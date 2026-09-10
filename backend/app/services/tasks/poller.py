"""NIO-style Selector：集中非阻塞轮询 awaiting_poll 上游任务。"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models_tasks import TaskRun
from app.services.billing.settlement import settle_task
from app.services.tasks.service import append_task_event

# 与 drama.jobs 收尾认领态一致：异常时勿缩短仍在 finalizing 的 next_action_at
_FRAGMENT_FINALIZE_STEP = "finalizing"

logger = logging.getLogger("app.tasks.poller")

# Selector 循环句柄、停机信号、并发闸与心跳
_poller_task: asyncio.Task | None = None
_stop_event = asyncio.Event()
_poll_inflight: set[int] = set()
_selector_sem: asyncio.Semaphore | None = None
_last_poll_mono: float = 0.0
_intentionally_stopped: bool = True


# 启动 Selector 轮询循环。
async def start_poller() -> None:
    global _poller_task, _selector_sem, _intentionally_stopped, _last_poll_mono
    if _poller_task and not _poller_task.done():
        return
    _intentionally_stopped = False
    limit = max(1, int(get_settings().task_poll_max_concurrency or 20))
    _selector_sem = asyncio.Semaphore(limit)
    _stop_event.clear()
    _last_poll_mono = time.monotonic()
    _poller_task = asyncio.create_task(_poller_loop(), name="task-poller")


# 停止 Selector 轮询循环。
async def stop_poller() -> None:
    global _intentionally_stopped
    _intentionally_stopped = True
    _stop_event.set()
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass


# 看门狗拉起卡死或已退出的 Selector 循环。
async def restart_poller_loop(*, reason: str = "watchdog") -> None:
    global _poller_task, _intentionally_stopped, _last_poll_mono, _selector_sem
    if _intentionally_stopped:
        return
    logger.warning("restarting task poller loop reason=%s", reason)
    _stop_event.set()
    if _poller_task and not _poller_task.done():
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass
    limit = max(1, int(get_settings().task_poll_max_concurrency or 20))
    _selector_sem = asyncio.Semaphore(limit)
    _stop_event.clear()
    _last_poll_mono = time.monotonic()
    _poller_task = asyncio.create_task(_poller_loop(), name="task-poller")


# 返回 Selector 当前状态。
def poller_status() -> str:
    if _intentionally_stopped:
        return "stopped"
    if _poller_task and not _poller_task.done():
        return "running"
    return "stopped"


# 距上次 Selector 轮询完成的秒数。
def poller_tick_age_sec() -> float:
    if _last_poll_mono <= 0:
        return 1e9
    return max(0.0, time.monotonic() - _last_poll_mono)


# Selector 心跳是否过期。
def poller_tick_stale() -> bool:
    if _intentionally_stopped:
        return False
    poll_interval = max(1.0, float(get_settings().ark_video_poll_interval or 8.0))
    stale_sec = max(30.0, float(get_settings().task_poll_stale_sec), poll_interval * 4)
    return poller_tick_age_sec() > stale_sec


# Selector 主循环：周期性 select 到期 channel。
async def _poller_loop() -> None:
    global _last_poll_mono
    interval = max(1.0, float(get_settings().ark_video_poll_interval or 8.0))
    while not _stop_event.is_set():
        _last_poll_mono = time.monotonic()
        poll_stale = max(30.0, float(get_settings().task_poll_stale_sec), interval * 4)
        timeout = max(20.0, poll_stale - 10.0)
        try:
            await asyncio.wait_for(_select_and_poll_due(), timeout=timeout)
            await asyncio.wait_for(_poll_ephemeral_deferred_tasks(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("task selector tick timed out after %.0fs", timeout)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("task selector failed")
        finally:
            _last_poll_mono = time.monotonic()
        await asyncio.sleep(interval)


# 拉取到期 awaiting_poll 任务并并发非阻塞 poll（类似 NIO select + 就绪集合处理）。
async def _select_and_poll_due() -> None:
    now = datetime.now(UTC)
    batch_limit = max(1, int(get_settings().task_poll_max_concurrency or 20))
    async with AsyncSessionLocal() as db:
        stmt = (
            select(TaskRun.id)
            .where(
                TaskRun.status == "awaiting_poll",
                TaskRun.next_action_at.is_not(None),
                TaskRun.next_action_at <= now,
            )
            .order_by(TaskRun.next_action_at.asc(), TaskRun.id.asc())
            .limit(batch_limit)
        )
        task_ids = [int(item) for item in (await db.execute(stmt)).scalars().all()]

    if not task_ids:
        return

    async def _guarded_poll(task_id: int) -> None:
        if task_id in _poll_inflight:
            return
        _poll_inflight.add(task_id)
        sem = _selector_sem or asyncio.Semaphore(1)
        try:
            async with sem:
                await _poll_one_task(task_id)
        finally:
            _poll_inflight.discard(task_id)

    await asyncio.gather(*[_guarded_poll(task_id) for task_id in task_ids])


# 对单条已注册上游任务执行一次非阻塞状态查询。
async def _poll_one_task(task_id: int) -> None:
    from app.services.drama.jobs import poll_fragment_video_task

    async with AsyncSessionLocal() as db:
        task = await db.get(TaskRun, task_id)
        if not task or task.status != "awaiting_poll":
            return
        if not task.provider_task_id:
            task.status = "failed"
            task.error_code = "missing_provider_task_id"
            task.error_message = "缺少上游任务 ID，无法轮询"
            task.finished_at = datetime.now(UTC)
            await append_task_event(
                db,
                task.id,
                event_type="task.failed",
                status=task.status,
                phase=task.current_step_key,
                message=task.error_message,
            )
            try:
                await settle_task(db, task.id)
            except Exception:  # noqa: BLE001
                logger.exception("settle_task failed task_id=%s", task.id)
            await db.commit()
            return

    try:
        await poll_fragment_video_task(task_id)
    except Exception:  # noqa: BLE001
        logger.exception("selector poll failed task_id=%s", task_id)
        async with AsyncSessionLocal() as db:
            task = await db.get(TaskRun, task_id)
            if not task or task.status != "awaiting_poll":
                return
            # 仍在收尾认领中：保留长 TTL，避免并发 poller 挤进下载窗口
            if (task.current_step_status or "") == _FRAGMENT_FINALIZE_STEP:
                return
            poll_interval = max(1.0, float(get_settings().ark_video_poll_interval or 8.0))
            task.next_action_at = datetime.now(UTC) + timedelta(seconds=poll_interval)
            await db.commit()


# 后台轮询 api/studio 轻量视频任务：主动查上游终态，超时则失败并解冻。
async def _poll_ephemeral_deferred_tasks() -> None:
    from app.models import User
    from app.services.billing.ephemeral import settle_deferred_video_poll
    from app.services.studio_tools import poll_video_task

    now = datetime.now(UTC)
    timeout_sec = float(get_settings().ark_video_poll_timeout or 900.0)

    async with AsyncSessionLocal() as db:
        stmt = (
            select(TaskRun)
            .where(
                TaskRun.status == "awaiting_poll",
                TaskRun.domain.in_(["api", "studio"]),
                TaskRun.billing_status == "frozen",
            )
            .order_by(TaskRun.next_action_at.asc().nullsfirst(), TaskRun.id.asc())
            .limit(20)
        )
        rows = list((await db.execute(stmt)).scalars().all())

    for row in rows:
        task_id = int(row.id)
        async with AsyncSessionLocal() as db:
            task = await db.get(TaskRun, task_id)
            if not task or task.status != "awaiting_poll":
                continue

            started = task.started_at or task.created_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            if started and (now - started).total_seconds() > timeout_sec:
                task.status = "failed"
                task.error_code = "poll_timeout"
                task.error_message = "视频轮询超时，预扣已退回"
                task.finished_at = now
                await append_task_event(
                    db,
                    task.id,
                    event_type="task.failed",
                    status=task.status,
                    phase=task.current_step_key,
                    message=task.error_message,
                )
                try:
                    await settle_task(db, task.id)
                except Exception:  # noqa: BLE001
                    logger.exception("settle_task failed task_id=%s", task.id)
                await db.commit()
                continue

            user = await db.get(User, task.requested_by)
            provider_id = (task.provider_task_id or "").strip()
            if not user or not provider_id:
                continue

            data = await poll_video_task(user, provider_id)
            status = str(data.get("status") or "").strip().lower()
            if status in {"", "running", "queued"}:
                task.next_action_at = now + timedelta(
                    seconds=max(1.0, float(get_settings().ark_video_poll_interval or 8.0))
                )
                await db.commit()
                continue

            await settle_deferred_video_poll(
                db,
                user,
                provider_task_id=provider_id,
                poll_status=status,
                error=str(data.get("error") or "") or None,
                billing_task_id=task.id,
                usage_tokens=int((data.get("usage") or {}).get("total_tokens") or 0),
                completion_tokens=int((data.get("usage") or {}).get("completion_tokens") or 0),
                raw_usage=data.get("raw_usage") if isinstance(data.get("raw_usage"), dict) else None,
            )
            await db.commit()
