"""In-process task executor for the de-workerized task platform."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.database import AsyncSessionLocal
from app.services.billing.context import billing_scope
from app.services.billing.settlement import freeze_for_task, settle_task
from app.services.tasks.handlers import get_task_handler
from app.services.tasks.service import append_task_event, get_task_for_runtime, set_task_step_state

logger = logging.getLogger(__name__)


# 执行单个任务并回写平台状态。
async def execute_task_run(task_id: int) -> None:
    async with AsyncSessionLocal() as db:
        task = await get_task_for_runtime(db, task_id)
        if not task:
            return
        if task.cancel_requested and task.status == "cancel_requested":
            await _mark_cancelled(db, task)
            return
        handler = get_task_handler(task.domain, task.task_type)
        if handler is None:
            task.status = "failed"
            task.error_code = "handler_missing"
            task.error_message = f"未注册任务处理器: {task.domain}/{task.task_type}"
            task.finished_at = datetime.now(UTC)
            # Team queue reservations must be released even when a handler is unavailable.
            if task.team_id is None:
                task.billing_status = "none"
            await append_task_event(
                db,
                task.id,
                event_type="task.failed",
                status=task.status,
                phase=task.current_step_key,
                message=task.error_message,
            )
            if task.team_id is not None:
                await settle_task(db, task.id)
            await db.commit()
            return

        # 在 freeze_for_task 之前读取 steps：_lock_task(populate_existing=True)
        # 会卸掉已预加载的关系，之后访问 task.steps 会触发异步懒加载抛 MissingGreenlet。
        step = task.steps[0] if task.steps else None

        try:
            if (task.team_id is not None or (task.domain == 'studio' and task.drama_project_id is not None)) and not task.provider_task_id:
                from app.services.tasks.team_scope import ensure_task_may_submit
                await ensure_task_may_submit(db, task)
                from app.services.teams.edit_locks import validate_task_locks
                await validate_task_locks(db, task)
            await freeze_for_task(db, task)
        except ValueError as exc:
            # 余额不足：可预期失败，专用错误码便于前端引导充值
            await _fail_task_before_start(
                db, task, step, error_code="insufficient_balance", message=str(exc)
            )
            return
        except Exception as exc:  # noqa: BLE001
            # DB 瞬断等非 ValueError 不能裸逃：否则任务永久卡 leased，只能等 watchdog 周期兜底
            logger.exception("freeze_for_task failed task_id=%s", task.id)
            from app.services.exc_format import format_exception_message

            await _fail_task_before_start(
                db,
                task,
                step,
                error_code=type(exc).__name__,
                message=format_exception_message(exc, fallback="预扣失败", limit=500),
            )
            return

        now = datetime.now(UTC)
        task.status = "running"
        task.started_at = task.started_at or now
        task.next_action_at = None
        task.lease_until = now + timedelta(minutes=10)
        set_task_step_state(task, step, status="submitting", now=now)
        await append_task_event(
            db,
            task.id,
            event_type="task.started",
            status=task.status,
            phase=task.current_step_key,
            message="任务开始执行",
        )
        await db.commit()

    try:
        async with billing_scope(task_id, team_id=task.team_id, snapshot=task.billing_snapshot):
            async with AsyncSessionLocal() as db:
                task = await get_task_for_runtime(db, task_id)
                if not task:
                    return
                handler = get_task_handler(task.domain, task.task_type)
            # Handlers read the loaded task snapshot and own their database sessions.
            # Release this read transaction before waiting on a provider or its semaphore.
            result = await handler.executor(task) if handler else {"ok": False, "error": "missing_handler"}
            async with AsyncSessionLocal() as db:
                # A new session also observes cancellation/provider state committed by handlers.
                # Reload steps with selectinload; refresh would unload the relationship.
                task = await get_task_for_runtime(db, task_id)
                if not task:
                    return
                if isinstance(result, dict) and result.get("retry_download"):
                    await _requeue_video_download(db, task, result)
                    return
                if isinstance(result, dict) and (result.get("deferred") or result.get("awaiting_poll")):
                    await db.commit()
                    return
                if task.status == "awaiting_poll":
                    await db.commit()
                    return
                if isinstance(result, dict) and result.get("cancelled"):
                    await _mark_cancelled(db, task)
                    return
                # handler 返回 ok:False 时必须失败收敛（勿当成 succeeded）
                if isinstance(result, dict) and result.get("ok") is False:
                    err_text = str(result.get("error") or "任务执行失败").strip()[:500] or "任务执行失败"
                    await _fail_task(db, task, RuntimeError(err_text))
                    return
                await _complete_task(db, task, result or {"ok": True})
    except asyncio.CancelledError:
        async with AsyncSessionLocal() as db:
            task = await get_task_for_runtime(db, task_id)
            if task:
                if task.cancel_requested:
                    await _mark_cancelled(db, task)
                else:
                    await _requeue_interrupted_task(db, task)
        raise
    except Exception as exc:  # noqa: BLE001
        async with AsyncSessionLocal() as db:
            task = await get_task_for_runtime(db, task_id)
            if task:
                await _fail_task(db, task, exc)


# 把任务收敛到成功态。
async def _complete_task(db, task, result: dict) -> None:
    now = datetime.now(UTC)
    step = task.steps[0] if task.steps else None
    set_task_step_state(task, step, status="done", now=now)
    task.status = "cancelled" if task.cancel_requested else "succeeded"
    task.progress_percent = 100 if task.status == "succeeded" else task.progress_percent
    task.result_payload = result
    task.error_code = None
    task.error_message = None
    task.finished_at = now
    await append_task_event(
        db,
        task.id,
        event_type="task.completed" if task.status == "succeeded" else "task.cancelled",
        status=task.status,
        phase=task.current_step_key,
        message="任务执行完成" if task.status == "succeeded" else "任务已取消",
        payload=result,
    )
    try:
        await settle_task(db, task.id)
    except Exception:  # noqa: BLE001
        logger.exception("settle_task failed task_id=%s", task.id)
    await db.commit()
    from app.services.creation import reconcile_after_task
    await reconcile_after_task(task)


# 预扣阶段（handler 尚未执行）失败收敛：此时 _lock_task(populate_existing) 已卸掉
# task.steps 关系，不能像 _fail_task 那样再访问 task.steps[0]，step 由调用方预读传入。
async def _fail_task_before_start(db, task, step, *, error_code: str, message: str) -> None:
    now = datetime.now(UTC)
    set_task_step_state(task, step, status="failed", now=now)
    task.status = "failed"
    task.error_code = error_code
    task.error_message = message[:500]
    task.finished_at = now
    # frozen 之后的异常（如落流水失败）保留 frozen 交 settle_task 对账；未预扣成功保持 none
    if task.billing_status not in {"frozen", "reserved"}:
        task.billing_status = "none"
    await append_task_event(
        db,
        task.id,
        event_type="task.failed",
        status=task.status,
        phase=task.current_step_key,
        message=task.error_message,
    )
    # 资产生图/视频：同步写回 asset.params.generation，避免前端只看到空的「生图失败」
    await _fail_drama_asset_generation_if_needed(db, task, task.error_message)
    try:
        await settle_task(db, task.id)
    except Exception:  # noqa: BLE001
        logger.exception("settle_task failed task_id=%s", task.id)
    await db.commit()


# 把任务收敛到失败态。
async def _fail_task(db, task, exc: Exception) -> None:
    from app.services.exc_format import format_exception_message

    now = datetime.now(UTC)
    step = task.steps[0] if task.steps else None
    set_task_step_state(task, step, status="failed", now=now)
    task.status = "failed"
    task.error_code = type(exc).__name__
    task.error_message = format_exception_message(exc, fallback="任务执行失败", limit=500)
    task.finished_at = now
    await append_task_event(
        db,
        task.id,
        event_type="task.failed",
        status=task.status,
        phase=task.current_step_key,
        message=task.error_message,
    )
    # 资产生图/视频：同步写回 asset.params.generation，避免前端只看到空的「生图失败」
    await _fail_drama_asset_generation_if_needed(db, task, task.error_message or str(exc))
    if task.fragment_id:
        from app.models_drama import DramaEpisodeFragment
        from app.services.drama.generation import build_failed_generation_params

        frag = await db.get(DramaEpisodeFragment, int(task.fragment_id))
        if frag:
            params = dict(frag.params or {})
            prev_gen = params.get("generation") if isinstance(params.get("generation"), dict) else None
            # 保留 root_error（避免「内部重试超限」盖掉真人审核等真实原因）
            params["generation"] = build_failed_generation_params(
                prev_gen if isinstance(prev_gen, dict) else None,
                task.error_message or str(exc),
            )
            frag.params = params
    if task.domain == "kepu" and task.project_id:
        from app.models import Project, ProjectStatus

        running = {
            ProjectStatus.SCRIPTING,
            ProjectStatus.IMAGING,
            ProjectStatus.VIDEOING,
            ProjectStatus.AUDIOING,
            ProjectStatus.COMPOSING,
            ProjectStatus.AUDITING,
        }
        project = await db.get(Project, int(task.project_id))
        if project and project.status in running:
            project.status = ProjectStatus.FAILED
            project.error_msg = (task.error_message or str(exc))[:2000]
    payload = task.payload if isinstance(task.payload, dict) else {}
    if payload.get("sequential") and task.batch_key:
        from app.services.tasks.service import fail_remaining_sequential_batch

        batch_index = int(payload.get("batch_index", 0))
        await fail_remaining_sequential_batch(
            db,
            task.batch_key,
            batch_index,
            "上一镜失败，无法衔接尾帧",
        )
    try:
        await settle_task(db, task.id)
    except Exception:  # noqa: BLE001
        logger.exception("settle_task failed task_id=%s", task.id)
    await db.commit()


# 把任务收敛到取消态。
async def _mark_cancelled(db, task) -> None:
    # finalizing 收尾窗口内让位：poller 协程可能正在下载成片并落真实用量，
    # 此时全额退款会导致 usage_events 悬空、钱货两失；协程会按实结算或退回 polling。
    # 任务保持 cancel_requested，scheduler 下轮重试，窗口 TTL（10 分钟）兜底。
    from app.services.tasks.service import task_finalizing_window_open

    if task_finalizing_window_open(task):
        logger.info(
            "cancel deferred: task %s inside finalizing window, poller will settle",
            task.id,
        )
        return
    now = datetime.now(UTC)
    step = task.steps[0] if task.steps else None
    set_task_step_state(task, step, status="cancelled", now=now)
    task.status = "cancelled"
    task.finished_at = now
    task.next_action_at = None
    task.lease_until = None
    await append_task_event(
        db,
        task.id,
        event_type="task.cancelled",
        status=task.status,
        phase=task.current_step_key,
        message="任务已取消",
    )
    try:
        await settle_task(db, task.id)
    except Exception:  # noqa: BLE001
        logger.exception("settle_task failed task_id=%s", task.id)
    await db.commit()


async def _fail_drama_asset_generation_if_needed(db, task, error: str) -> None:
    """任务未开始执行时失败，同步更新漫剧资产 generation 状态。"""
    if (task.domain or "") != "drama" or not task.asset_id:
        return
    if (task.task_type or "") not in {"asset_image", "asset_video"}:
        return
    from app.models_drama import DramaAsset

    asset = await db.get(DramaAsset, int(task.asset_id))
    if not asset:
        return
    msg = (error or "").strip() or "生成失败"
    params = dict(asset.params or {})
    params["generation"] = {"status": "failed", "error": msg[:400]}
    asset.params = params


# 成片已在上游生成时退回待执行，下次只下载，不重新提交视频任务。
async def _requeue_video_download(db, task, result: dict) -> None:
    from app.services.drama.asset_video import (
        asset_video_download_retry_delay_sec,
        asset_video_download_retry_payload,
    )

    from app.config import get_settings

    provider_task_id = str(result.get("provider_task_id") or "").strip()
    if not result.get("counts_attempt", True):
        started = task.started_at or task.created_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        timeout_sec = float(get_settings().ark_video_poll_timeout or 900.0)
        if started is not None and (datetime.now(UTC) - started).total_seconds() > timeout_sec:
            await _fail_task(
                db,
                task,
                RuntimeError("视频已在上游生成，等待下载超时。请勿重新生成，联系客服按原任务拉取成片。"),
            )
            return
    payload = task.payload if isinstance(task.payload, dict) else {}
    if result.get("counts_attempt", True):
        updated = asset_video_download_retry_payload(payload, provider_task_id=provider_task_id)
    else:
        updated = dict(payload)
        updated["provider_task_id"] = provider_task_id
    if updated is None or not provider_task_id:
        await _fail_task(
            db,
            task,
            RuntimeError(
                "视频已在上游生成，但下载到服务器多次中断。请勿重新生成，联系客服按原任务拉取成片。"
            ),
        )
        return
    now = datetime.now(UTC)
    delay = asset_video_download_retry_delay_sec(int(updated.get("download_attempts") or 1))
    task.payload = updated
    task.provider_task_id = provider_task_id
    task.status = "pending"
    task.error_code = None
    task.error_message = None
    task.finished_at = None
    task.lease_token = None
    task.lease_until = None
    task.next_action_at = now + timedelta(seconds=delay)
    await append_task_event(
        db,
        task.id,
        event_type="task.requeued",
        status=task.status,
        phase=task.current_step_key,
        message=f"成片下载中断，将在 {delay} 秒后重试下载",
    )
    await db.commit()


# 应用重启或热更新中断时，把任务重新放回待执行状态。
async def _requeue_interrupted_task(db, task) -> None:
    now = datetime.now(UTC)
    step = task.steps[0] if task.steps else None
    set_task_step_state(task, step, status="pending", now=now)
    payload = dict(task.payload or {}) if isinstance(task.payload, dict) else {}
    provider_task_id = str(task.provider_task_id or payload.get("provider_task_id") or "").strip()
    if provider_task_id:
        payload["provider_task_id"] = provider_task_id
        task.payload = payload
        task.provider_task_id = provider_task_id
    task.status = "pending"
    task.next_action_at = now
    task.lease_token = None
    task.lease_until = None
    await append_task_event(
        db,
        task.id,
        event_type="task.requeued",
        status=task.status,
        phase=task.current_step_key,
        message="任务被中断，已重新排队",
    )
    await db.commit()
