"""Pipeline orchestration — in-process runtime used by the task platform."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import PipelineJob, Project, ProjectStatus, Shot, ShotStatus
from app.services.ark import get_ark
from app.services.ffmpeg_compose import (
    ComposeOptions,
    FfmpegInterrupted,
    ShotMedia,
    allocate_durations_by_narration,
    compose_project,
    is_ffmpeg_interrupted_error,
    is_near_silent_audio,
    probe_duration,
)
from app.services.progress import publish_progress
from app.services import storage
from app.services.style_lock import (
    build_locked_image_prompt,
    merge_negative,
    strip_lock_blocks,
    template_allow_source_names,
    template_consistency_mode,
    template_is_photoreal,
    template_shot_range,
)
from app.services.kepu_continuity import (
    image_refs_for_shot,
    persist_last_frame_from_video,
    previous_usable_shot,
    video_image_ref,
    video_extra_refs_for_shot,
)
from app.services.kepu_image_references import project_image_references
from app.services.voices import resolve_speaker
from app.services import seedance_segments as segplan
from app.services.bgm import clip_shot_bgm, resolve_bgm_path

logger = logging.getLogger(__name__)

# 成片 FFmpeg 被 SIGTERM 打断时的自动重试次数
_COMPOSE_SIGTERM_MAX_ATTEMPTS = 3

_cancelled: set[int] = set()


async def _record_usage_est(
    project_id: int,
    billing_key: str,
    *,
    tokens: int = 0,
    model: str = "",
    estimated: bool = True,
    shot_id: int | None = None,
) -> None:
    try:
        from app.services.billing import record_line

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if not project:
                return
            await record_line(
                db,
                user_id=project.user_id,
                billing_key=billing_key,
                model=model,
                tokens=tokens,
                estimated=estimated,
                project_id=project_id,
                shot_id=shot_id,
                domain="kepu",
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("billing record failed project=%s key=%s", project_id, billing_key)


async def _record_seedream_usage(
    project_id: int,
    *,
    image_result,
    model: str,
    shot_id: int | None = None,
    delivered: bool = True,
) -> None:
    try:
        from app.services.drama.billing_util import record_seedream_image_usage

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if not project:
                return
            await record_seedream_image_usage(
                db,
                user_id=project.user_id,
                model=model,
                domain="kepu",
                image_result=image_result,
                delivered=delivered,
                project_id=project_id,
                shot_id=shot_id,
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("seedream billing record failed project=%s", project_id)


async def _record_seedance_usage(
    project_id: int,
    *,
    billing_key: str,
    model: str,
    task_result,
    fallback_duration_sec: float,
    shot_id: int | None = None,
    delivered: bool = True,
) -> None:
    try:
        from app.services.drama.billing_util import record_seedance_video_usage

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if not project:
                return
            from app.services.seedance_resolutions import project_video_resolution
            res = project_video_resolution(project)
            await record_seedance_video_usage(
                db,
                user_id=project.user_id,
                billing_key=billing_key,
                model=model,
                domain="kepu",
                task_result=task_result,
                delivered=delivered,
                fallback_duration_sec=fallback_duration_sec,
                resolution=res,
                provider_task_id=getattr(task_result, "provider_task_id", None),
                project_id=project_id,
                shot_id=shot_id,
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("seedance billing record failed project=%s key=%s", project_id, billing_key)
# Seedream min pixels ~3686400; portrait 9:16 ≈ 1440x2560
_IMAGE_SIZE_BY_RATIO = {
    "9:16": "1440x2560",
    "16:9": "2560x1440",
    "1:1": "1920x1920",
    "4:3": "1920x1440",
    "21:9": "2560x1080",
}

IMAGE_TEXT_DURATION_MIN = 4
IMAGE_TEXT_DURATION_MAX = 12


class PipelineCancelled(Exception):
    """Raised when user cancels a running pipeline."""


def cancel_pipeline(project_id: int) -> bool:
    """标记项目取消；流水线由任务平台 executor 驱动，无进程内任务可停，恒返回 False。"""
    _cancelled.add(project_id)
    return False


def is_cancelled(project_id: int) -> bool:
    return project_id in _cancelled


def clear_pipeline_cancellation(project_id: int) -> None:
    """Only explicit resume paths clear a previous user-cancellation marker."""
    _cancelled.discard(project_id)


def _is_image_text(project: Project) -> bool:
    return (getattr(project, "pipeline_mode", None) or "full") == "image_text"


def _kepu_seedance_native_audio(project: Project | None = None) -> bool:
    """科普 full：Seedance 视频内置口播，不走外部 TTS。"""
    if project is not None and _is_image_text(project):
        return False
    return bool(getattr(get_settings(), "kepu_seedance_native_audio", True))


def _kepu_seedance_sfx_audio(project: Project | None = None) -> bool:
    """科普 full 回退：Seedance 只要操作音效，口播改后期 TTS。"""
    if _kepu_seedance_native_audio(project):
        return False
    if project is not None and _is_image_text(project):
        return False
    return bool(get_settings().kepu_seedance_sfx_audio)


def _kepu_seedance_generate_audio(project: Project | None = None) -> bool:
    """是否向 Seedance 要音轨（内置口播或仅音效）。"""
    return _kepu_seedance_native_audio(project) or _kepu_seedance_sfx_audio(project)


def _project_output_ratio(project: Project) -> str:
    """User-selected output ratio, else template default, else 16:9."""
    allowed = {"16:9", "9:16", "1:1", "4:3", "21:9"}
    user = (getattr(project, "output_ratio", None) or "").strip()
    if user in allowed:
        return user
    tpl_ratio = (project.template.default_ratio if project.template else None) or ""
    if tpl_ratio in allowed:
        return tpl_ratio
    return "16:9"


def _project_voice(project: Project) -> str:
    tpl_preset = ""
    if project.template and project.template.audio_config:
        tpl_preset = str(project.template.audio_config.get("voice_preset") or "")
    return resolve_speaker(getattr(project, "voice_id", None) or "", template_preset=tpl_preset)


def clamp_shot_duration(duration: float, *, pipeline_mode: str, tpl_min: int, tpl_max: int) -> float:
    """将单镜时长钳到模板区间；完整模式再压到科普节奏上限。"""
    settings = get_settings()
    if pipeline_mode == "image_text":
        lo = IMAGE_TEXT_DURATION_MIN
        hi = IMAGE_TEXT_DURATION_MAX
    else:
        hi = min(max(tpl_max, 1), settings.max_shot_duration, segplan.KEPU_FULL_SHOT_DURATION_MAX)
        lo = max(1, min(tpl_min, hi))
    return float(max(lo, min(float(duration), hi)))


def _merge_subtitle_preset(sub_cfg: dict, preset: str) -> dict:
    """科普字幕预设覆盖模板 subtitle_config。"""
    out = dict(sub_cfg or {})
    key = (preset or "").strip().lower()
    if key == "large":
        out["caption_scale"] = 1.55
    elif key == "split":
        out["position"] = "split"
    elif key == "standard":
        out["caption_scale"] = 1.25
        out["position"] = "top"
    return out


def _kepu_video_prompt(
    script: str,
    *,
    style_prefix: str,
    motion_bias: str,
    camera: str,
    ambient_only: bool,
    no_bgm: bool = False,
) -> str:
    """科普提交 Seedance：后期叠字，禁止模型烧录字幕。"""
    return segplan.build_seedance_prompt(
        segplan.normalize_kepu_subtitle_cue(script or ""),
        style_prefix=style_prefix,
        motion_bias=motion_bias,
        camera=camera,
        ambient_only=ambient_only,
        burn_subtitles=False,
        no_bgm=no_bgm,
    )


async def _ensure_not_cancelled(project_id: int) -> None:
    if is_cancelled(project_id):
        raise PipelineCancelled(f"project {project_id} cancelled")
    # Cross-process (Celery worker): cancel API writes CANCELLED to DB
    async with AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        if project and project.status == ProjectStatus.CANCELLED:
            _cancelled.add(project_id)
            raise PipelineCancelled(f"project {project_id} cancelled")


def _full_narration_path(project_id: int) -> Path:
    return storage.project_dir(project_id) / "full_narration.mp3"


def join_shot_narrations(narrations: list[str]) -> str:
    """Merge per-shot旁白 into one continuous TTS script (punctuation = natural breath)."""
    parts: list[str] = []
    for raw in narrations:
        t = (raw or "").strip()
        if not t:
            continue
        if t[-1] not in "。！？；…,.!?;":
            t += "。"
        parts.append(t)
    return "".join(parts)


def _continuous_audio_ok(project_id: int) -> bool:
    from app.services.kepu_stages import continuous_narration_ok

    return continuous_narration_ok(project_id)


async def _synthesize_continuous_audio(
    project_id: int,
    *,
    voice: str,
    shot_rows: list,
    force: bool = False,
) -> Path:
    """One TTS pass for the whole film; redistribute shot durations by narration weight."""
    dest = _full_narration_path(project_id)
    narrations = [(getattr(s, "narration", None) or "") for s in shot_rows]
    full_text = join_shot_narrations(narrations)
    if not full_text.strip():
        raise ValueError("全部镜头旁白为空，无法配音")

    ark = get_ark()
    regenerated = force or not _continuous_audio_ok(project_id)
    if regenerated:
        hint = sum(max(float(getattr(s, "duration", 4) or 4), 2.0) for s in shot_rows)
        audio_url = await ark.tts(
            full_text,
            voice,
            project_id=project_id,
            shot_no=0,
            duration_hint=hint,
        )
        s = get_settings()
        await _record_usage_est(
            project_id,
            "tts",
            tokens=s.billing_est_tts_tokens * max(len(shot_rows), 1),
            model=s.model_audio,
        )
        src = storage.local_path_from_url(audio_url or "")
        if not src or not src.exists():
            raise RuntimeError("整片配音生成失败")
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        # 新合成必须复查近静音：TTS 偶发返回极低音量音频，静默合成会产出无声成片
        if is_near_silent_audio(dest):
            raise RuntimeError("整片配音近静音（音量异常），请重新配音")

    dur = await asyncio.to_thread(probe_duration, dest)
    if not dur or dur < 0.8:
        raise RuntimeError("整片配音时长异常")

    allocated = allocate_durations_by_narration(narrations, dur)
    async with _db_write_lock():
        async with AsyncSessionLocal() as db:
            for shot, new_dur in zip(shot_rows, allocated):
                row = await db.get(Shot, shot.id)
                if not row:
                    continue
                row.duration = float(new_dur)
                # Point every shot at the same continuous file (compose prefers full_narration)
                row.audio_url = storage.publish_local(dest)
                if row.status == ShotStatus.PENDING:
                    row.status = ShotStatus.AUDIO_READY
            await db.commit()
    return dest


async def _resume_plan(project_id: int) -> tuple[bool, bool, bool, bool]:
    """Return (image_text, skip_script, skip_assets, skip_videos).

    When shots already have images (+ audio / videos as needed), resume from
    the next unfinished stage instead of wiping the storyboard.
    """
    from app.services.kepu_stages import project_audio_ready, shot_image_ready, shot_video_ready

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots))
        )
        project = result.scalar_one_or_none()
        if not project or not project.shots:
            return False, False, False, False
        image_text = _is_image_text(project)
        shots = list(project.shots)
        has_images = all(shot_image_ready(s) for s in shots)
        # 与计费 resolve_kepu_billing_phase 共用旁白就绪规则
        has_audio = project_audio_ready(project)
        has_videos = all(shot_video_ready(s) for s in shots)
        skip_script = len(shots) > 0
        skip_assets = has_images and has_audio
        skip_videos = image_text or has_videos
        return image_text, skip_script, skip_assets, skip_videos


@storage.without_intermediate_oss
async def run_pipeline(project_id: int, *, phase: str | None = None) -> None:
    """跑科普流水线；phase 指定时只执行该计费阶段，避免冻 A 跑 B。"""
    from app.services.kepu_stages import normalize_kepu_pipeline_phase

    try:
        await _ensure_not_cancelled(project_id)
        image_text, skip_script, skip_assets, skip_videos = await _resume_plan(project_id)

        requested: str | None = None
        if phase is not None:
            async with AsyncSessionLocal() as db:
                project = (
                    await db.execute(
                        select(Project)
                        .where(Project.id == project_id)
                        .options(selectinload(Project.shots))
                    )
                ).scalar_one_or_none()
            requested = normalize_kepu_pipeline_phase(phase, project)

        if not skip_script:
            if requested and requested not in {"script", "produce"}:
                raise RuntimeError(
                    f"分镜尚未就绪，无法执行阶段 {requested}；请先生成分镜脚本"
                )
            await _script_stage(project_id)
            await _ensure_not_cancelled(project_id)
            await publish_progress(
                project_id,
                {
                    "event": "paused",
                    "stage": "SCRIPT_READY",
                    "percent": 15,
                    "message": "分镜已生成，请确认修改后手动继续",
                },
            )
            return

        if requested == "script":
            # 文字任务直接执行时也不能因已有分镜而落入媒体生成分支。
            await publish_progress(project_id, {
                "event": "paused", "stage": "SCRIPT_READY", "percent": 15,
                "message": "分镜脚本已就绪，请确认后继续生成素材",
            })
            return

        logger.info(
            "pipeline resume project=%s phase=%s skip_script=%s skip_assets=%s skip_videos=%s",
            project_id,
            requested or "(auto)",
            skip_script,
            skip_assets,
            skip_videos,
        )
        await publish_progress(
            project_id,
            {
                "event": "progress",
                "stage": "RESUME",
                "percent": 70 if skip_assets else 18,
                "message": "沿用已有分镜，继续后续阶段",
            },
        )

        # 显式 phase：只跑对应阶段并暂停，保证与预扣一致
        if requested == "assets":
            if not skip_assets:
                await _parallel_image_and_audio(project_id)
                await _ensure_not_cancelled(project_id)
            await publish_progress(
                project_id,
                {
                    "event": "paused",
                    "stage": "ASSETS_READY",
                    "percent": 70 if image_text else 50,
                    "message": (
                        "分镜图与配音已完成，请确认后继续合成"
                        if image_text
                        else "分镜图与配音已完成，请确认后继续生成镜头视频"
                    ),
                },
            )
            return

        if requested == "videos":
            if not skip_assets:
                # 预扣按视频，但旁白/出图未齐：先补 assets 并停下，避免冻视频款去跑视频
                await _parallel_image_and_audio(project_id)
                await _ensure_not_cancelled(project_id)
                await publish_progress(
                    project_id,
                    {
                        "event": "paused",
                        "stage": "ASSETS_READY",
                        "percent": 50,
                        "message": "分镜图与配音已补齐，请再次点击继续生成镜头视频",
                    },
                )
                return
            if image_text or skip_videos:
                await publish_progress(
                    project_id,
                    {
                        "event": "paused",
                        "stage": "VIDEO_READY",
                        "percent": 88,
                        "message": "镜头视频已就绪，请确认后合成成片",
                    },
                )
                return
            await _parallel_videos(project_id)
            await _ensure_not_cancelled(project_id)
            await publish_progress(
                project_id,
                {
                    "event": "paused",
                    "stage": "VIDEO_READY",
                    "percent": 88,
                    "message": "镜头视频已完成，请确认后合成成片",
                },
            )
            return

        if requested == "compose":
            await _compose_stage(project_id)
            if is_cancelled(project_id):
                raise PipelineCancelled(f"project {project_id} cancelled")
            async with AsyncSessionLocal() as db:
                project = await db.get(Project, project_id)
                if project:
                    if project.status == ProjectStatus.CANCELLED:
                        raise PipelineCancelled(f"project {project_id} cancelled")
                    project.status = ProjectStatus.DONE
                    project.progress = 100
                    project.error_msg = None
                    await db.commit()
            await publish_progress(
                project_id,
                {"event": "done", "percent": 100, "video_url": await _final_url(project_id)},
            )
            return

        # 无 phase（旧任务/兼容）：每段只跑一步后暂停
        if not skip_assets:
            await _parallel_image_and_audio(project_id)
            await _ensure_not_cancelled(project_id)
            await publish_progress(
                project_id,
                {
                    "event": "paused",
                    "stage": "ASSETS_READY",
                    "percent": 70 if image_text else 50,
                    "message": (
                        "分镜图与配音已完成，请确认后继续合成"
                        if image_text
                        else "分镜图与配音已完成，请确认后继续生成镜头视频"
                    ),
                },
            )
            return

        if not image_text and not skip_videos:
            await _parallel_videos(project_id)
            await _ensure_not_cancelled(project_id)
            await publish_progress(
                project_id,
                {
                    "event": "paused",
                    "stage": "VIDEO_READY",
                    "percent": 88,
                    "message": "镜头视频已完成，请确认后合成成片",
                },
            )
            return

        await _compose_stage(project_id)

        if is_cancelled(project_id):
            raise PipelineCancelled(f"project {project_id} cancelled")

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project:
                if project.status == ProjectStatus.CANCELLED:
                    raise PipelineCancelled(f"project {project_id} cancelled")
                project.status = ProjectStatus.DONE
                project.progress = 100
                project.error_msg = None
                await db.commit()
        await publish_progress(
            project_id,
            {"event": "done", "percent": 100, "video_url": await _final_url(project_id)},
        )
    except (PipelineCancelled, asyncio.CancelledError) as exc:
        # 落项目态、推 SSE 后必须 re-raise：本函数由任务平台 executor 驱动，
        # 吞掉会让 TaskRun 误判 succeeded 扣费，并破坏 asyncio 任务取消语义。
        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            requested = (
                isinstance(exc, PipelineCancelled)
                or is_cancelled(project_id)
                or (project is not None and project.status == ProjectStatus.CANCELLED)
            )
            if not requested:
                # 服务中断后调度器会重排同一任务，保留成功素材及可恢复状态。
                logger.info("pipeline interrupted; preserving resume state project=%s", project_id)
                raise
            logger.info("pipeline cancelled project=%s", project_id)
            if project and project.status != ProjectStatus.DONE:
                project.status = ProjectStatus.CANCELLED
                project.error_msg = "用户取消"
                await db.commit()
        await publish_progress(
            project_id,
            {
                "event": "failed",
                "stage": "CANCELLED",
                "message": "用户取消",
                "retryable": True,
                "code": "CANCELLED",
            },
        )
        raise
    except Exception as exc:  # noqa: BLE001
        if is_cancelled(project_id):
            logger.info("pipeline cancelled (during error) project=%s", project_id)
            async with AsyncSessionLocal() as db:
                project = await db.get(Project, project_id)
                if project and project.status != ProjectStatus.DONE:
                    project.status = ProjectStatus.CANCELLED
                    project.error_msg = "用户取消"
                    await db.commit()
            await publish_progress(
                project_id,
                {
                    "event": "failed",
                    "stage": "CANCELLED",
                    "message": "用户取消",
                    "retryable": True,
                    "code": "CANCELLED",
                },
            )
            raise PipelineCancelled(f"project {project_id} cancelled") from exc
        logger.exception("pipeline failed project=%s", project_id)
        fail_msg = (
            "FFmpeg 被系统中断（signal 15），请点击重新拼接"
            if is_ffmpeg_interrupted_error(exc)
            else str(exc)[:2000]
        )
        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project:
                project.status = ProjectStatus.FAILED
                project.error_msg = fail_msg
                await db.commit()
        await publish_progress(
            project_id,
            {
                "event": "failed",
                "stage": "PIPELINE",
                "message": fail_msg,
                "retryable": True,
                "code": "PIPELINE_ERROR",
            },
        )
        raise
    finally:
        _cancelled.discard(project_id)


async def delete_project_assets(project_id: int) -> None:
    pdir = storage.GENERATED_ROOT / f"p{project_id}"
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)


async def _final_url(project_id: int) -> str | None:
    async with AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        return project.final_video_url if project else None


async def _set_status(project_id: int, status: str, progress: int, stage: str) -> None:
    await _ensure_not_cancelled(project_id)
    async with AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        if not project:
            return
        project.status = status
        project.progress = progress
        db.add(PipelineJob(project_id=project_id, stage=stage, progress=progress))
        await db.commit()
    await publish_progress(project_id, {"event": "progress", "stage": stage, "percent": progress})


async def _script_stage(project_id: int) -> None:
    await _set_status(project_id, ProjectStatus.SCRIPTING, 5, "SCRIPTING")
    ark = get_ark()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.template), selectinload(Project.shots))
        )
        project = result.scalar_one()
        tpl = project.template
        image_text = _is_image_text(project)
        mode = project.pipeline_mode or "full"
        if image_text:
            d_min, d_max = IMAGE_TEXT_DURATION_MIN, IMAGE_TEXT_DURATION_MAX
        else:
            d_min = tpl.shot_duration_min
            d_max = min(
                tpl.shot_duration_max,
                get_settings().max_shot_duration,
                segplan.KEPU_FULL_SHOT_DURATION_MAX,
            )

        style = _effective_style(project)
        extra = _effective_extra(project)
        if image_text:
            target = int(getattr(project, "target_duration_sec", 60) or 60)
            extra = f"{extra}\n成片目标约 {target} 秒。每镜一个清晰画面，按旁白节奏分配镜头。".strip()
            if project.source_type == "script":
                extra += "严格保留用户已生成文案的全部旁白，只拆分镜头，不增加或删改旁白。"
        char_hint = _effective_character_prompt(project)
        consist = template_consistency_mode(tpl)
        plans_result = await ark.chat_storyboard(
            source_text=project.source_text,
            source_type=project.source_type,
            style_prefix=style,
            llm_system_addon=tpl.llm_system_addon,
            duration_min=d_min,
            duration_max=d_max,
            max_shot_duration=d_max,
            pipeline_mode=mode,
            # 仅用户显式覆盖才当强制人设；模板角色交给 llm_system_addon 与主题由 AI 决定
            character_hint=char_hint,
            extra_requirements=extra,
            consistency_mode=consist,
            output_ratio=_project_output_ratio(project),
            shot_range_override=template_shot_range(tpl),
            allow_source_names=template_allow_source_names(tpl),
        )
        plans = plans_result.shots
        project.character_bible = resolve_script_character_bible(
            char_hint,
            plans_result.character_bible,
        )
        tpl_bgm = ""
        if tpl and isinstance(tpl.audio_config, dict):
            tpl_bgm = str(tpl.audio_config.get("bgm_mood") or "").strip()
        # 风格页用户选曲优先，其次 LLM / 模板推断
        user_bgm = (getattr(project, "bgm_lock", None) or "").strip()
        project.bgm_lock = (
            user_bgm
            or (plans_result.bgm_lock or "").strip()
            or tpl_bgm
            or (plans[0].bgm if plans else "")
            or "轻快专业"
        )
        for shot in list(project.shots):
            await db.delete(shot)
        await db.flush()
        bible = project.character_bible
        for plan in plans:
            segment_script = (plan.segment_script or plan.video_prompt or "").strip()
            # 时长以脚本 @duration 合计为准（与列表「逐段分镜」标签一致），勿只用 LLM duration 字段
            script_total = segplan.sum_duration(segment_script)
            dur = clamp_shot_duration(
                float(script_total if script_total > 0 else plan.duration),
                pipeline_mode=mode,
                tpl_min=tpl.shot_duration_min,
                tpl_max=tpl.shot_duration_max,
            )
            # Store scene-only prompt for UI; locks applied at Seedream time
            scene = strip_lock_blocks(plan.img_prompt)
            # Drop duplicated style / bible text from stored scene prompt
            if style and style in scene:
                scene = scene.replace(style, "", 1)
            if bible and bible[:24] in scene:
                scene = scene.replace(bible, "", 1)
            scene = strip_lock_blocks(scene)
            img_prompt = ark._sanitize_seedream_prompt(scene)
            db.add(
                Shot(
                    project_id=project.id,
                    shot_no=plan.shot,
                    duration=dur,
                    narration=plan.text,
                    overlay_title=plan.overlay_title or "",
                    overlay_subtitle=plan.overlay_subtitle or "",
                    img_prompt=img_prompt,
                    video_prompt=segment_script or plan.video_prompt,
                    segment_script=segment_script,
                    camera=plan.camera,
                    bgm_mood=clip_shot_bgm(project.bgm_lock or plan.bgm),
                    status=ShotStatus.PENDING,
                )
            )
        project.status = ProjectStatus.SCRIPT_READY
        project.progress = 15
        await db.commit()
    s = get_settings()
    await _record_usage_est(
        project_id,
        "llm_chat",
        tokens=s.billing_est_llm_tokens,
        model=s.model_llm,
    )
    await publish_progress(project_id, {"event": "progress", "stage": "SCRIPT_READY", "percent": 15})


def _effective_style(project: Project) -> str:
    user = (getattr(project, "style_prompt", None) or "").strip()
    tpl = project.template
    base = (tpl.style_prefix if tpl else "") or ""
    return user or base


def _template_seedream_field(project: Project, key: str) -> str:
    tpl = project.template
    if not tpl:
        return ""
    cfg = getattr(tpl, "seedream_config", None) or {}
    if not isinstance(cfg, dict):
        return ""
    return str(cfg.get(key) or "").strip()


def _effective_character_prompt(project: Project) -> str:
    """仅用户在项目里写的角色覆盖；模板角色不当作用户强制约束。"""
    return (getattr(project, "character_prompt", None) or "").strip()


def resolve_script_character_bible(user_character_prompt: str, llm_bible: str = "") -> str:
    """用户覆盖优先，否则用分镜 LLM 的 character_bible。"""
    user = (user_character_prompt or "").strip()
    if user:
        return user
    return (llm_bible or "").strip() or "无固定人物，各镜独立场景"


def _effective_extra(project: Project) -> str:
    user = (getattr(project, "extra_prompt", None) or "").strip()
    return user or _template_seedream_field(project, "extra_prompt")


def _image_size_for(project: Project) -> str | None:
    explicit = str(getattr(project, "image_resolution", "") or "").strip().upper()
    if explicit:
        return explicit
    ratio = _project_output_ratio(project)
    return _IMAGE_SIZE_BY_RATIO.get(ratio)


def _project_image_negative(project: Project) -> str:
    tpl = project.template
    return merge_negative(
        tpl.negative_prompt if tpl else "",
        image_text=_is_image_text(project),
        photoreal=template_is_photoreal(tpl),
    )


def _locked_shot_prompt(project: Project, img_prompt: str) -> str:
    consist = template_consistency_mode(project.template)
    return build_locked_image_prompt(
        _effective_style(project),
        strip_lock_blocks(img_prompt),
        getattr(project, "character_bible", None) or "",
        photoreal=template_is_photoreal(project.template),
        lock_character=consist == "character",
        lock_style=True,
    )


_db_write_locks: dict[int, asyncio.Lock] = {}


def _db_write_lock() -> asyncio.Lock:
    """Per-event-loop lock (module-level Lock breaks across Celery asyncio.run)."""
    loop = asyncio.get_running_loop()
    key = id(loop)
    lock = _db_write_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _db_write_locks[key] = lock
    return lock


async def _parallel_image_and_audio(project_id: int) -> None:
    """逐镜出图（后镜参考上一镜静帧），同时整片连贯配音。"""
    await _set_status(project_id, ProjectStatus.IMAGING, 18, "PARALLEL_ASSETS")
    cfg = get_settings()
    ark = get_ark()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots), selectinload(Project.template))
        )
        project = result.scalar_one()
        tpl = project.template
        image_text = _is_image_text(project)
        shot_rows = sorted(project.shots, key=lambda s: s.shot_no)
        total = len(shot_rows)
        shot_meta = [
            {
                "id": s.id,
                "shot_no": s.shot_no,
                "img_prompt": s.img_prompt,
                "narration": s.narration,
                "duration": float(s.duration),
                "image_url": s.image_url,
                "image_ark_url": s.image_ark_url,
                "has_image": bool(s.image_url or s.image_ark_url),
                "has_audio": bool(
                    s.audio_url
                    and (p := storage.local_path_from_url(s.audio_url))
                    and p.exists()
                    and not is_near_silent_audio(p)
                ),
            }
            for s in shot_rows
        ]
        style_prefix = _effective_style(project)
        character_bible = getattr(project, "character_bible", None) or ""
        photoreal = template_is_photoreal(tpl)
        consist = template_consistency_mode(tpl)
        lock_character = consist == "character"
        image_size = _image_size_for(project)
        negative = _project_image_negative(project)
        voice = _project_voice(project)
        image_model = (getattr(project, "image_model", None) or "").strip()
        output_ratio = _project_output_ratio(project) or ""

    if not shot_meta:
        return

    # 同步发布参考图可能等待 OSS，必须释放数据库连接后执行。
    base_refs, style_refs = (
        await asyncio.to_thread(project_image_references, project)
        if any(not meta["has_image"] for meta in shot_meta) else ([], [])
    )

    img_sem = asyncio.Semaphore(max(1, cfg.pipeline_image_concurrency))
    done_img = 0
    progress_lock = asyncio.Lock()
    # 静图成片仍走外部 TTS；full + Seedance 内置口播则跳过
    native_audio = _kepu_seedance_native_audio(project)
    need_audio = (not native_audio) and (
        not _continuous_audio_ok(project_id)
    )

    async def bump_images() -> None:
        nonlocal done_img
        async with progress_lock:
            done_img += 1
            # 18 → ~55 while images; audio fills the rest when done
            img_w = 0.7 if image_text else 0.55
            frac = (done_img / max(total, 1)) * img_w
            pct = 18 + int(40 * frac)
            async with _db_write_lock():
                async with AsyncSessionLocal() as db:
                    project = await db.get(Project, project_id)
                    if project:
                        project.progress = pct
                        project.status = ProjectStatus.IMAGING
                        await db.commit()
            msg = f"出图 {done_img}/{total}" + (
                " · 整片配音生成中…" if need_audio else
                " · 声音将在视频阶段生成" if native_audio else " · 配音已就绪"
            )
            await publish_progress(
                project_id,
                {
                    "event": "progress",
                    "stage": "PARALLEL_ASSETS",
                    "percent": pct,
                    "message": msg,
                    "shot": None,
                    "total": total,
                },
            )

    async def persist_image(meta: dict, img) -> None:
        async with _db_write_lock():
            async with AsyncSessionLocal() as db:
                shot = await db.get(Shot, meta["id"])
                if not shot:
                    return
                shot.image_url = img.local_url
                shot.image_ark_url = img.remote_url
                if shot.status in {ShotStatus.PENDING, ShotStatus.AUDIO_READY}:
                    shot.status = (
                        ShotStatus.AUDIO_READY if shot.audio_url else ShotStatus.IMAGE_READY
                    )
                elif not shot.video_url:
                    shot.status = ShotStatus.IMAGE_READY
                from app.services.media_models.runtime import current_snapshot
                if (current_snapshot.get() or {}).get("mode") == "fixed_media":
                    from app.services.drama.billing_util import record_seedream_image_usage
                    await record_seedream_image_usage(db, user_id=project.user_id, model=image_model or get_settings().model_image,
                        domain="kepu", image_result=img, project_id=project_id, shot_id=shot.id)
                await db.commit()
        await bump_images()

    async def one_image(meta: dict, ref_urls: list[str]) -> SimpleNamespace | None:
        """生成一镜；返回静帧代理供下一镜参考。"""
        await _ensure_not_cancelled(project_id)
        if meta.get("has_image"):
            await bump_images()
            return None
        prompt = build_locked_image_prompt(
            style_prefix,
            strip_lock_blocks(meta["img_prompt"]),
            character_bible if lock_character else "",
            photoreal=photoreal,
            lock_character=lock_character,
            lock_style=True,
        )
        async with img_sem:
            await _ensure_not_cancelled(project_id)
            img = await ark.gen_image(
                prompt,
                negative,
                ref_urls,
                project_id=project_id,
                shot_no=meta["shot_no"],
                size=image_size,
                model=image_model,
                aspect_ratio=output_ratio or None,
                style_ref_urls=style_refs or None,
            )
        await persist_image(meta, img)
        from app.services.media_models.runtime import current_snapshot
        if (current_snapshot.get() or {}).get("mode") != "fixed_media":
            await _record_seedream_usage(project_id, image_result=img,
                model=image_model or get_settings().model_image, shot_id=meta["id"])
        return SimpleNamespace(image_ark_url=img.remote_url, image_url=img.local_url)

    async def run_images() -> None:
        """逐镜出图：后镜 Seedream 参考上一镜静帧。"""
        prev_proxy = None
        for meta in shot_meta:
            if meta.get("has_image"):
                prev_proxy = SimpleNamespace(
                    image_ark_url=meta.get("image_ark_url"),
                    image_url=meta.get("image_url"),
                )
                await bump_images()
                continue
            refs = await asyncio.to_thread(image_refs_for_shot, prev_proxy, base_refs)
            proxy = await one_image(meta, refs)
            if proxy:
                prev_proxy = proxy

    async def run_continuous_audio() -> None:
        await _ensure_not_cancelled(project_id)
        if not need_audio:
            return
        await publish_progress(
            project_id,
            {
                "event": "progress",
                "stage": "PARALLEL_ASSETS",
                "percent": 30,
                "message": "整片连贯配音中…",
            },
        )
        await _synthesize_continuous_audio(
            project_id,
            voice=voice,
            shot_rows=shot_rows,
            force=False,
        )
        async with _db_write_lock():
            async with AsyncSessionLocal() as db:
                project = await db.get(Project, project_id)
                if project:
                    project.progress = max(project.progress or 0, 45)
                    await db.commit()
        await publish_progress(
            project_id,
            {
                "event": "progress",
                "stage": "PARALLEL_ASSETS",
                "percent": 48,
                "message": "整片配音完成",
            },
        )

    results = await asyncio.gather(
        run_images(),
        run_continuous_audio(),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        # Prefer cancel over generic failure
        for err in errors:
            if isinstance(err, (PipelineCancelled, asyncio.CancelledError)):
                raise err
        raise RuntimeError(str(errors[0]))

    async with _db_write_lock():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Project)
                .where(Project.id == project_id)
                .options(selectinload(Project.shots))
            )
            project = result.scalar_one()
            if project.shots:
                project.cover_url = sorted(project.shots, key=lambda s: s.shot_no)[0].image_url
            project.status = ProjectStatus.IMAGE_READY
            project.progress = 70 if image_text else 50
            await db.commit()
    await publish_progress(
        project_id,
        {
            "event": "progress",
            "stage": "ASSETS_READY",
            "percent": 70 if image_text else 50,
            "message": (
                "分镜图已完成，下一步生成视频与声音" if native_audio else "分镜图与整片配音已完成"
            ),
        },
    )


async def _parallel_videos(project_id: int) -> None:
    """按镜序逐个出视频；后镜参考上一镜尾帧。"""
    from app.services.kepu_stages import VIDEO_SKIP_REASON_PRIVACY

    await _set_status(project_id, ProjectStatus.VIDEOING, 55, "VIDEOING")
    cfg = get_settings()
    ark = get_ark()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots), selectinload(Project.template))
        )
        project = result.scalar_one()
        project_user_id = int(project.user_id)
        tpl = project.template
        # 科普 full：默认 Seedance 内置口播；回退模式才 ambient_only + 后期 TTS
        generate_audio = _kepu_seedance_generate_audio(project)
        ambient_only = _kepu_seedance_sfx_audio(project)
        no_bgm = _kepu_seedance_native_audio(project)
        consistency = template_consistency_mode(tpl) == "character" and bool(
            tpl.seedance_config.get("character_consistency", True)
        )
        motion = str(tpl.seedance_config.get("motion_bias", ""))
        from app.services.seedance_resolutions import project_video_resolution
        resolution = project_video_resolution(project, cfg)
        ratio = _project_output_ratio(project) or cfg.ark_video_ratio
        shot_meta = [
            {
                "id": s.id,
                "shot_no": s.shot_no,
                "duration": float(s.duration),
                "video_prompt": s.video_prompt,
                "segment_script": getattr(s, "segment_script", "") or s.video_prompt or "",
                "camera": s.camera,
                "image_ref": video_image_ref(s),
                "image_ark_url": s.image_ark_url,
                "image_url": s.image_url,
                "last_frame_url": getattr(s, "last_frame_url", None),
                "video_url": s.video_url,
                "has_video": bool(s.video_url),
                "video_skip_reason": getattr(s, "video_skip_reason", None),
            }
            for s in sorted(project.shots, key=lambda s: s.shot_no)
        ]
        style_prefix = _effective_style(project)
        total = len(shot_meta)
        video_model = (getattr(project, "video_model", None) or "").strip()

    if not shot_meta:
        return

    done = 0

    async def one_video(meta: dict, extra_refs: list[str]) -> SimpleNamespace:
        nonlocal done
        await _ensure_not_cancelled(project_id)
        proxy = SimpleNamespace(
            image_ark_url=meta.get("image_ark_url"),
            image_url=meta.get("image_url"),
            last_frame_url=meta.get("last_frame_url"),
        )
        if meta.get("has_video") or meta.get("video_skip_reason") == VIDEO_SKIP_REASON_PRIVACY:
            done += 1
            pct = 55 + int(30 * done / max(total, 1))
            if meta.get("video_skip_reason") == VIDEO_SKIP_REASON_PRIVACY:
                # 上一轮已确认真人隐私拦截：不再重提上游，直接沿用静图
                await publish_progress(
                    project_id,
                    {
                        "event": "progress",
                        "stage": "VIDEOING",
                        "shot": meta["shot_no"],
                        "total": total,
                        "percent": pct,
                        "message": f"镜头 {meta['shot_no']} 含真人已跳过 AI 视频，将用静图合成",
                    },
                )
                return proxy
            if not proxy.last_frame_url and meta.get("video_url"):
                last = persist_last_frame_from_video(
                    project_id, int(meta["shot_no"]), str(meta["video_url"])
                )
                if last:
                    proxy.last_frame_url = last
                    async with _db_write_lock():
                        async with AsyncSessionLocal() as db:
                            shot = await db.get(Shot, meta["id"])
                            if shot:
                                shot.last_frame_url = last
                                await db.commit()
            await publish_progress(
                project_id,
                {
                    "event": "progress",
                    "stage": "VIDEOING",
                    "shot": meta["shot_no"],
                    "percent": pct,
                    "message": f"沿用已有视频 {done}/{total}",
                },
            )
            return proxy
        await _ensure_not_cancelled(project_id)
        script = (meta.get("segment_script") or meta.get("video_prompt") or "").strip()
        prompt = _kepu_video_prompt(
            script,
            style_prefix=style_prefix,
            motion_bias=motion,
            camera=str(meta.get("camera") or ""),
            ambient_only=ambient_only,
            no_bgm=no_bgm,
        )
        dur = segplan.resolve_api_duration(
            script,
            fallback=meta["duration"],
            lo=cfg.seedance_duration_min,
            hi=cfg.seedance_duration_max,
        )
        try:
            local_video, task_result = await ark.gen_and_wait_video(
                meta["image_ref"],
                prompt,
                int(dur),
                project_id=project_id,
                shot_no=meta["shot_no"],
                character_consistency=consistency,
                resolution=resolution,
                ratio=ratio,
                generate_audio=generate_audio,
                model=video_model,
                extra_image_urls=extra_refs or None,
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            # Real-person privacy blocks — skip AI video; compose will use still image
            if any(
                k in msg
                for k in (
                    "PrivacyInformation",
                    "InputImageSensitive",
                    "SensitiveContentDetected",
                )
            ):
                logger.warning(
                    "Seedance privacy skip project=%s shot=%s: %s",
                    project_id,
                    meta["shot_no"],
                    msg[:240],
                )
                # 持久跳过标记：后续轮次不再重提上游（否则每轮都被拦截、白等配额）
                async with _db_write_lock():
                    async with AsyncSessionLocal() as db:
                        skipped_shot = await db.get(Shot, meta["id"])
                        if skipped_shot:
                            skipped_shot.video_skip_reason = VIDEO_SKIP_REASON_PRIVACY
                            await db.commit()
                done += 1
                pct = 55 + int(30 * done / max(total, 1))
                await publish_progress(
                    project_id,
                    {
                        "event": "progress",
                        "stage": "VIDEOING",
                        "shot": meta["shot_no"],
                        "total": total,
                        "percent": pct,
                        "message": (
                            f"镜头 {meta['shot_no']} 含真人已跳过 AI 视频"
                            + ("（成片将缺该镜）" if generate_audio else "，将用静图合成")
                        ),
                    },
                )
                return proxy
            raise
        last = persist_last_frame_from_video(
            project_id,
            int(meta["shot_no"]),
            local_video,
            preferred_url=getattr(task_result, "last_frame_url", None),
        )
        proxy.last_frame_url = last
        s = get_settings()
        dur = max(float(dur), 2.0)
        billing_key = "seedance2:video0" if generate_audio else "seedance2:video1"
        async with _db_write_lock():
            async with AsyncSessionLocal() as db:
                shot = await db.get(Shot, meta["id"])
                if not shot:
                    return proxy
                shot.video_url = local_video
                shot.last_frame_url = last
                shot.status = ShotStatus.VIDEO_READY
                from app.services.media_models.runtime import current_snapshot
                if (current_snapshot.get() or {}).get("mode") == "fixed_media":
                    from app.services.drama.billing_util import record_seedance_video_usage
                    await record_seedance_video_usage(db, user_id=project_user_id, billing_key=billing_key,
                        model=video_model or get_settings().model_video, domain="kepu", task_result=task_result,
                        fallback_duration_sec=dur, resolution=resolution, provider_task_id=task_result.provider_task_id,
                        project_id=project_id, shot_id=shot.id)
                await db.commit()
        from app.services.media_models.runtime import current_snapshot
        if (current_snapshot.get() or {}).get("mode") != "fixed_media":
            await _record_seedance_usage(
                project_id,
                billing_key=billing_key,
                model=s.model_video,
                task_result=task_result,
                fallback_duration_sec=dur,
                shot_id=meta["id"],
            )
        done += 1
        pct = 55 + int(30 * done / max(total, 1))
        async with _db_write_lock():
            async with AsyncSessionLocal() as db:
                project = await db.get(Project, project_id)
                if project:
                    project.progress = pct
                    project.status = ProjectStatus.VIDEOING
                    await db.commit()
        await publish_progress(
            project_id,
            {
                "event": "progress",
                "stage": "VIDEOING",
                "shot": meta["shot_no"],
                "total": total,
                "percent": pct,
                "message": (
                    f"逐镜 AI 视频 {done}/{total}（参考上一镜）"
                    if extra_refs
                    else (
                        f"AI 视频（含操作音效）{done}/{total}"
                        if generate_audio
                        else f"AI 视频 {done}/{total}"
                    )
                ),
            },
        )
        return proxy

    prev_proxy: SimpleNamespace | None = None
    for meta in shot_meta:
        extra = video_extra_refs_for_shot(prev_proxy)
        prev_proxy = await one_video(meta, extra)

    async with _db_write_lock():
        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project:
                project.status = ProjectStatus.VIDEO_READY
                project.progress = 88
                await db.commit()
    await publish_progress(
        project_id,
        {"event": "progress", "stage": "VIDEO_READY", "percent": 88, "message": "全部镜头视频完成"},
    )


async def _compose_stage(project_id: int) -> None:
    await _set_status(project_id, ProjectStatus.COMPOSING, 92, "COMPOSING")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots), selectinload(Project.template))
        )
        project = result.scalar_one()
        out = storage.project_dir(project_id) / "final.mp4"

        media: list[ShotMedia] = []
        for shot in sorted(project.shots, key=lambda s: s.shot_no):
            pdir = storage.project_dir(project_id)
            # Resolve/download to local for FFmpeg; keep OSS URLs in DB for frontend preview
            video_path = storage.local_path_from_url(shot.video_url or "")
            audio_path = storage.local_path_from_url(shot.audio_url or "")
            image_path = storage.local_path_from_url(shot.image_url or "")
            if shot.video_url and (not video_path or not video_path.exists()):
                if shot.video_url.startswith("http"):
                    video_path = await storage.ensure_local_media(
                        shot.video_url, pdir / f"shot_{shot.shot_no:03d}.mp4"
                    )
            if shot.audio_url and (not audio_path or not audio_path.exists()):
                if shot.audio_url.startswith("http"):
                    audio_path = await storage.ensure_local_media(
                        shot.audio_url, pdir / f"shot_{shot.shot_no:03d}_tts.mp3"
                    )
            if shot.image_url and (not image_path or not image_path.exists()):
                if shot.image_url.startswith("http"):
                    image_path = await storage.ensure_local_media(
                        shot.image_url, pdir / f"shot_{shot.shot_no:03d}.png"
                    )
            media.append(
                ShotMedia(
                    shot_no=shot.shot_no,
                    duration=float(shot.duration),
                    narration=shot.narration,
                    overlay_title=getattr(shot, "overlay_title", "") or "",
                    overlay_subtitle=getattr(shot, "overlay_subtitle", "") or "",
                    video_path=video_path if video_path and video_path.exists() else None,
                    audio_path=audio_path if audio_path and audio_path.exists() else None,
                    image_path=image_path if image_path and image_path.exists() else None,
                )
            )

        ratio = _project_output_ratio(project)
        mode = project.pipeline_mode or "full"

        # full 模式：成片节奏跟镜头视频真实时长，勿被整片旁白重分配后的短 duration 裁掉画面
        if mode == "full":
            for item in media:
                if not item.video_path:
                    continue
                probed = await asyncio.to_thread(probe_duration, item.video_path)
                if probed and probed > 0.5:
                    item.duration = float(probed)

        native_audio = _kepu_seedance_native_audio(project)
        # 视频内置口播：不叠外部 full_narration；回退/静图仍可用整片 TTS
        full_audio = None
        if not native_audio:
            full_audio = _full_narration_path(project_id)
            if not full_audio.exists():
                full_audio = None

        if mode == "image_text":
            if not media or any(item.image_path is None for item in media):
                raise RuntimeError("分镜图片尚未齐备，请重试素材生成")
            if full_audio is not None:
                if not _continuous_audio_ok(project_id):
                    raise RuntimeError("整片配音不可用，请重新生成配音")
            elif any(
                item.audio_path is None or is_near_silent_audio(item.audio_path)
                for item in media
            ):
                raise RuntimeError("配音尚未齐备，请重新生成配音")

        sub_cfg = _merge_subtitle_preset(
            (project.template.subtitle_config if project.template else None) or {},
            getattr(project, "subtitle_preset", "") or "",
        )
        layout = str(sub_cfg.get("position") or "top")
        if layout not in {"top", "split", "bottom", "center"}:
            layout = "top"
        # bottom/center still use top dual-line unless explicitly split
        subtitle_layout = "split" if layout == "split" else "top"

        def _f(key: str, default: float) -> float:
            try:
                return float(sub_cfg.get(key, default))
            except (TypeError, ValueError):
                return default

        bgm_mood = (getattr(project, "bgm_lock", None) or "").strip()
        if not bgm_mood and project.shots:
            bgm_mood = (project.shots[0].bgm_mood or "").strip()
        if not bgm_mood and project.template and isinstance(project.template.audio_config, dict):
            bgm_mood = str(project.template.audio_config.get("bgm_mood") or "").strip()
        bgm_path = resolve_bgm_path(bgm_mood)
        keep_video_sfx = native_audio or _kepu_seedance_sfx_audio(project)

        await _run_ffmpeg_compose_with_retry(
            project_id,
            lambda: compose_project(
                media,
                out,
                ComposeOptions(
                    ratio=ratio,
                    mode=mode,
                    resolution_mode=project.resolution_mode or "preview",
                    full_audio_path=full_audio,
                    subtitle_layout=subtitle_layout,
                    title_scale=_f("title_scale", 1.35),
                    sub_scale=_f("sub_scale", 1.3),
                    caption_scale=_f("caption_scale", 1.25),
                    bgm_path=bgm_path,
                    bgm_volume=0.22,
                    keep_video_sfx=keep_video_sfx,
                    prefer_video_audio=native_audio,
                    sfx_volume=0.22,
                ),
            ),
        )
        project.final_video_url = storage.publish_local(out)
        if project.status != ProjectStatus.CANCELLED:
            project.status = ProjectStatus.AUDITING
            project.progress = 96
        await db.commit()

    async with AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        if project and project.status != ProjectStatus.CANCELLED:
            project.status = ProjectStatus.DONE
            project.progress = 100
            await db.commit()
# 遇到 SIGTERM 自动重试，避免部署重启等打断直接落失败
async def _run_ffmpeg_compose_with_retry(project_id: int, work) -> None:
    last_exc: BaseException | None = None
    for attempt in range(1, _COMPOSE_SIGTERM_MAX_ATTEMPTS + 1):
        try:
            await asyncio.to_thread(work)
            return
        except FfmpegInterrupted as exc:
            last_exc = exc
            if attempt >= _COMPOSE_SIGTERM_MAX_ATTEMPTS:
                break
            logger.warning(
                "compose interrupted by SIGTERM, retry %s/%s project=%s",
                attempt,
                _COMPOSE_SIGTERM_MAX_ATTEMPTS,
                project_id,
            )
            await publish_progress(
                project_id,
                {
                    "event": "progress",
                    "stage": "COMPOSING",
                    "percent": 93,
                    "message": f"合成被中断，正在自动重试（{attempt}/{_COMPOSE_SIGTERM_MAX_ATTEMPTS}）…",
                },
            )
            await asyncio.sleep(float(attempt) * 2.0)
        except Exception as exc:  # noqa: BLE001
            # 历史错误文案里也可能带 signal 15
            if is_ffmpeg_interrupted_error(exc) and attempt < _COMPOSE_SIGTERM_MAX_ATTEMPTS:
                last_exc = exc
                logger.warning(
                    "compose looks SIGTERM-interrupted, retry %s/%s project=%s",
                    attempt,
                    _COMPOSE_SIGTERM_MAX_ATTEMPTS,
                    project_id,
                )
                await publish_progress(
                    project_id,
                    {
                        "event": "progress",
                        "stage": "COMPOSING",
                        "percent": 93,
                        "message": f"合成被中断，正在自动重试（{attempt}/{_COMPOSE_SIGTERM_MAX_ATTEMPTS}）…",
                    },
                )
                await asyncio.sleep(float(attempt) * 2.0)
                continue
            raise
    raise last_exc or RuntimeError("FFmpeg 合成失败")


@storage.without_intermediate_oss
async def regen_shot_image(project_id: int, shot_id: int) -> None:
    """重绘单镜首帧图，并清掉该镜视频以便后续重生。"""
    ark = get_ark()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.template), selectinload(Project.shots))
        )
        project = result.scalar_one()
        shot = next((s for s in project.shots if s.id == shot_id), None)
        if not shot:
            raise ValueError("shot not found")
        # 先读齐元数据；参考图发布与模型请求都在数据库连接释放后进行。
        shot_no = shot.shot_no
        shot_rows = list(project.shots)
        negative = _project_image_negative(project)
        prompt = _locked_shot_prompt(project, shot.img_prompt)
        image_size = _image_size_for(project)
        image_model = (getattr(project, "image_model", None) or "").strip()
        aspect_ratio = _project_output_ratio(project) or None
    base_refs, style_refs = await asyncio.to_thread(project_image_references, project)
    ref_urls = await asyncio.to_thread(
        lambda: image_refs_for_shot(previous_usable_shot(shot_rows, shot_no), base_refs)
    )
    img = await ark.gen_image(
        prompt,
        negative,
        ref_urls,
        project_id=project_id,
        shot_no=shot_no,
        size=image_size,
        model=image_model,
        aspect_ratio=aspect_ratio,
        style_ref_urls=style_refs or None,
    )
    cancelled = False
    async with AsyncSessionLocal() as db:
        shot = await db.get(Shot, shot_id)
        project = await db.get(Project, project_id)
        if not shot or not project:
            raise ValueError("shot not found")
        cancelled = project.status == ProjectStatus.CANCELLED
        if not cancelled:
            shot.image_url = img.local_url
            shot.image_ark_url = img.remote_url
            shot.video_url = None
            shot.last_frame_url = None
            shot.video_skip_reason = None  # 换了首帧图，真人隐私可能已消失
            shot.status = ShotStatus.IMAGE_READY
            shot.version += 1
            project.status = ProjectStatus.IMAGE_READY
            project.final_video_url = None
            await db.commit()
    s = get_settings()
    # 上游成本已真实发生：即使项目刚被取消也要记账，随后抛出让任务收敛取消态
    await _record_seedream_usage(
        project_id,
        image_result=img,
        model=image_model or s.model_image,
        shot_id=shot_id,
        delivered=not cancelled,
    )
    if cancelled:
        raise PipelineCancelled(f"project {project_id} cancelled during regen image")


@storage.without_intermediate_oss
async def regen_shot_video(project_id: int, shot_id: int) -> None:
    """重绘单镜视频；后镜参考上一镜尾帧。"""
    ark = get_ark()
    cfg = get_settings()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.template), selectinload(Project.shots))
        )
        project = result.scalar_one()
        if _is_image_text(project):
            raise ValueError("图文模式无需生成 AI 视频，请直接重新合成成片")
        shot = next((s for s in project.shots if s.id == shot_id), None)
        if not shot or not (shot.image_url or shot.image_ark_url):
            raise ValueError("shot image required")
        generate_audio = _kepu_seedance_generate_audio(project)
        ambient_only = _kepu_seedance_sfx_audio(project)
        no_bgm = _kepu_seedance_native_audio(project)
        motion = str(project.template.seedance_config.get("motion_bias", ""))
        consistency = template_consistency_mode(project.template) == "character" and bool(
            project.template.seedance_config.get("character_consistency", True)
        )
        from app.services.seedance_resolutions import project_video_resolution
        resolution = project_video_resolution(project, cfg)
        script = (getattr(shot, "segment_script", "") or shot.video_prompt or "").strip()
        prompt = _kepu_video_prompt(
            script,
            style_prefix=_effective_style(project),
            motion_bias=motion,
            camera=shot.camera or "",
            ambient_only=ambient_only,
            no_bgm=no_bgm,
        )
        dur = segplan.resolve_api_duration(
            script,
            fallback=shot.duration,
            lo=cfg.seedance_duration_min,
            hi=cfg.seedance_duration_max,
        )
        shot_no = shot.shot_no
        image_ref = video_image_ref(shot)
        extra_refs = video_extra_refs_for_shot(previous_usable_shot(list(project.shots), shot_no))
        video_model = (getattr(project, "video_model", None) or "").strip()
        ratio = _project_output_ratio(project) or cfg.ark_video_ratio
    local_video, task_result = await ark.gen_and_wait_video(
        image_ref,
        prompt,
        int(dur),
        project_id=project_id,
        shot_no=shot_no,
        character_consistency=consistency,
        resolution=resolution,
        ratio=ratio,
        generate_audio=generate_audio,
        model=video_model,
        extra_image_urls=extra_refs or None,
    )
    last = persist_last_frame_from_video(
        project_id,
        int(shot_no),
        local_video,
        preferred_url=getattr(task_result, "last_frame_url", None),
    )
    cancelled = False
    async with AsyncSessionLocal() as db:
        shot = await db.get(Shot, shot_id)
        project = await db.get(Project, project_id)
        if not shot or not project:
            raise ValueError("shot not found")
        cancelled = project.status == ProjectStatus.CANCELLED
        if not cancelled:
            shot.video_url = local_video
            shot.last_frame_url = last
            shot.video_skip_reason = None  # 视频成功生成，清除跳过标记
            shot.status = ShotStatus.VIDEO_READY
            shot.version += 1
            project.final_video_url = None
            project.status = ProjectStatus.VIDEO_READY
            await db.commit()
    billing_key = "seedance2:video0" if generate_audio else "seedance2:video1"
    # 上游成本已真实发生：即使项目刚被取消也要记账，随后抛出让任务收敛取消态
    await _record_seedance_usage(
        project_id,
        billing_key=billing_key,
        model=cfg.model_video,
        task_result=task_result,
        fallback_duration_sec=max(float(dur), 2.0),
        shot_id=shot_id,
        delivered=not cancelled,
    )
    if cancelled:
        raise PipelineCancelled(f"project {project_id} cancelled during regen video")


@storage.without_intermediate_oss
async def regen_shot_audio(project_id: int, shot_id: int) -> None:
    """Re-TTS uses continuous full-film narration (editing one shot re-voices the whole track)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.template), selectinload(Project.shots))
        )
        project = result.scalar_one()
        if _kepu_seedance_native_audio(project):
            raise ValueError("当前为视频内置配音，请重绘该镜视频以更新口播")
        shot = next((s for s in project.shots if s.id == shot_id), None)
        if not shot:
            raise ValueError("shot not found")
        if not (shot.narration or "").strip() and not any(
            (s.narration or "").strip() for s in project.shots
        ):
            raise ValueError("旁白为空，无法配音")
        voice = _project_voice(project)
        shots = sorted(project.shots, key=lambda s: s.shot_no)
    await _synthesize_continuous_audio(
        project_id, voice=voice, shot_rows=shots, force=True
    )
    cancelled = False
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots))
        )
        project = result.scalar_one_or_none()
        shot = await db.get(Shot, shot_id)
        if project and project.status == ProjectStatus.CANCELLED:
            cancelled = True
        elif shot:
            shot.version += 1
        if project and not cancelled:
            project.final_video_url = None
            shots = list(project.shots or [])
            if _is_image_text(project):
                project.status = ProjectStatus.IMAGE_READY
            elif shots and all(s.video_url for s in shots):
                project.status = ProjectStatus.VIDEO_READY
            else:
                project.status = ProjectStatus.IMAGE_READY
            await db.commit()
    if cancelled:
        raise PipelineCancelled(f"project {project_id} cancelled during regen audio")


@storage.without_intermediate_oss
async def regen_project_audio_and_compose(project_id: int) -> None:
    """Force continuous re-TTS with current voice, then compose."""
    await _set_status(project_id, ProjectStatus.AUDIOING, 80, "AUDIOING")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.template), selectinload(Project.shots))
        )
        project = result.scalar_one()
        native_audio = _kepu_seedance_native_audio(project)
        voice = _project_voice(project)
        shots = sorted(project.shots, key=lambda s: s.shot_no)
        project.final_video_url = None
        await db.commit()

    if native_audio:
        await publish_progress(
            project_id,
            {
                "event": "progress",
                "stage": "AUDIOING",
                "percent": 90,
                "message": "使用视频内置配音，开始合成",
            },
        )
    else:
        await publish_progress(
            project_id,
            {
                "event": "progress",
                "stage": "AUDIOING",
                "percent": 82,
                "message": "整片连贯配音中…",
            },
        )
        await _synthesize_continuous_audio(
            project_id, voice=voice, shot_rows=shots, force=True
        )
        await publish_progress(
            project_id,
            {
                "event": "progress",
                "stage": "AUDIOING",
                "percent": 90,
                "message": "整片配音完成，开始合成",
            },
        )

    try:
        await _compose_stage(project_id)
        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project and project.status != ProjectStatus.CANCELLED:
                project.status = ProjectStatus.DONE
                project.progress = 100
                project.error_msg = None
                await db.commit()
        await publish_progress(
            project_id,
            {"event": "done", "percent": 100, "video_url": await _final_url(project_id)},
        )
    except (PipelineCancelled, asyncio.CancelledError):
        raise
    except Exception as exc:  # noqa: BLE001
        await _fail_project_compose(project_id, exc)
        raise


# 拼接失败时把项目落成 FAILED，避免长期卡在 COMPOSING 无法点「重新拼接」
async def _fail_project_compose(project_id: int, exc: Exception) -> None:
    raw = str(exc)
    if is_ffmpeg_interrupted_error(exc):
        msg = "FFmpeg 被系统中断（signal 15），请点击重新拼接"
    else:
        msg = raw[:2000]
    logger.error("compose failed project=%s: %s", project_id, msg[:500])
    async with AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        if project and project.status != ProjectStatus.DONE:
            project.status = ProjectStatus.FAILED
            project.error_msg = msg
            await db.commit()
    await publish_progress(
        project_id,
        {
            "event": "failed",
            "stage": "COMPOSING",
            "message": msg,
            "retryable": True,
            "code": "COMPOSE_ERROR",
        },
    )


@storage.without_intermediate_oss
async def compose_only(project_id: int) -> None:
    try:
        await _compose_stage(project_id)
        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project and project.status != ProjectStatus.CANCELLED:
                project.status = ProjectStatus.DONE
                project.progress = 100
                project.error_msg = None
                await db.commit()
        await publish_progress(
            project_id,
            {"event": "done", "percent": 100, "video_url": await _final_url(project_id)},
        )
    except (PipelineCancelled, asyncio.CancelledError):
        raise
    except Exception as exc:  # noqa: BLE001
        await _fail_project_compose(project_id, exc)
        raise
