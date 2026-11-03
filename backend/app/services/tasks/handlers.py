"""Task handler registry for the de-workerized task platform."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import asyncio
from dataclasses import dataclass
from typing import Any

from app.models_tasks import TaskRun
from app.schemas_tasks import TaskCreateRequest, TaskStepCreate

TaskExecutor = Callable[[TaskRun], Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True)
class TaskHandler:
    """Describe how one task type is planned and executed."""

    domain: str
    task_type: str
    executor: TaskExecutor

    # 为任务创建时生成默认步骤
    def plan_steps(self, body: TaskCreateRequest) -> list[TaskStepCreate]:
        return [TaskStepCreate(step_key=body.task_type, step_type="job")]


# 执行漫剧剧本摘要任务。
async def _run_drama_script_summary(task: TaskRun) -> dict[str, Any] | None:
    from app.services.drama.jobs import run_script_summary_job

    return await run_script_summary_job(_require_int(task.drama_project_id, "drama_project_id"))


# 执行漫剧分集剧本生成任务。
async def _run_drama_episode_script(task: TaskRun) -> dict[str, Any] | None:
    from app.services.drama.jobs import run_episode_scripts_job

    payload = task.payload or {}
    episode_raw = payload.get("episode_number")
    try:
        episode_number = int(episode_raw) if episode_raw not in (None, "") else None
    except (TypeError, ValueError):
        episode_number = None
    draft = str(payload.get("draft") or "").strip() or None
    generate_mode = str(payload.get("generate_mode") or "").strip() or None
    return await run_episode_scripts_job(
        _require_int(task.drama_project_id, "drama_project_id"),
        force=bool(payload.get("force")),
        task_id=int(task.id),
        episode_number=episode_number,
        draft=draft,
        generate_mode=generate_mode,
    )


# 执行单集分镜规划任务。
async def _run_drama_fragment_plan(task: TaskRun) -> dict[str, Any] | None:
    from app.services.drama.jobs import run_episode_fragment_plan_job

    payload = task.payload or {}
    return await run_episode_fragment_plan_job(
        _require_int(task.episode_id, "episode_id"),
        fallback_rules=bool(payload.get("fallback_rules", True)),
        subtitle_enabled=payload.get("subtitle_enabled"),
        force=bool(payload.get("force")),
    )


# 执行漫剧分镜视频任务（NIO + 任务平台计费；每 task 仅处理一个 fragment）。
async def _run_drama_fragment_video(task: TaskRun) -> dict[str, Any] | None:
    from app.services.drama.jobs import submit_fragment_video_task

    payload = task.payload or {}
    fragment_ids = payload.get("fragment_ids") or []
    if fragment_ids and not isinstance(fragment_ids, list):
        raise ValueError("fragment_ids 必须为数组")
    return await submit_fragment_video_task(task)


# 执行漫剧资产生图任务。
async def _run_drama_asset_image(task: TaskRun) -> dict[str, Any] | None:
    from app.services.drama.jobs import run_asset_image_job

    payload = task.payload or {}
    return await run_asset_image_job(
        _require_int(task.drama_project_id, "drama_project_id"),
        int(task.requested_by),
        str(payload.get("prompt") or "").strip(),
        asset_id=task.asset_id,
        name=(payload.get("name") or None),
        kind=str(payload.get("kind") or "character"),
        image_style_id=(payload.get("image_style_id") or None),
        model_id=(payload.get("model_id") or None),
        aspect_ratio=(payload.get("aspect_ratio") or None),
        resolution=(payload.get("resolution") or None),
    )


# 执行漫剧资产生视频任务。
async def _run_drama_asset_video(task: TaskRun) -> dict[str, Any] | None:
    from app.services.drama.jobs import run_asset_video_job

    payload = task.payload or {}
    reference_asset_ids = payload.get("reference_asset_ids") or []
    if not isinstance(reference_asset_ids, list):
        raise ValueError("reference_asset_ids 必须为数组")
    provider_task_id = str(payload.get("provider_task_id") or task.provider_task_id or "").strip() or None

    async def _remember_provider_task(provider_id: str) -> None:
        """上游任务一创建就落库，下载中断后下次只拉成片、不重新生成。"""
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = await db.get(TaskRun, int(task.id))
            if row is None:
                return
            stored = dict(row.payload or {})
            stored["provider_task_id"] = provider_id
            row.payload = stored
            row.provider_task_id = provider_id
            await db.commit()

    return await run_asset_video_job(
        _require_int(task.drama_project_id, "drama_project_id"),
        int(task.requested_by),
        str(payload.get("prompt") or "").strip(),
        _require_int(task.asset_id, "asset_id"),
        model_id=(payload.get("model_id") or None),
        aspect_ratio=(payload.get("aspect_ratio") or None),
        resolution=(payload.get("resolution") or None),
        duration_sec=payload.get("duration_sec"),
        image_style_id=(payload.get("image_style_id") or None),
        reference_asset_ids=[int(item) for item in reference_asset_ids],
        provider_task_id=provider_task_id,
        on_provider_task=_remember_provider_task,
    )


# 执行漫剧资产抽取任务。
async def _run_drama_seed_assets(task: TaskRun) -> dict[str, Any] | None:
    from app.services.drama.jobs import run_seed_assets_job

    payload = task.payload or {}
    return await run_seed_assets_job(
        _require_int(task.drama_project_id, "drama_project_id"),
        refresh_prompts=bool(payload.get("refresh_prompts")),
        reextract_props=bool(payload.get("reextract_props")),
    )


# 执行科普可取消子流程：项目已被用户请求取消时，PipelineCancelled 收敛为
# {"cancelled": True}（executor 据此落取消态并退回冻结）；其余异常照常抛出。
async def _await_kepu(task: TaskRun, aw: Awaitable[Any], **extra: Any) -> dict[str, Any]:
    from app.services.pipeline import PipelineCancelled

    try:
        await aw
    except PipelineCancelled:
        if task.cancel_requested:
            return {"cancelled": True, "project_id": task.project_id, **extra}
        raise
    result = {"ok": True, "project_id": task.project_id, **extra}
    result.update(await _kepu_output_snapshot(task, extra.get("phase")))
    return result


async def _kepu_output_snapshot(task: TaskRun, phase: str | None) -> dict[str, Any]:
    """Freeze the completed generation's outputs before later edits replace them."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models import Project, Shot

    if task.task_type == "shot_regen_image" or phase == "assets":
        kind, field = "image", "image_url"
    elif task.task_type in {"shot_regen_audio", "project_regen_audio"} or phase == "audio":
        kind, field = "audio", "audio_url"
    elif task.task_type == "shot_regen_video" or phase == "videos":
        kind, field = "video", "video_url"
    elif task.task_type in {"project_compose_only", "project_pipeline"} and phase not in {"script", "storyboard"}:
        kind, field = "video", "final_video_url"
    else:
        kind, field = "text", None
    async with AsyncSessionLocal() as db:
        project = await db.get(Project, task.project_id)
        if project is None:
            return {"kind": kind, "urls": []}
        if field == "final_video_url":
            urls = [project.final_video_url] if project.final_video_url else []
        else:
            query = select(Shot).where(Shot.project_id == task.project_id).order_by(Shot.shot_no)
            if task.shot_id:
                query = query.where(Shot.id == task.shot_id)
            shots = list((await db.execute(query)).scalars().all())
            if field:
                urls = list(dict.fromkeys(getattr(shot, field) for shot in shots if getattr(shot, field)))
            else:
                return {"kind": "text", "text_content": "\n\n".join(
                    shot.narration or shot.segment_script or "" for shot in shots
                )}
        result = {"kind": kind, "urls": urls}
        if project.cover_url:
            result["preview_url"] = project.cover_url
        return result


# 执行科普分阶段流水线（严格按 payload.phase 预扣对应阶段）。
async def _run_kepu_project_pipeline(task: TaskRun) -> dict[str, Any] | None:
    from app.services.pipeline import clear_pipeline_cancellation, run_pipeline

    payload = task.payload if isinstance(task.payload, dict) else {}
    if task.cancel_requested:
        return {"cancelled": True, "project_id": task.project_id}
    project_id = _require_int(task.project_id, "project_id")
    raw_phase = payload.get("phase")
    phase = str(raw_phase).strip().lower() if raw_phase is not None else None
    if phase not in {"script", "assets", "videos", "compose"}:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.database import AsyncSessionLocal
        from app.models import Project
        from app.services.kepu_stages import normalize_kepu_pipeline_phase

        async with AsyncSessionLocal() as db:
            project = (await db.execute(
                select(Project).where(Project.id == project_id).options(selectinload(Project.shots))
            )).scalar_one_or_none()
            if project is not None:
                # Resolve legacy auto/produce before generation changes readiness.
                # Use the pipeline's shared rules for both execution and its saved output.
                phase = normalize_kepu_pipeline_phase(phase, project)
        # The read transaction is closed before awaiting external generation.
    # The previous task can have been cancelled before its pipeline ever ran,
    # leaving a process-local marker. Clear it in the executing worker only for
    # this fresh task; persistent CANCELLED checks still catch a new cancellation.
    clear_pipeline_cancellation(project_id)
    return await _await_kepu(
        task,
        run_pipeline(
            project_id,
            phase=phase,
        ),
        phase=phase,
    )


# 执行科普单镜生图任务。
async def _run_kepu_shot_image(task: TaskRun) -> dict[str, Any] | None:
    from app.services.pipeline import regen_shot_image

    return await _await_kepu(
        task,
        regen_shot_image(
            _require_int(task.project_id, "project_id"),
            _require_int(task.shot_id, "shot_id"),
        ),
        shot_id=task.shot_id,
    )


# 执行科普单镜生视频任务。
async def _run_kepu_shot_video(task: TaskRun) -> dict[str, Any] | None:
    from app.services.pipeline import regen_shot_video

    return await _await_kepu(
        task,
        regen_shot_video(
            _require_int(task.project_id, "project_id"),
            _require_int(task.shot_id, "shot_id"),
        ),
        shot_id=task.shot_id,
    )


# 执行科普单镜配音任务。
async def _run_kepu_shot_audio(task: TaskRun) -> dict[str, Any] | None:
    from app.services.pipeline import regen_shot_audio

    return await _await_kepu(
        task,
        regen_shot_audio(
            _require_int(task.project_id, "project_id"),
            _require_int(task.shot_id, "shot_id"),
        ),
        shot_id=task.shot_id,
    )


# 执行科普整片重配音任务。
async def _run_kepu_project_audio(task: TaskRun) -> dict[str, Any] | None:
    from app.services.pipeline import clear_pipeline_cancellation, regen_project_audio_and_compose

    if task.cancel_requested:
        return {"cancelled": True, "project_id": task.project_id}
    # Same stale-marker guard as the pipeline/compose handlers: a previous task
    # cancelled before start leaves a process-local marker that would otherwise
    # make this fresh re-voice task abort inside _set_status.
    clear_pipeline_cancellation(_require_int(task.project_id, "project_id"))
    return await _await_kepu(
        task,
        regen_project_audio_and_compose(_require_int(task.project_id, "project_id")),
    )


# 执行科普仅合成任务。
async def _run_kepu_compose(task: TaskRun) -> dict[str, Any] | None:
    from app.services.pipeline import clear_pipeline_cancellation, compose_only

    if task.cancel_requested:
        return {"cancelled": True, "project_id": task.project_id}
    clear_pipeline_cancellation(_require_int(task.project_id, "project_id"))
    return await _await_kepu(
        task,
        compose_only(_require_int(task.project_id, "project_id")),
    )


# 执行延时模拟任务，便于验证任务平台状态流转。
async def _run_tools_mock_delay(task: TaskRun) -> dict[str, Any] | None:
    payload = task.payload or {}
    delay_seconds = int(payload.get("delay_seconds") or 10)
    if delay_seconds < 1 or delay_seconds > 600:
        raise ValueError("delay_seconds 必须在 1-600 秒之间")
    await asyncio.sleep(delay_seconds)
    succeed = payload.get("succeed", True)
    if not isinstance(succeed, bool):
        raise ValueError("succeed 必须为布尔值")
    if not succeed:
        raise RuntimeError(str(payload.get("error_message") or "mock delayed task failed"))
    result_payload = payload.get("result_payload")
    return {
        "ok": True,
        "delay_seconds": delay_seconds,
        "echo": (
            {"message": "mock delayed task finished"}
            if result_payload is None
            else result_payload
        ),
    }


# 轻量任务占位 handler（实际由 run_billed_ephemeral 内联执行）。
async def _noop_ephemeral(task: TaskRun) -> dict[str, Any] | None:
    return {"ok": True, "ephemeral": True}


async def _run_studio_generation(task: TaskRun) -> dict[str, Any] | None:
    from app.services.studio_generation import execute_generation
    return await execute_generation(task)


async def _run_creation_turn(task: TaskRun) -> dict[str, Any] | None:
    from app.services.creation import execute_creation_turn
    return await execute_creation_turn(task)


# 确保关键主键字段存在。
def _require_int(value: int | None, field_name: str) -> int:
    if isinstance(value, int) and value > 0:
        return value
    raise ValueError(f"任务缺少 {field_name}")


TASK_HANDLERS: dict[tuple[str, str], TaskHandler] = {
    ("kepu", "creation_turn"): TaskHandler("kepu", "creation_turn", _run_creation_turn),
    ("drama", "script_summary"): TaskHandler("drama", "script_summary", _run_drama_script_summary),
    ("drama", "episode_script"): TaskHandler("drama", "episode_script", _run_drama_episode_script),
    ("drama", "fragment_plan"): TaskHandler("drama", "fragment_plan", _run_drama_fragment_plan),
    ("drama", "fragment_video"): TaskHandler("drama", "fragment_video", _run_drama_fragment_video),
    ("drama", "asset_image"): TaskHandler("drama", "asset_image", _run_drama_asset_image),
    ("drama", "asset_video"): TaskHandler("drama", "asset_video", _run_drama_asset_video),
    ("drama", "seed_assets"): TaskHandler("drama", "seed_assets", _run_drama_seed_assets),
    ("drama", "agent_chat"): TaskHandler("drama", "agent_chat", _noop_ephemeral),
    ("drama", "skill_optimize"): TaskHandler("drama", "skill_optimize", _noop_ephemeral),
    ("drama", "voice_prompt"): TaskHandler("drama", "voice_prompt", _noop_ephemeral),
    ("drama", "voice_synthesis"): TaskHandler("drama", "voice_synthesis", _noop_ephemeral),
    ("drama", "episode_compose"): TaskHandler("drama", "episode_compose", _noop_ephemeral),
    ("kepu", "content_expand"): TaskHandler("kepu", "content_expand", _noop_ephemeral),
    ("kepu", "voice_preview"): TaskHandler("kepu", "voice_preview", _noop_ephemeral),
    ("studio", "tool_image"): TaskHandler("studio", "tool_image", _run_studio_generation),
    ("studio", "tool_video"): TaskHandler("studio", "tool_video", _run_studio_generation),
    ("studio", "tool_audio"): TaskHandler("studio", "tool_audio", _run_studio_generation),
    ("kepu", "project_pipeline"): TaskHandler("kepu", "project_pipeline", _run_kepu_project_pipeline),
    ("kepu", "shot_regen_image"): TaskHandler("kepu", "shot_regen_image", _run_kepu_shot_image),
    ("kepu", "shot_regen_video"): TaskHandler("kepu", "shot_regen_video", _run_kepu_shot_video),
    ("kepu", "shot_regen_audio"): TaskHandler("kepu", "shot_regen_audio", _run_kepu_shot_audio),
    ("kepu", "project_regen_audio"): TaskHandler("kepu", "project_regen_audio", _run_kepu_project_audio),
    ("kepu", "project_compose_only"): TaskHandler("kepu", "project_compose_only", _run_kepu_compose),
    ("tools", "mock_delay"): TaskHandler("tools", "mock_delay", _run_tools_mock_delay),
}


# 按 domain + task_type 找到平台 handler。
def get_task_handler(domain: str, task_type: str) -> TaskHandler | None:
    return TASK_HANDLERS.get((domain, task_type))
