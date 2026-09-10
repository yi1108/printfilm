"""Pipeline orchestration — in-process runtime used by the task platform."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

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
    concat_native_videos,
    is_ffmpeg_interrupted_error,
    is_near_silent_audio,
    probe_duration,
)
from app.services.progress import publish_progress
from app.services import storage
from app.services.style_lock import (
    build_locked_image_prompt,
    merge_negative,
    seedream_ref_urls,
    strip_lock_blocks,
    template_consistency_mode,
    template_is_photoreal,
)
from app.services.voices import resolve_speaker
from app.services import seedance_segments as segplan
from app.services.bgm import resolve_bgm_path

logger = logging.getLogger(__name__)

# 成片 FFmpeg 被 SIGTERM 打断时的自动重试次数
_COMPOSE_SIGTERM_MAX_ATTEMPTS = 3

_running: dict[int, asyncio.Task] = {}
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
) -> None:
    try:
        from app.services.drama.billing_util import record_seedance_video_usage

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if not project:
                return
            await record_seedance_video_usage(
                db,
                user_id=project.user_id,
                billing_key=billing_key,
                model=model,
                domain="kepu",
                task_result=task_result,
                fallback_duration_sec=fallback_duration_sec,
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


def start_pipeline(project_id: int) -> str:
    """Start one in-process pipeline task."""
    _cancelled.discard(project_id)
    if project_id in _running and not _running[project_id].done():
        return "in-process"
    _running[project_id] = asyncio.create_task(run_pipeline(project_id))
    return "in-process"


def cancel_pipeline(project_id: int) -> bool:
    """Request cancel for one in-process pipeline task."""
    _cancelled.add(project_id)
    stopped = False

    task = _running.get(project_id)
    if task and not task.done():
        task.cancel()
        stopped = True

    return stopped


def is_cancelled(project_id: int) -> bool:
    return project_id in _cancelled


# 单镜重生 / 合成等短任务的进程内异步执行。
_regen_tasks: dict[str, asyncio.Task] = {}


def _dispatch_side_task(
    key: str,
    *,
    coro_factory,
) -> str:
    """Start one in-process side task."""
    existing = _regen_tasks.get(key)
    if existing and not existing.done():
        return "in-process"

    async def _runner() -> None:
        try:
            await coro_factory()
        except Exception:  # noqa: BLE001
            logger.exception("in-process side task failed key=%s", key)

    _regen_tasks[key] = asyncio.create_task(_runner())
    return "in-process"


def dispatch_regen_image(project_id: int, shot_id: int) -> str:
    """异步重绘单镜首帧图。"""
    key = f"regen-image:{project_id}:{shot_id}"

    async def _coro() -> None:
        await regen_shot_image(project_id, shot_id)

    return _dispatch_side_task(
        key,
        coro_factory=_coro,
    )


def dispatch_regen_video(project_id: int, shot_id: int) -> str:
    """异步重生单镜 Seedance 视频。"""
    key = f"regen-video:{project_id}:{shot_id}"

    async def _coro() -> None:
        await regen_shot_video(project_id, shot_id)

    return _dispatch_side_task(
        key,
        coro_factory=_coro,
    )


def dispatch_regen_audio(project_id: int, shot_id: int) -> str:
    """异步重配单镜旁白（整片连贯 TTS）。"""
    key = f"regen-audio:{project_id}:{shot_id}"

    async def _coro() -> None:
        await regen_shot_audio(project_id, shot_id)

    return _dispatch_side_task(
        key,
        coro_factory=_coro,
    )


def dispatch_regen_project_audio_and_compose(project_id: int) -> str:
    """异步整片重配音并合成成片。"""
    key = f"regen-all-audio:{project_id}"

    async def _coro() -> None:
        await regen_project_audio_and_compose(project_id)

    return _dispatch_side_task(
        key,
        coro_factory=_coro,
    )


def dispatch_compose_only(project_id: int) -> str:
    """异步仅合成成片（不重跑 AI 阶段）。"""
    key = f"compose:{project_id}"

    async def _coro() -> None:
        await compose_only(project_id)

    return _dispatch_side_task(
        key,
        coro_factory=_coro,
    )


def _is_image_text(project: Project) -> bool:
    return (project.pipeline_mode or "full") == "image_text"


def _use_native_video_audio(project: Project | None = None) -> bool:
    """是否跳过 TTS、直拼 Seedance 口播。科普已改回外部合成，恒为 False。"""
    return False


def _kepu_seedance_sfx_audio(project: Project | None = None) -> bool:
    """科普 full：向 Seedance 要操作/环境音效（不含口播与 BGM）。"""
    if project is not None and _is_image_text(project):
        return False
    return bool(get_settings().kepu_seedance_sfx_audio)


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
    if force or not _continuous_audio_ok(project_id):
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
        native_audio = _use_native_video_audio(project)
        shots = list(project.shots)
        has_images = all(shot_image_ready(s) for s in shots)
        # 与计费 resolve_kepu_billing_phase 共用旁白就绪规则
        has_audio = True if native_audio else project_audio_ready(project)
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
    except (PipelineCancelled, asyncio.CancelledError):
        logger.info("pipeline cancelled project=%s", project_id)
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
            return
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
        _running.pop(project_id, None)


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
            # 用户角色限制在 diverse/style 下也必须进分镜，否则出镜人物会被模板默认成「过肩无脸」
            character_hint=char_hint,
            extra_requirements=extra,
            consistency_mode=consist,
            output_ratio=_project_output_ratio(project),
        )
        plans = plans_result.shots
        if consist == "character":
            project.character_bible = _effective_character_bible(project, plans_result.character_bible)
        elif char_hint:
            # 多样人物：保留用户角色限制，不锁成同一张脸
            project.character_bible = char_hint
        else:
            project.character_bible = "无固定人物，各镜独立场景"
        tpl_bgm = ""
        if tpl and isinstance(tpl.audio_config, dict):
            tpl_bgm = str(tpl.audio_config.get("bgm_mood") or "").strip()
        project.bgm_lock = (
            (plans_result.bgm_lock or "").strip()
            or tpl_bgm
            or (plans[0].bgm if plans else "")
            or "轻快专业"
        )
        for shot in list(project.shots):
            await db.delete(shot)
        await db.flush()
        bible = project.character_bible
        for plan in plans:
            dur = clamp_shot_duration(
                plan.duration,
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
            segment_script = (plan.segment_script or plan.video_prompt or "").strip()
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
                    bgm_mood=project.bgm_lock or plan.bgm,
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
    user = (getattr(project, "character_prompt", None) or "").strip()
    return user or _template_seedream_field(project, "character_prompt")


def _effective_extra(project: Project) -> str:
    user = (getattr(project, "extra_prompt", None) or "").strip()
    return user or _template_seedream_field(project, "extra_prompt")


def _effective_character_bible(project: Project, llm_bible: str = "") -> str:
    user = _effective_character_prompt(project)
    return user or (llm_bible or "").strip()


def _image_size_for(project: Project) -> str | None:
    ratio = _project_output_ratio(project)
    return _IMAGE_SIZE_BY_RATIO.get(ratio)


def _project_image_negative(project: Project) -> str:
    tpl = project.template
    return merge_negative(
        tpl.negative_prompt if tpl else "",
        image_text=_is_image_text(project),
        photoreal=template_is_photoreal(tpl),
    )


def _project_base_refs(project: Project) -> list[str]:
    tpl = project.template
    refs = list((tpl.seedream_config or {}).get("ref_images") or []) if tpl else []
    if project.ref_image_url:
        refs = [project.ref_image_url, *refs]
    return seedream_ref_urls(*refs)


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


def _consistency_ref_from_shots(shots: list) -> str | None:
    """Prefer first finished shot's Ark CDN URL, else local static."""
    ordered = sorted(shots, key=lambda s: s.shot_no)
    for s in ordered:
        if s.image_ark_url and str(s.image_ark_url).startswith("http"):
            return s.image_ark_url
    for s in ordered:
        if s.image_url:
            return s.image_url
    return None


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
    """Generate storyboard images and continuous TTS (full 再并行图生视频)。"""
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
        native_audio = _use_native_video_audio(project)
        shot_rows = sorted(project.shots, key=lambda s: s.shot_no)
        total = len(shot_rows)
        shot_meta = [
            {
                "id": s.id,
                "shot_no": s.shot_no,
                "img_prompt": s.img_prompt,
                "narration": s.narration,
                "duration": float(s.duration),
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
        base_refs = _project_base_refs(project)
        # Only character mode chains shot-to-shot refs; diverse/style keep scenes independent
        existing_anchor = _consistency_ref_from_shots(shot_rows) if lock_character else None
        image_size = _image_size_for(project)
        negative = _project_image_negative(project)
        voice = _project_voice(project)

    if not shot_meta:
        return

    img_sem = asyncio.Semaphore(max(1, cfg.pipeline_image_concurrency))
    done_img = 0
    progress_lock = asyncio.Lock()
    # 静图成片与完整模式都合成连贯旁白；已有音轨则跳过
    need_audio = (not native_audio) and (not _continuous_audio_ok(project_id))

    async def bump_images() -> None:
        nonlocal done_img
        async with progress_lock:
            done_img += 1
            # 18 → ~55 while images; audio fills the rest when done
            img_w = 0.7 if image_text else (0.85 if native_audio else 0.55)
            frac = (done_img / max(total, 1)) * img_w
            pct = 18 + int(40 * frac)
            async with _db_write_lock():
                async with AsyncSessionLocal() as db:
                    project = await db.get(Project, project_id)
                    if project:
                        project.progress = pct
                        project.status = ProjectStatus.IMAGING
                        await db.commit()
            if native_audio:
                msg = f"出图 {done_img}/{total}（配音交由视频模型）"
            else:
                msg = f"出图 {done_img}/{total}" + (
                    " · 整片配音生成中…" if need_audio else " · 配音已就绪"
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
                await db.commit()
        await bump_images()

    async def one_image(meta: dict, ref_urls: list[str]) -> str | None:
        """Generate one shot; return remote/local URL for consistency chaining."""
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
            )
        s = get_settings()
        await _record_seedream_usage(
            project_id,
            image_result=img,
            model=s.model_image,
            shot_id=meta["id"],
        )
        await persist_image(meta, img)
        return img.remote_url or img.local_url

    async def run_images() -> None:
        """Character mode: anchor first shot then parallelize. Diverse/style: all independent."""
        need = [m for m in shot_meta if not m.get("has_image")]
        already = [m for m in shot_meta if m.get("has_image")]
        for _m in already:
            await bump_images()

        if not need:
            return

        if not lock_character:
            # Content-driven: each shot uses only template base refs (if any)
            results = await asyncio.gather(
                *(one_image(m, list(base_refs)) for m in need),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, Exception):
                    raise r
            return

        anchor = existing_anchor
        first, rest = need[0], need[1:]
        first_refs = seedream_ref_urls(anchor, *base_refs) if anchor else list(base_refs)
        first_url = await one_image(first, first_refs)
        if first_url:
            anchor = first_url

        if not rest:
            return
        rest_refs = seedream_ref_urls(anchor, *base_refs) if anchor else list(base_refs)

        results = await asyncio.gather(
            *(one_image(m, rest_refs) for m in rest),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                raise r

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
                "分镜图与整片配音已完成"
            ),
        },
    )


async def _parallel_videos(project_id: int) -> None:
    """Run Seedance i2v for all shots concurrently (after images exist)."""
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
        tpl = project.template
        # 科普 full：Seedance 出操作音效，口播改后期 TTS
        generate_audio = _kepu_seedance_sfx_audio(project)
        ambient_only = generate_audio
        consistency = template_consistency_mode(tpl) == "character" and bool(
            tpl.seedance_config.get("character_consistency", True)
        )
        motion = str(tpl.seedance_config.get("motion_bias", ""))
        resolution = cfg.ark_video_resolution
        if project.resolution_mode == "hd" and resolution == "480p":
            resolution = "720p"
        ratio = _project_output_ratio(project) or cfg.ark_video_ratio
        shot_meta = [
            {
                "id": s.id,
                "shot_no": s.shot_no,
                "duration": float(s.duration),
                "video_prompt": s.video_prompt,
                "segment_script": getattr(s, "segment_script", "") or s.video_prompt or "",
                "camera": s.camera,
                "image_ref": s.image_ark_url or s.image_url or "",
                "has_video": bool(s.video_url),
            }
            for s in sorted(project.shots, key=lambda s: s.shot_no)
        ]
        style_prefix = _effective_style(project)
        total = len(shot_meta)

    if not shot_meta:
        return

    sem = asyncio.Semaphore(max(1, cfg.pipeline_video_concurrency))
    done = 0
    progress_lock = asyncio.Lock()

    async def one_video(meta: dict) -> None:
        nonlocal done
        await _ensure_not_cancelled(project_id)
        if meta.get("has_video"):
            async with progress_lock:
                done += 1
                pct = 55 + int(30 * done / max(total, 1))
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
            return
        async with sem:
            await _ensure_not_cancelled(project_id)
            script = (meta.get("segment_script") or meta.get("video_prompt") or "").strip()
            prompt = segplan.build_seedance_prompt(
                script,
                style_prefix=style_prefix,
                motion_bias=motion,
                camera=str(meta.get("camera") or ""),
                ambient_only=ambient_only,
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
                    async with progress_lock:
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
                    return
                raise
        s = get_settings()
        dur = max(float(dur), 2.0)
        billing_key = "seedance2:video0" if generate_audio else "seedance2:video1"
        await _record_seedance_usage(
            project_id,
            billing_key=billing_key,
            model=s.model_video,
            task_result=task_result,
            fallback_duration_sec=dur,
            shot_id=meta["id"],
        )
        async with _db_write_lock():
            async with AsyncSessionLocal() as db:
                shot = await db.get(Shot, meta["id"])
                if not shot:
                    return
                shot.video_url = local_video
                shot.status = ShotStatus.VIDEO_READY
                await db.commit()
        async with progress_lock:
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
                        f"AI 视频（含操作音效）{done}/{total}"
                        if generate_audio
                        else f"AI 视频 {done}/{total}"
                    ),
                },
            )

    results = await asyncio.gather(*(one_video(m) for m in shot_meta), return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        for err in errors:
            if isinstance(err, (PipelineCancelled, asyncio.CancelledError)):
                raise err
        raise RuntimeError(str(errors[0]))

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


async def _image_stage(project_id: int) -> None:
    await _set_status(project_id, ProjectStatus.IMAGING, 20, "IMAGING")
    ark = get_ark()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots), selectinload(Project.template))
        )
        project = result.scalar_one()
        tpl = project.template
        total = len(project.shots)
        ref_urls = _project_base_refs(project)
        image_size = _image_size_for(project)
        negative = _project_image_negative(project)
        style_prefix = _effective_style(project)
        bible = getattr(project, "character_bible", None) or ""
        photoreal = template_is_photoreal(tpl)
        consist = template_consistency_mode(tpl)
        lock_character = consist == "character"
        anchor: str | None = None

        for idx, shot in enumerate(sorted(project.shots, key=lambda s: s.shot_no)):
            await _ensure_not_cancelled(project_id)
            if shot.image_url or shot.image_ark_url:
                if lock_character and not anchor:
                    anchor = shot.image_ark_url or shot.image_url
                continue
            if lock_character:
                refs = seedream_ref_urls(anchor, *ref_urls) if anchor else list(ref_urls)
            else:
                refs = list(ref_urls)
            prompt = build_locked_image_prompt(
                style_prefix,
                strip_lock_blocks(shot.img_prompt),
                bible if lock_character else "",
                photoreal=photoreal,
                lock_character=lock_character,
                lock_style=True,
            )
            img = await ark.gen_image(
                prompt,
                negative,
                refs,
                project_id=project_id,
                shot_no=shot.shot_no,
                size=image_size,
            )
            shot.image_url = img.local_url
            shot.image_ark_url = img.remote_url
            shot.status = ShotStatus.IMAGE_READY
            if lock_character and not anchor:
                anchor = img.remote_url or img.local_url
            span = 55 if _is_image_text(project) else 25
            pct = 20 + int(span * (idx + 1) / max(total, 1))
            project.progress = pct
            await db.commit()
            await publish_progress(
                project_id,
                {
                    "event": "progress",
                    "stage": "IMAGING",
                    "shot": shot.shot_no,
                    "total": total,
                    "percent": pct,
                },
            )
        if project.shots:
            project.cover_url = sorted(project.shots, key=lambda s: s.shot_no)[0].image_url
        project.status = ProjectStatus.IMAGE_READY
        project.progress = 75 if _is_image_text(project) else 45
        await db.commit()


async def _video_stage(project_id: int) -> None:
    await _set_status(project_id, ProjectStatus.VIDEOING, 50, "VIDEOING")
    ark = get_ark()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots), selectinload(Project.template))
        )
        project = result.scalar_one()
        tpl = project.template
        generate_audio = _kepu_seedance_sfx_audio(project)
        ambient_only = generate_audio
        consistency = template_consistency_mode(tpl) == "character" and bool(
            tpl.seedance_config.get("character_consistency", True)
        )
        motion = str(tpl.seedance_config.get("motion_bias", ""))
        total = len(project.shots)
        cfg = get_settings()
        resolution = cfg.ark_video_resolution
        if project.resolution_mode == "hd" and resolution == "480p":
            resolution = "720p"
        ratio = _project_output_ratio(project) or cfg.ark_video_ratio
        style_prefix = _effective_style(project)
        for idx, shot in enumerate(sorted(project.shots, key=lambda s: s.shot_no)):
            await _ensure_not_cancelled(project_id)
            script = (getattr(shot, "segment_script", "") or shot.video_prompt or "").strip()
            prompt = segplan.build_seedance_prompt(
                script,
                style_prefix=style_prefix,
                motion_bias=motion,
                camera=shot.camera or "",
                ambient_only=ambient_only,
            )
            dur = segplan.resolve_api_duration(
                script,
                fallback=shot.duration,
                lo=cfg.seedance_duration_min,
                hi=cfg.seedance_duration_max,
            )
            image_ref = shot.image_ark_url or shot.image_url or ""
            local_video, task_result = await ark.gen_and_wait_video(
                image_ref,
                prompt,
                int(dur),
                project_id=project_id,
                shot_no=shot.shot_no,
                character_consistency=consistency,
                resolution=resolution,
                ratio=ratio,
                generate_audio=generate_audio,
            )
            shot.video_url = local_video
            shot.status = ShotStatus.VIDEO_READY
            billing_key = "seedance2:video0" if generate_audio else "seedance2:video1"
            await _record_seedance_usage(
                project_id,
                billing_key=billing_key,
                model=cfg.model_video,
                task_result=task_result,
                fallback_duration_sec=max(float(dur), 2.0),
                shot_id=shot.id,
            )
            pct = 50 + int(25 * (idx + 1) / max(total, 1))
            project.progress = pct
            await db.commit()
            await publish_progress(
                project_id,
                {
                    "event": "progress",
                    "stage": "VIDEOING",
                    "shot": shot.shot_no,
                    "total": total,
                    "percent": pct,
                },
            )
        project.status = ProjectStatus.VIDEO_READY
        project.progress = 75
        await db.commit()


async def _audio_stage(project_id: int) -> None:
    """Fallback audio stage — continuous narration for the whole film."""
    await _set_status(project_id, ProjectStatus.AUDIOING, 80, "AUDIOING")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots), selectinload(Project.template))
        )
        project = result.scalar_one()
        voice = _project_voice(project)
        shots = sorted(project.shots, key=lambda s: s.shot_no)
    await _synthesize_continuous_audio(
        project_id, voice=voice, shot_rows=shots, force=False
    )
    await publish_progress(
        project_id,
        {"event": "progress", "stage": "AUDIOING", "percent": 88, "message": "整片配音完成"},
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
        native_audio = _use_native_video_audio(project)
        out = storage.project_dir(project_id) / "final.mp4"

        if native_audio:
            # 模型已含配音/字幕：只拼接镜头，不再 TTS 叠轨与烧字
            video_paths: list[Path] = []
            for shot in sorted(project.shots, key=lambda s: s.shot_no):
                pdir = storage.project_dir(project_id)
                video_path = storage.local_path_from_url(shot.video_url or "")
                if shot.video_url and (not video_path or not video_path.exists()):
                    if shot.video_url.startswith("http"):
                        video_path = await storage.ensure_local_media(
                            shot.video_url, pdir / f"shot_{shot.shot_no:03d}.mp4"
                        )
                if video_path and video_path.exists():
                    video_paths.append(video_path)
            if not video_paths:
                raise RuntimeError("没有可用镜头视频，无法拼接成片（视频模型配音模式）")
            await publish_progress(
                project_id,
                {
                    "event": "progress",
                    "stage": "COMPOSING",
                    "percent": 94,
                    "message": f"拼接 {len(video_paths)} 段带配音视频…",
                },
            )
            await _run_ffmpeg_compose_with_retry(
                project_id,
                lambda: concat_native_videos(video_paths, out),
            )
            project.final_video_url = storage.publish_local(out)
            if project.status != ProjectStatus.CANCELLED:
                project.status = ProjectStatus.AUDITING
                project.progress = 96
            await db.commit()
        else:
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

            full_audio = _full_narration_path(project_id)
            if not full_audio.exists():
                full_audio = None

            sub_cfg = (project.template.subtitle_config if project.template else None) or {}
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
            # 科普 full：不要后期 BGM；静图成片仍可叠配乐
            bgm_path = None if mode != "image_text" else resolve_bgm_path(bgm_mood)
            keep_video_sfx = _kepu_seedance_sfx_audio(project)

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
        base_refs = _project_base_refs(project)
        lock_character = template_consistency_mode(project.template) == "character"
        if lock_character:
            anchor = _consistency_ref_from_shots([s for s in project.shots if s.id != shot.id])
            ref_urls = seedream_ref_urls(anchor, *base_refs) if anchor else list(base_refs)
        else:
            ref_urls = list(base_refs)
        negative = _project_image_negative(project)
        prompt = _locked_shot_prompt(project, shot.img_prompt)
        img = await ark.gen_image(
            prompt,
            negative,
            ref_urls,
            project_id=project_id,
            shot_no=shot.shot_no,
            size=_image_size_for(project),
        )
        shot.image_url = img.local_url
        shot.image_ark_url = img.remote_url
        shot.video_url = None
        shot.status = ShotStatus.IMAGE_READY
        shot.version += 1
        project.status = ProjectStatus.IMAGE_READY
        project.final_video_url = None
        await db.commit()
    s = get_settings()
    await _record_seedream_usage(
        project_id,
        image_result=img,
        model=s.model_image,
        shot_id=shot_id,
    )


@storage.without_intermediate_oss
async def regen_shot_video(project_id: int, shot_id: int) -> None:
    ark = get_ark()
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
        generate_audio = _kepu_seedance_sfx_audio(project)
        motion = str(project.template.seedance_config.get("motion_bias", ""))
        consistency = template_consistency_mode(project.template) == "character" and bool(
            project.template.seedance_config.get("character_consistency", True)
        )
        cfg = get_settings()
        resolution = cfg.ark_video_resolution
        if project.resolution_mode == "hd" and resolution == "480p":
            resolution = "720p"
        script = (getattr(shot, "segment_script", "") or shot.video_prompt or "").strip()
        prompt = segplan.build_seedance_prompt(
            script,
            style_prefix=_effective_style(project),
            motion_bias=motion,
            camera=shot.camera or "",
            ambient_only=generate_audio,
        )
        dur = segplan.resolve_api_duration(
            script,
            fallback=shot.duration,
            lo=cfg.seedance_duration_min,
            hi=cfg.seedance_duration_max,
        )
        image_ref = shot.image_ark_url or shot.image_url or ""
        local_video, task_result = await ark.gen_and_wait_video(
            image_ref,
            prompt,
            int(dur),
            project_id=project_id,
            shot_no=shot.shot_no,
            character_consistency=consistency,
            resolution=resolution,
            ratio=_project_output_ratio(project) or cfg.ark_video_ratio,
            generate_audio=generate_audio,
        )
        shot.video_url = local_video
        shot.status = ShotStatus.VIDEO_READY
        shot.version += 1
        project.final_video_url = None
        project.status = ProjectStatus.VIDEO_READY
        billing_key = "seedance2:video0" if generate_audio else "seedance2:video1"
        await _record_seedance_usage(
            project_id,
            billing_key=billing_key,
            model=cfg.model_video,
            task_result=task_result,
            fallback_duration_sec=max(float(dur), 2.0),
            shot_id=shot_id,
        )
        await db.commit()


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
        if _use_native_video_audio(project):
            raise ValueError("当前为视频模型配音，请使用「重生视频」重做该镜旁白")
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
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.shots))
        )
        project = result.scalar_one_or_none()
        shot = await db.get(Shot, shot_id)
        if shot:
            shot.version += 1
        if project:
            project.final_video_url = None
            shots = list(project.shots or [])
            if _is_image_text(project):
                project.status = ProjectStatus.IMAGE_READY
            elif shots and all(s.video_url for s in shots):
                project.status = ProjectStatus.VIDEO_READY
            else:
                project.status = ProjectStatus.IMAGE_READY
            await db.commit()


@storage.without_intermediate_oss
async def regen_project_audio_and_compose(project_id: int) -> None:
    """Force continuous re-TTS with current voice, then compose."""
    async with AsyncSessionLocal() as db:
        project = await db.get(Project, project_id)
        if project and _use_native_video_audio(project):
            raise ValueError("当前为视频模型配音，请重生各镜视频后点「拼接成片」")
    await _set_status(project_id, ProjectStatus.AUDIOING, 80, "AUDIOING")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.template), selectinload(Project.shots))
        )
        project = result.scalar_one()
        voice = _project_voice(project)
        shots = sorted(project.shots, key=lambda s: s.shot_no)
        project.final_video_url = None
        await db.commit()

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
