"""分步短视频模式的阶段、模式切换与单镜生成契约（全程离线）。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import projects
from app.config import get_settings
from app.models import Project, ProjectStatus, Shot, ShotStatus, Template
from app.models_tasks import TaskRun
from app.schemas import ProjectCreate, ProjectUpdate
from app.services import pipeline
from app.services.billing.settlement import freeze_for_task
from app.services.media_models.prices import active_book, publish_book
from tests.conftest import make_user


def _shot(**overrides):
    """构造已有首帧、尚未生成视频的分镜。"""
    values = dict(
        id=11, shot_no=1, duration=8, narration="同一个三维卡通角色观察天空。",
        img_prompt="三维卡通角色", image_url="/static/shot.png", image_ark_url=None,
        audio_url=None, video_url=None, last_frame_url=None, video_skip_reason=None,
        video_prompt="@duration:8 缓慢推近", segment_script="@duration:8 缓慢推近",
        camera="push-in", status=ShotStatus.IMAGE_READY, version=1,
    )
    return SimpleNamespace(**{**values, **overrides})


def _project(**overrides):
    """构造可编辑的分步项目并保留模板生成参数。"""
    values = dict(
        id=1, user_id=7, creation_session_id=None, pipeline_mode="full",
        status=ProjectStatus.DONE, progress=100, final_video_url="/static/final.mp4",
        error_msg=None, active_tasks=[], shots=[_shot()], output_ratio="9:16",
        resolution_mode="hd", image_resolution="2K", video_resolution="720p",
        style_prompt="统一三维卡通画风", video_model="seedance-2-5",
        template=SimpleNamespace(style_prefix="三维卡通", default_ratio="16:9",
                                 seedance_config={"motion_bias": "平稳", "character_consistency": True}),
    )
    return SimpleNamespace(**{**values, **overrides})


def _api_context(monkeypatch, project):
    """隔离拥有者查询与数据库提交，仅记录实际路由创建的任务。"""
    monkeypatch.setattr(projects, "_get_owned_project", AsyncMock(return_value=project))
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    user = SimpleNamespace(id=project.user_id)
    return db, user


@pytest.mark.parametrize("before,after,ready_audio,expected", [
    ("image_text", "full", False, ProjectStatus.IMAGE_READY),
    ("full", "image_text", False, ProjectStatus.SCRIPT_READY),
    ("full", "image_text", True, ProjectStatus.VIDEO_READY),
])
async def test_mode_change_invalidates_final_and_resolves_new_stage(
    monkeypatch, before, after, ready_audio, expected,
):
    """切换制作模式沿用已有素材，但成片与就绪状态必须按新模式重算。"""
    project = _project(pipeline_mode=before)
    image = project.shots[0].image_url
    monkeypatch.setattr(get_settings(), "kepu_seedance_native_audio", True)
    monkeypatch.setattr("app.services.kepu_stages.continuous_narration_ok", lambda _id: ready_audio)
    monkeypatch.setattr("app.services.kepu_stages.shot_audio_file_ok", lambda _shot: ready_audio)
    db, user = _api_context(monkeypatch, project)

    updated = await projects.update_project(project.id, ProjectUpdate(pipeline_mode=after), db, user)

    assert updated.pipeline_mode == after
    assert updated.final_video_url is None
    assert updated.status == expected
    assert updated.shots[0].image_url == image
    db.commit.assert_awaited_once()


async def test_unchanged_mode_preserves_completed_output(monkeypatch):
    """重复保存同一模式不会让已完成作品失效。"""
    project = _project()
    db, user = _api_context(monkeypatch, project)
    await projects.update_project(project.id, ProjectUpdate(pipeline_mode="full"), db, user)
    assert project.status == ProjectStatus.DONE
    assert project.final_video_url == "/static/final.mp4"


async def test_mode_and_bgm_change_rechecks_new_mode_even_from_image_ready(monkeypatch):
    """素材就绪状态和同时保存的配乐不能掩盖新模式所缺的配音阶段。"""
    project = _project(status=ProjectStatus.IMAGE_READY)
    monkeypatch.setattr("app.services.kepu_stages.continuous_narration_ok", lambda _id: False)
    monkeypatch.setattr("app.services.kepu_stages.shot_audio_file_ok", lambda _shot: False)
    db, user = _api_context(monkeypatch, project)
    await projects.update_project(
        project.id, ProjectUpdate(pipeline_mode="image_text", bgm_lock="轻快"), db, user,
    )
    assert project.pipeline_mode == "image_text" and project.bgm_lock == "轻快"
    assert project.status == ProjectStatus.SCRIPT_READY
    assert project.final_video_url is None


async def test_mode_change_rejects_active_generation(monkeypatch):
    """视频生成执行期间不能改模式而让计费与实际阶段分离。"""
    project = _project(status=ProjectStatus.VIDEOING)
    db, user = _api_context(monkeypatch, project)
    with pytest.raises(HTTPException) as error:
        await projects.update_project(project.id, ProjectUpdate(pipeline_mode="image_text"), db, user)
    assert error.value.status_code == 409
    assert project.pipeline_mode == "full"
    db.commit.assert_not_awaited()


async def test_full_generate_routes_script_assets_and_video_before_compose(monkeypatch):
    """完整模式每次只入队一个付费阶段，全部视频就绪后改走专用合成任务。"""
    project = _project(status=ProjectStatus.DRAFT, shots=[], final_video_url=None)
    db, user = _api_context(monkeypatch, project)
    create_task = AsyncMock()
    monkeypatch.setattr(projects, "create_task", create_task)
    monkeypatch.setattr(get_settings(), "kepu_seedance_native_audio", True)
    monkeypatch.setattr(projects, "list_active_tasks_for_owner", AsyncMock(return_value=[]))

    await projects.generate_project(project.id, db=db, user=user)
    assert create_task.await_args.args[2].payload["phase"] == "script"
    assert create_task.await_args.args[2].payload["pipeline_mode"] == "full"
    assert project.status == ProjectStatus.SCRIPTING

    project.status = ProjectStatus.SCRIPT_READY
    project.shots = [_shot(image_url=None)]
    await projects.generate_project(project.id, db=db, user=user)
    assert create_task.await_args.args[2].payload["phase"] == "assets"
    assert project.status == ProjectStatus.IMAGING

    project.status = ProjectStatus.IMAGE_READY
    project.shots[0].image_url = "/static/shot.png"
    await projects.generate_project(project.id, db=db, user=user)
    assert create_task.await_args.args[2].payload["phase"] == "videos"
    assert project.status == ProjectStatus.VIDEOING

    project.status = ProjectStatus.VIDEO_READY
    project.shots[0].video_url = "/static/shot.mp4"
    with pytest.raises(HTTPException, match="409"):
        await projects.generate_project(project.id, db=db, user=user)
    assert create_task.await_count == 3
    await projects.compose_only(project.id, db=db, user=user)
    assert create_task.await_args.args[2].task_type == "project_compose_only"
    assert project.status == ProjectStatus.COMPOSING


@pytest.mark.parametrize("mode,has_image,allowed", [
    ("full", True, True), ("full", False, False), ("image_text", True, False),
])
async def test_regen_video_requires_full_mode_and_a_starting_image(monkeypatch, mode, has_image, allowed):
    """视频重生成只允许完整模式、且已有首帧的分镜。"""
    project = _project(pipeline_mode=mode, shots=[_shot(image_url="/static/shot.png" if has_image else None)])
    db, user = _api_context(monkeypatch, project)
    create_task = AsyncMock()
    monkeypatch.setattr(projects, "_create_kepu_task", create_task)
    if allowed:
        await projects.regen_video(project.id, 11, db, user)
        assert create_task.await_args.kwargs["task_type"] == "shot_regen_video"
        assert project.status == ProjectStatus.VIDEOING
    else:
        with pytest.raises(HTTPException) as error:
            await projects.regen_video(project.id, 11, db, user)
        assert error.value.status_code == 400
        create_task.assert_not_awaited()
        db.commit.assert_not_awaited()


def test_full_create_contract_preserves_user_media_choices():
    """创建参数支持视频模式、参考图、选定的模型和输出清晰度。"""
    request = ProjectCreate(
        template_id="anim_3d", source_text="讲解天空为什么是蓝色。", pipeline_mode="full",
        ref_image_url="/static/reference.png", image_model="gpt-image-1.5", image_resolution="2K",
        video_model="seedance-2-5", video_resolution="720p", target_duration_sec=60,
    )
    assert request.pipeline_mode == "full"
    assert request.ref_image_url == "/static/reference.png"
    assert request.image_model == "gpt-image-1.5" and request.image_resolution == "2K"
    assert request.video_model == "seedance-2-5" and request.video_resolution == "720p"


@pytest.mark.parametrize("upstream_image,expected_first_frame", [
    ("https://media.example/start-1.png", "https://media.example/start-1.png"),
    ("https://www.tokenfree.com/v1/tasks/t1/artifacts/image-0/content", "/static/shot.png"),
])
@pytest.mark.parametrize("billing_mode", ["legacy", "fixed_media"])
async def test_full_video_generation_uses_own_image_and_previous_tail_with_native_audio(
    monkeypatch, upstream_image, expected_first_frame, billing_mode,
):
    """图生视频沿用本镜首帧、前镜尾帧、脚本时长和项目模型，完整模式保留内置口播。"""
    shot1 = _shot(image_ark_url=upstream_image, duration=3,
                  segment_script="@duration:4 观察天空\n@duration:4 蓝光向四周散射")
    shot2 = _shot(id=12, shot_no=2, image_url="/static/start-2.png", duration=6,
                  segment_script="@duration:6 同一个角色展示蓝色天空")
    project = _project(shots=[shot2, shot1], final_video_url=None, status=ProjectStatus.IMAGE_READY)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one=lambda: project)), commit=AsyncMock(),
    )

    async def get_row(model, row_id):
        """模拟项目与两镜的持久化回读。"""
        return project if model is Project else {shot1.id: shot1, shot2.id: shot2}.get(row_id)

    @asynccontextmanager
    async def session():
        """为每次分镜写回提供同一离线数据库替身。"""
        yield db

    db.get = AsyncMock(side_effect=get_row)
    generate_video = AsyncMock(side_effect=[
        ("/static/video-1.mp4", SimpleNamespace(last_frame_url="/static/tail-1.png", provider_task_id="video-task-1")),
        ("/static/video-2.mp4", SimpleNamespace(last_frame_url="/static/tail-2.png", provider_task_id="video-task-2")),
    ])
    record_usage = AsyncMock()
    fixed_record_usage = AsyncMock()
    monkeypatch.setattr(get_settings(), "kepu_seedance_native_audio", True)
    monkeypatch.setattr(pipeline, "AsyncSessionLocal", session)
    monkeypatch.setattr(pipeline, "get_ark", lambda: SimpleNamespace(gen_and_wait_video=generate_video))
    monkeypatch.setattr(pipeline, "_ensure_not_cancelled", AsyncMock())
    monkeypatch.setattr(pipeline, "_set_status", AsyncMock())
    monkeypatch.setattr(pipeline, "publish_progress", AsyncMock())
    monkeypatch.setattr(pipeline, "_record_seedance_usage", record_usage)
    monkeypatch.setattr("app.services.drama.billing_util.record_seedance_video_usage", fixed_record_usage)
    monkeypatch.setattr(pipeline, "persist_last_frame_from_video", lambda *args, **kwargs: kwargs.get("preferred_url"))

    from app.services.media_models.runtime import current_snapshot
    token = current_snapshot.set({"mode": "fixed_media"} if billing_mode == "fixed_media" else None)
    try:
        await pipeline._parallel_videos(project.id)
    finally:
        current_snapshot.reset(token)

    first, second = generate_video.await_args_list
    assert first.args[0] == expected_first_frame
    assert second.args[0] == "/static/start-2.png"
    assert first.args[2] == 8 and second.args[2] == 6
    assert first.kwargs["extra_image_urls"] is None
    assert second.kwargs["extra_image_urls"] == ["/static/tail-1.png"]
    for call in (first, second):
        assert call.kwargs["generate_audio"] is True
        assert call.kwargs["model"] == "seedance-2-5"
        assert call.kwargs["resolution"] == "720p" and call.kwargs["ratio"] == "9:16"
        assert call.kwargs["character_consistency"] is True
        assert "三维卡通" in call.args[1]
    assert shot1.video_url == "/static/video-1.mp4" and shot2.video_url == "/static/video-2.mp4"
    assert project.status == ProjectStatus.VIDEO_READY and project.progress == 88
    selected_usage = fixed_record_usage if billing_mode == "fixed_media" else record_usage
    unused_usage = record_usage if billing_mode == "fixed_media" else fixed_record_usage
    assert [call.kwargs["fallback_duration_sec"] for call in selected_usage.await_args_list] == [8, 6]
    assert all(call.kwargs["billing_key"] == "seedance2:video0" for call in selected_usage.await_args_list)
    unused_usage.assert_not_awaited()
    if billing_mode == "fixed_media":
        assert all(call.kwargs["user_id"] == project.user_id for call in selected_usage.await_args_list)
        assert [call.kwargs["shot_id"] for call in selected_usage.await_args_list] == [shot1.id, shot2.id]
        assert [call.kwargs["provider_task_id"] for call in selected_usage.await_args_list] == ["video-task-1", "video-task-2"]


async def test_full_project_video_admission_reserves_only_remaining_video_cost(db_session, monkeypatch):
    """真实创建/入队/冻结链路只为尚缺的视频预扣，不重复计入已有视频与图片。"""
    db = db_session
    user = await make_user(db, balance_fen=100_000)
    template = await db.get(Template, "anim_3d")
    if template is None:
        db.add(Template(id="anim_3d", name="3D动画", style_prefix="三维卡通"))
        await db.flush()
    book = await active_book(db)
    await publish_book(
        db, prices={"seedance-2.5": {"720p": "0.5000"}},
        expected_version=book["version"] if book else None, user_id=user.id,
    )
    monkeypatch.setattr(get_settings(), "kepu_seedance_native_audio", True)
    monkeypatch.setattr(get_settings(), "ark_mock", True)
    project = await projects.create_project(ProjectCreate(
        template_id="anim_3d", source_text="讲解天空为什么是蓝色。", pipeline_mode="full",
        video_model="seedance-2.5", video_resolution="720p", output_ratio="9:16",
    ), db, user)
    project.shots = [
        Shot(shot_no=1, duration=8, image_url="/static/first.png", segment_script="@duration:8 观察天空"),
        Shot(shot_no=2, duration=6, image_url="/static/second.png", video_url="/static/kept.mp4"),
    ]
    project.status = ProjectStatus.IMAGE_READY
    await db.commit()

    generated = await projects.generate_project(project.id, db=db, user=user)
    task = (await db.execute(select(TaskRun).where(TaskRun.project_id == project.id))).scalar_one()
    assert generated.pipeline_mode == "full" and generated.status == ProjectStatus.VIDEOING
    assert task.payload["phase"] == "videos"
    assert task.billing_snapshot["mode"] == "fixed_media"
    items = task.billing_snapshot["items"]
    assert len(items) == 1 and items[0]["target_id"] == project.shots[0].id
    assert items[0]["params"]["duration"] == 8
    assert items[0]["model_id"] == "seedance-2.5" and items[0]["params"]["resolution"] == "720p"
    before = user.balance_fen
    reserved = await freeze_for_task(db, task)
    assert reserved == 400
    assert user.balance_fen == before - reserved and user.frozen_fen == reserved
    assert task.billing_status == "frozen"


@pytest.mark.parametrize("upstream_image,expected_first_frame", [
    ("https://media.example/start-2.png", "https://media.example/start-2.png"),
    ("https://www.tokenfree.com/v1/tasks/t2/artifacts/image-0/content", "/static/start-2.png"),
])
async def test_single_video_regeneration_preserves_image_duration_and_audio_contract(
    monkeypatch, upstream_image, expected_first_frame,
):
    """单镜重生成使用与批量生成一致的首帧选择、前镜尾帧和内置口播参数。"""
    first = _shot(last_frame_url="/static/previous-tail.png", video_url="/static/kept.mp4")
    shot = _shot(id=12, shot_no=2, duration=3, image_ark_url=upstream_image,
                 image_url="/static/start-2.png", segment_script="@duration:9 同一个角色继续讲解")
    project = _project(shots=[first, shot], status=ProjectStatus.VIDEO_READY)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one=lambda: project)),
                         commit=AsyncMock())

    async def get_row(model, row_id):
        """为单镜重生成提供对应的项目与分镜。"""
        return project if model is Project else shot

    @asynccontextmanager
    async def session():
        """用内存替身隔离重生成的写回。"""
        yield db

    db.get = AsyncMock(side_effect=get_row)
    generate_video = AsyncMock(return_value=("/static/regenerated.mp4", SimpleNamespace(last_frame_url="/static/new-tail.png")))
    monkeypatch.setattr(get_settings(), "kepu_seedance_native_audio", True)
    monkeypatch.setattr(pipeline, "AsyncSessionLocal", session)
    monkeypatch.setattr(pipeline, "get_ark", lambda: SimpleNamespace(gen_and_wait_video=generate_video))
    monkeypatch.setattr(pipeline, "_record_seedance_usage", AsyncMock())
    monkeypatch.setattr(pipeline, "persist_last_frame_from_video", lambda *args, **kwargs: kwargs.get("preferred_url"))

    await pipeline.regen_shot_video(project.id, shot.id)

    call = generate_video.await_args
    assert call.args[0] == expected_first_frame and call.args[2] == 9
    assert call.kwargs["extra_image_urls"] == ["/static/previous-tail.png"]
    assert call.kwargs["generate_audio"] is True and call.kwargs["character_consistency"] is True
    assert call.kwargs["model"] == "seedance-2-5"
    assert call.kwargs["resolution"] == "720p" and call.kwargs["ratio"] == "9:16"
    assert shot.video_url == "/static/regenerated.mp4" and shot.last_frame_url == "/static/new-tail.png"
    assert project.final_video_url is None
