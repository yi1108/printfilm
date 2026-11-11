"""Durable studio generation, using one scheduled task and one billing lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import ToolRun, User
from app.models_tasks import TaskRun
from app.schemas_tasks import TaskCreateRequest
from app.services.billing.context import billing_scope
from app.services.studio_tools import ensure_public_urls, poll_video_task, run_image_tool, start_video_tool
from app.services.tasks.service import append_task_event, create_task, get_task_for_runtime
from app.services.tasks.upstream import upstream_event_session

IMAGE_TOOLS = {"t2i", "i2i", "i2p", "ecom"}
VIDEO_TOOLS = {"t2v", "v2v"}
VOICES = {"narrator_calm", "warm_storyteller", "teacher_clear"}


def video_audio_enabled(model_id: str | None, requested: bool | None = None) -> bool:
    from app.services.media_models.prices import resolve_strategy
    strategy = resolve_strategy(model_id or get_settings().model_video)
    enabled = strategy.supports_generate_audio if requested is None else requested
    if enabled and not strategy.supports_generate_audio:
        raise ValueError('所选视频模型不支持生成声音')
    return enabled


def validate_generation(tool_id: str, prompt: str, params: dict, file_count: int, *, quote: bool = False) -> str:
    if tool_id not in IMAGE_TOOLS | VIDEO_TOOLS | {"audio"}:
        raise ValueError("未知生成类型")
    kind = "image" if tool_id in IMAGE_TOOLS else "video" if tool_id in VIDEO_TOOLS else "audio"
    video_mode = params.get("video_mode") if kind == "video" else None
    if not quote and (tool_id in {"t2i", "t2v", "audio"} or video_mode) and not prompt.strip():
        raise ValueError("请填写生成内容")
    if len(prompt) > (2000 if kind == "audio" else 7000):
        raise ValueError("生成内容超过字数限制")
    if tool_id in {"i2i", "i2p", "v2v"} and not video_mode and not file_count:
        raise ValueError("请上传参考文件")
    if tool_id == "v2v" and not video_mode and file_count > 1:
        raise ValueError("视频生成只支持一个参考文件")
    if tool_id == "audio" and file_count:
        raise ValueError("音频生成请直接输入文字")
    if kind in {"image", "video"}:
        from app.services.media_models.prices import resolve_strategy
        model = params.get("model_id") or (get_settings().model_image if kind == "image" else get_settings().model_video)
        strategy = resolve_strategy(model)
        if strategy.capability != kind:
            raise ValueError("model: 模型类型不匹配")
        from app.services.media_models.planning import reference_params
        if video_mode:
            from app.services.studio_references import parse_references, validate_reference_mode
            refs = parse_references(params.get("references") or [])
            validate_reference_mode(video_mode, refs, None if quote else file_count)
            references = reference_params(params)
        else:
            references = {"reference_images": [f"pending://upload/{i}" for i in range(file_count or (1 if kind == "video" else 0))]}
        if kind == 'video':
            params['generate_audio'] = video_audio_enabled(model, params.get('generate_audio'))
        strategy.normalize_and_validate({"aspect_ratio": params.get("ratio") or ("1:1" if kind == "image" else "9:16"),
            "resolution": params.get("resolution") or ("2K" if kind == "image" else "480p"),
            **references,
            **({"generate_audio": params["generate_audio"], "duration": str(params.get("duration") or "5").removesuffix("s")} if kind == "video" else {})})
    if kind == "audio" and params.get("voice", "narrator_calm") not in VOICES:
        raise ValueError("不支持的音色")
    return kind


async def enqueue_generation(db, user, *, tool_id: str, prompt: str, params: dict, files: list[Path], drama_project_id: int | None = None) -> dict:
    kind = validate_generation(tool_id, prompt, params, len(files))
    row = ToolRun(user_id=user.id, tool_id=tool_id, kind=kind, status="queued", prompt=prompt.strip(),
                  params={**params, "file_paths": [str(p) for p in files]})
    db.add(row)
    await db.flush()
    payload = {**params, "run_id": row.id, "tool_id": tool_id,
               "duration": int(str(params.get("duration") or "5").removesuffix("s")),
               "resolution": params.get("resolution") or ("480p" if kind == "video" else "2K"), "generate_audio": params.get("generate_audio", False)}
    if not params.get("video_mode"):
        payload["reference_images"] = [str(path) for path in files]
    task = await create_task(db, user, TaskCreateRequest(
        domain="studio", task_type=f"tool_{kind}", cancelable=False, payload=payload, drama_project_id=drama_project_id,
    ), commit=False)
    row.task_id = f"task-{task.id}"
    row.params = {**row.params, "platform_task_id": task.id, "billing_task_id": task.id}
    await db.flush()
    return {"kind": kind, "urls": [], "task_id": row.task_id, "platform_task_id": task.id,
            "status": "queued", "run_id": row.id, "message": "任务已排队，可在我的任务中查看进度"}


async def execute_generation(task: TaskRun) -> dict:
    async with AsyncSessionLocal() as db:
        row = await db.get(ToolRun, int((task.payload or {}).get("run_id") or 0))
        if not row or row.user_id != task.requested_by:
            raise ValueError("生成记录不存在")
        stored_task = await db.get(TaskRun, task.id, populate_existing=True)
        if stored_task.result_payload and stored_task.result_payload.get("urls"):
            return stored_task.result_payload
        user = await db.get(User, row.user_id)
        if not user:
            raise ValueError("用户不存在")
        params = dict(row.params or {})
        files = [Path(p) for p in params.get("file_paths") or []]
        row.status = "running"
        await db.commit()
        if row.kind == "video":
            # Observation persists an accepted provider ID immediately; on recovery reuse it.
            provider_id = stored_task.provider_task_id
            if not provider_id:
                data = await start_video_tool(db, user, tool_id=row.tool_id, prompt=row.prompt,
                    ratio=params.get("ratio"), duration_raw=params.get("duration"),
                    motion=params.get("motion"), files=files, output_no=row.id,
                    model_id=params.get("model_id"), resolution=params.get("resolution"),
                    video_mode=params.get("video_mode"), references=stored_task.payload, generate_audio=stored_task.payload.get("generate_audio", False))
                provider_id = data["task_id"]
                row.preview_url = data.get("preview_url")
            stored_task.provider_task_id = provider_id
            stored_task.provider_status = "queued"
            stored_task.status = "awaiting_poll"
            stored_task.current_step_status = "awaiting_poll"
            stored_task.next_action_at = datetime.now(UTC)
            row.params = {**params, "provider_task_id": provider_id}
            await append_task_event(db, task.id, event_type="task.submitted", status="awaiting_poll",
                                    payload={"provider_task_id": provider_id})
            await db.commit()
            return {"awaiting_poll": True}
        if row.kind == "audio":
            from app.services.ark import get_ark
            from app.services.billing import record_line
            from app.services.studio_tools import ensure_public_url
            url = await get_ark().tts(row.prompt, params.get("voice") or "narrator_calm",
                                      project_id=0, shot_no=row.id, duration_hint=max(1, len(row.prompt) / 4))
            await record_line(db, user_id=user.id, billing_key="tts", model=get_settings().model_audio,
                              estimated=True, domain="studio", raw={"characters": len(row.prompt)})
            data = {"kind": "audio", "urls": [ensure_public_url(url) or url], "status": "succeeded"}
        else:
            data = await run_image_tool(db, user, tool_id=row.tool_id, prompt=row.prompt,
                negative=str(params.get("negative") or ""), ratio=params.get("ratio"),
                strength=params.get("strength"), mode=params.get("mode"), pack=params.get("pack"),
                files=files, output_no=row.id, model_id=params.get("model_id"),
                resolution=params.get("resolution"))
        urls = ensure_public_urls(data.get("urls"))
        if not urls or not all(urls):
            raise RuntimeError("上游未返回生成结果")
        row.urls = urls
        row.preview_url = urls[0] if row.kind == "image" else row.preview_url
        # Persist result before executor finalization, so recovery cannot regenerate it.
        stored_task.result_payload = {"ok": True, **data, "urls": urls}
        await db.commit()
        return stored_task.result_payload


async def poll_generation_video(task_id: int) -> None:
    from app.services.ark import TaskResult
    from app.services.drama.billing_util import record_seedance_video_usage, seedance_billing_key
    from app.services.tasks.executor import _complete_task, _fail_task

    async with AsyncSessionLocal() as db:
        # One process owns this poll and its result/usage transaction. Other pollers skip it.
        locked = (await db.execute(select(TaskRun.id).where(
            TaskRun.id == task_id, TaskRun.status == "awaiting_poll",
            TaskRun.next_action_at <= datetime.now(UTC),
        ).with_for_update(skip_locked=True))).scalar_one_or_none()
        if not locked:
            return
        task = await get_task_for_runtime(db, task_id)
        row = await db.get(ToolRun, int((task.payload or {}).get("run_id") or 0))
        if not row:
            await _fail_task(db, task, ValueError("生成记录不存在"))
            return
        started = task.started_at or task.created_at
        if started and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if started and (datetime.now(UTC) - started).total_seconds() > get_settings().ark_video_poll_timeout:
            await _fail_task(db, task, TimeoutError("视频生成超时"))
            return
        user = await db.get(User, task.requested_by)
        async with billing_scope(task.id, snapshot=task.billing_snapshot), upstream_event_session(db):
            async def stage_changed(stage):
                task.provider_status = stage
                await db.commit()
            data = await poll_video_task(user, task.provider_task_id, on_stage=stage_changed)
            task.provider_status = data["status"]
            if data["status"] == "succeeded":
                usage = data.get("usage") or {}
                result = TaskResult(status="succeeded", total_tokens=usage.get("total_tokens", 0),
                                    completion_tokens=usage.get("completion_tokens", 0), raw_usage=data.get("raw_usage"))
                await record_seedance_video_usage(db, user_id=user.id, billing_key=seedance_billing_key(generate_audio=bool((task.payload or {}).get("generate_audio", False))),
                    model=(task.payload or {}).get("model_id") or get_settings().model_video, domain="studio", task_result=result,
                    fallback_duration_sec=(task.payload or {}).get("duration"), resolution=(task.payload or {}).get("resolution") or "480p",
                    provider_task_id=task.provider_task_id)
                row.urls = data["urls"]
                row.status = "succeeded"
                step = task.steps[0] if task.steps else None
                if step:
                    step.provider_task_id = task.provider_task_id
                await _complete_task(db, task, {"ok": True, **data})
            elif data["status"] == "failed":
                row.status = "failed"
                row.error = data.get("error") or "生成失败"
                await _fail_task(db, task, RuntimeError(row.error))
            else:
                task.next_action_at = datetime.now(UTC) + timedelta(seconds=max(1, get_settings().ark_video_poll_interval))
                await db.commit()


async def sync_generation_record(db, row: ToolRun) -> TaskRun | None:
    task_id = (row.params or {}).get("platform_task_id")
    if not task_id:
        return None
    task = await db.get(TaskRun, int(task_id), populate_existing=True)
    if task and task.requested_by == row.user_id:
        row.status = {"pending": "queued", "leased": "queued", "awaiting_poll": "running"}.get(task.status, task.status)
        row.error = task.error_message
        result = task.result_payload or {}
        if result.get("urls"):
            row.urls = result["urls"]
        return task
    return None
