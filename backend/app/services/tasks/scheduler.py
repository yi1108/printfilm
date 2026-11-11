"""Task scheduler that leases due tasks and starts in-process execution."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models_tasks import TaskRun
from app.services.tasks.queues import QUEUE_TYPES, queue_capacity
from app.services.tasks.execution_policy import llm_task_condition
from app.services.billing.settlement import reconcile_terminal_frozen_tasks
from app.services.tasks.executor import _mark_cancelled, execute_task_run
from app.services.tasks.service import (
    FINALIZING_UNTIL_KEY,
    append_task_event,
    count_user_active_runtime_tasks,
    get_task_for_runtime,
    reconcile_sequential_batches,
    reconcile_stale_pending_tasks,
    task_finalizing_window_open,
)

logger = logging.getLogger("app.tasks.scheduler")

# 调度循环句柄、进程内执行槽、停机信号、心跳与孤儿扫描时间戳
_scheduler_task: asyncio.Task | None = None
_running_jobs: dict[int, asyncio.Task] = {}
_running_queues: dict[int, str] = {}
_cancel_jobs: dict[int, asyncio.Task] = {}
_maintenance_task: asyncio.Task | None = None
_stop_event = asyncio.Event()
_last_tick_mono: float = 0.0
_last_success_mono: float = 0.0
_loop_started_mono: float = 0.0
_consecutive_failures: int = 0
_intentionally_stopped: bool = True
_MAINTENANCE_TIMEOUT_SEC = 5.0
_MAX_CLAIM_PAGES = 4
_MAX_CANDIDATES_PER_PAGE = 128
_MAX_CANCEL_JOBS = 16


# 启动任务调度循环。
async def start_scheduler() -> None:
    global _scheduler_task, _intentionally_stopped, _last_tick_mono
    global _last_success_mono, _consecutive_failures
    global _loop_started_mono
    if _scheduler_task and not _scheduler_task.done():
        return
    _intentionally_stopped = False
    _stop_event.clear()
    _last_tick_mono = time.monotonic()
    _loop_started_mono = _last_tick_mono
    _last_success_mono = 0.0
    _consecutive_failures = 0
    _ensure_maintenance_loop()
    _scheduler_task = asyncio.create_task(_scheduler_loop(), name="task-scheduler")


# 停止任务调度循环并取消执行中的任务。
async def stop_scheduler() -> None:
    global _intentionally_stopped
    _intentionally_stopped = True
    _stop_event.set()
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    if _maintenance_task and not _maintenance_task.done():
        _maintenance_task.cancel()
        await asyncio.gather(_maintenance_task, return_exceptions=True)
    running_jobs = list(_running_jobs.values()) + list(_cancel_jobs.values())
    for task in running_jobs:
        if not task.done():
            task.cancel()
    if running_jobs:
        await asyncio.gather(*running_jobs, return_exceptions=True)
    _running_jobs.clear()
    _running_queues.clear()
    _cancel_jobs.clear()


# 仅重启调度循环（保留进程内仍在跑的 job），用于看门狗拉起卡死 tick。
async def restart_scheduler_loop(*, reason: str = "watchdog") -> None:
    global _scheduler_task, _intentionally_stopped
    global _loop_started_mono
    if _intentionally_stopped:
        return
    logger.warning("restarting task scheduler loop reason=%s", reason)
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    _stop_event.clear()
    _ensure_maintenance_loop()
    _loop_started_mono = time.monotonic()
    _scheduler_task = asyncio.create_task(_scheduler_loop(), name="task-scheduler")


# 返回当前运行中的平台任务数量。
def running_count() -> int:
    return sum(1 for ident, task in _running_jobs.items() if not task.done() and _running_queues.get(ident) != "direct")


# 调度循环是否存活。
def scheduler_status() -> str:
    if _intentionally_stopped:
        return "stopped"
    if _scheduler_task and not _scheduler_task.done():
        return "running"
    return "stopped"


# 距上次成功完成 tick 的秒数；从未 tick 时返回很大值。
def scheduler_tick_age_sec() -> float:
    if _last_tick_mono <= 0:
        return 1e9
    return max(0.0, time.monotonic() - _last_tick_mono)


# 返回最近成功调度的年龄与连续失败数；失败不能伪装成成功心跳。
def scheduler_diagnostics() -> dict[str, int | float]:
    age = time.monotonic() - _last_success_mono if _last_success_mono > 0 else 1e9
    return {
        "scheduler_success_age_sec": round(max(0.0, age), 1),
        "scheduler_consecutive_failures": _consecutive_failures,
    }


# 是否因心跳过期应视为卡死（供看门狗判断）。
def scheduler_tick_stale() -> bool:
    if _intentionally_stopped:
        return False
    stale_sec = max(15, int(get_settings().task_runtime_tick_stale_sec))
    # 重启保留真实失败记录，但给新循环一次完整执行机会，避免 watchdog 连续掐断重试。
    heartbeat = max(_last_tick_mono, _loop_started_mono)
    return time.monotonic() - heartbeat > stale_sec


# 本地是否仍持有该任务的执行协程。
def _job_alive(task_id: int) -> bool:
    job = _running_jobs.get(task_id)
    return bool(job and not job.done())


# 周期扫描到期任务并交给执行器。
async def _scheduler_loop() -> None:
    global _last_tick_mono, _last_success_mono, _consecutive_failures
    while not _stop_event.is_set():
        timeout = max(20.0, float(get_settings().task_runtime_tick_stale_sec) - 10.0)
        try:
            await asyncio.wait_for(_tick(), timeout=timeout)
        except asyncio.TimeoutError:
            _consecutive_failures += 1
            logger.error("task scheduler tick timed out after %.0fs", timeout)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _consecutive_failures += 1
            logger.exception("task scheduler tick failed")
        else:
            _last_tick_mono = time.monotonic()
            _last_success_mono = _last_tick_mono
            _consecutive_failures = 0
        await asyncio.sleep(1.0)


# 保持唯一维护协程；watchdog 只重启调度循环时复用仍存活的维护任务。
def _ensure_maintenance_loop() -> None:
    global _maintenance_task
    if _maintenance_task is None or _maintenance_task.done():
        _maintenance_task = asyncio.create_task(_maintenance_loop(), name="task-maintenance")


# 每项维护独占短事务；超时退出时由 session 上下文回滚，释放已持有的锁。
async def _run_maintenance_operation(name: str) -> None:
    from app.services.billing.wallet_cutover import runtime_state as state, sync_runtime
    async with AsyncSessionLocal() as cutover_db:
        value = await state(cutover_db)
        await sync_runtime(cutover_db, value)
        if value.get("paused") and name == "sequential_queue":
            return
    from app.services.billing.unified_ai import reconcile_refunded_task_notices
    if name == "orphan_recovery":
        await recover_orphaned_tasks()
        return
    operations = {
        "sequential_queue": reconcile_sequential_batches,
        "stale_fragments": reconcile_stale_pending_tasks,
        "billing_reconcile": reconcile_terminal_frozen_tasks,
        "wallet_refunds": reconcile_refunded_task_notices,
    }
    async with AsyncSessionLocal() as db:
        await operations[name](db)


# 低频维护与任务领取隔离，单项锁等待不得阻塞新任务和取消请求。
async def _maintenance_loop() -> None:
    while not _stop_event.is_set():
        for name in ("orphan_recovery", "sequential_queue", "stale_fragments", "billing_reconcile", "wallet_refunds"):
            try:
                await asyncio.wait_for(_run_maintenance_operation(name), timeout=_MAINTENANCE_TIMEOUT_SEC)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                logger.warning("task maintenance timed out operation=%s", name)
            except Exception:  # noqa: BLE001
                logger.exception("task maintenance failed operation=%s", name)
        interval = max(5, int(get_settings().task_runtime_orphan_check_sec))
        await asyncio.sleep(interval)


# 扫描并租约抢占可执行任务。
async def _tick() -> None:
    # A cutover revision is persisted; other API/worker processes must not keep
    # using pre-migration billing settings after maintenance is released.
    from app.services.billing.wallet_cutover import runtime_state as state, sync_runtime
    async with AsyncSessionLocal() as cutover_db:
        cutover_state = await state(cutover_db)
        await sync_runtime(cutover_db, cutover_state)
    now = datetime.now(UTC)
    for task_id, job in list(_running_jobs.items()):
        if job.done():
            _running_jobs.pop(task_id, None)
            _running_queues.pop(task_id, None)
    for task_id, job in list(_cancel_jobs.items()):
        if job.done():
            _cancel_jobs.pop(task_id, None)
    await _claim_cancel_requests()
    if cutover_state.get("paused"):
        return
    # Conversations advance from persisted, settled stage results, including after restarts.
    try:
        from app.services.creation import reconcile_creation_sessions
        async with AsyncSessionLocal() as db:
            await reconcile_creation_sessions(db)
    except Exception:
        logger.exception("creation workflow reconciliation failed")
    await _claim_direct_llm_tasks(now)

    # Each lane owns its capacity; a blocked image/video lane never blocks text.
    for queue in QUEUE_TYPES:
        await _claim_queue(queue, now)


async def _claim_queue(queue: str, now: datetime) -> None:
    capacity = queue_capacity(get_settings(), queue)
    user_limit = max(1, int(get_settings().task_user_max_concurrency))
    team_limit = max(1, int(getattr(get_settings(), "task_team_max_concurrency", 4)))
    local_active = sum(
        1 for tid, job in _running_jobs.items()
        if not job.done() and _running_queues.get(tid, "text") == queue
    )
    available_slots = max(0, capacity - local_active)
    if not available_slots:
        return

    claimed_ids: list[int] = []
    claimed_tokens: dict[int, str] = {}
    async with AsyncSessionLocal() as db:
        # Serialize claims per lane across API processes, without blocking other lanes.
        bind = getattr(db, "bind", None)
        if bind is not None and bind.dialect.name == "postgresql":
            locked = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": 842100 + QUEUE_TYPES.index(queue)})
            if not locked:
                return
        active_states = ("leased", "running", "awaiting_poll") if queue == "video" else ("leased", "running")
        occupied = int(await db.scalar(select(func.count()).select_from(TaskRun).where(
            TaskRun.queue_type == queue, TaskRun.status.in_(active_states),
            ~llm_task_condition(TaskRun),
        )) or 0)
        available_slots = min(available_slots, max(0, capacity - occupied))
        if not available_slots:
            return
        user_active_cache: dict[int, int] = {}
        team_active_cache: dict[int, int] = {}
        seen_ids: set[int] = set()
        full_users: set[int] = set()
        active = aliased(TaskRun)
        active_count = (
            select(func.count(active.id))
            .where(active.requested_by == TaskRun.requested_by, active.status.in_(active_states), active.queue_type == queue, ~llm_task_condition(active))
            .correlate(TaskRun)
            .scalar_subquery()
        )
        team_active = aliased(TaskRun)
        team_active_count = (select(func.count(team_active.id)).where(team_active.team_id == TaskRun.team_id, team_active.status.in_(("leased", "running", "awaiting_poll")), ~llm_task_condition(team_active)).correlate(TaskRun).scalar_subquery())
        for _ in range(_MAX_CLAIM_PAGES):
            remaining = available_slots - len(claimed_ids)
            if remaining <= 0:
                break
            stmt = (
                select(TaskRun.id, TaskRun.status, TaskRun.requested_by, TaskRun.team_id)
                .where(
                    TaskRun.status == "pending",
                    TaskRun.queue_type == queue,
                    ~llm_task_condition(TaskRun),
                    TaskRun.cancel_requested.is_(False),
                    TaskRun.next_action_at.is_not(None),
                    TaskRun.next_action_at <= now,
                    active_count < user_limit,
                    or_(TaskRun.team_id.is_(None), team_active_count < team_limit),
                )
                .order_by(TaskRun.priority.asc(), TaskRun.created_at.asc(), TaskRun.id.asc())
                .limit(min(_MAX_CANDIDATES_PER_PAGE, max(remaining * 4, remaining)))
                .with_for_update(skip_locked=True, of=TaskRun)
            )
            if seen_ids:
                stmt = stmt.where(TaskRun.id.not_in(sorted(seen_ids)))
            if full_users:
                stmt = stmt.where(TaskRun.requested_by.not_in(sorted(full_users)))
            candidates = list((await db.execute(stmt)).all())
            if not candidates:
                break
            for row in candidates:
                if len(claimed_ids) >= available_slots:
                    break
                task_id = int(row.id)
                seen_ids.add(task_id)
                user_id = int(row.requested_by)
                if _job_alive(task_id):
                    continue
                if user_id not in user_active_cache:
                    user_active_cache[user_id] = await count_user_active_runtime_tasks(db, user_id, queue_type=queue)
                if user_active_cache[user_id] >= user_limit:
                    full_users.add(user_id)
                    continue
                team_id = getattr(row, "team_id", None)
                if team_id is not None:
                    if bind is not None and bind.dialect.name == "postgresql":
                        team_claimed = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": 942100000 + int(team_id)})
                        if not team_claimed:
                            continue
                    if team_id not in team_active_cache:
                        team_active_cache[team_id] = int((await db.execute(select(func.count()).select_from(TaskRun).where(TaskRun.team_id == team_id, TaskRun.status.in_(("leased", "running", "awaiting_poll")), ~llm_task_condition(TaskRun)))).scalar_one() or 0)
                    if team_active_cache[team_id] >= team_limit:
                        continue
                lease_token = uuid.uuid4().hex
                result = await db.execute(
                    update(TaskRun)
                    .where(TaskRun.id == task_id, TaskRun.status == "pending", TaskRun.cancel_requested.is_(False))
                    .values(status="leased", lease_token=lease_token, lease_until=now + timedelta(minutes=10))
                )
                if int(result.rowcount or 0) != 1:
                    continue
                task = await db.get(TaskRun, task_id)
                await append_task_event(
                    db, task_id, event_type="task.leased", status="leased",
                    phase=getattr(task, "current_step_key", None), message="任务已被调度器领取",
                )
                claimed_ids.append(task_id)
                claimed_tokens[task_id] = lease_token
                user_active_cache[user_id] += 1
                if team_id is not None:
                    team_active_cache[team_id] += 1
                if user_active_cache[user_id] >= user_limit:
                    full_users.add(user_id)
        if claimed_ids:
            await db.commit()

    for task_id in claimed_ids:
        if task_id in _running_jobs and not _running_jobs[task_id].done():
            continue
        _running_queues[task_id] = queue
        _running_jobs[task_id] = asyncio.create_task(_run_one(task_id, claimed_tokens[task_id]), name=f"task-{queue}-{task_id}")


# 取消使用独立且有上限的槽位，满额用户或普通队列积压不能阻挡取消。
async def _claim_cancel_requests() -> None:
    available = max(0, _MAX_CANCEL_JOBS - len(_cancel_jobs))
    if available <= 0:
        return
    claimed: list[int] = []
    async with AsyncSessionLocal() as db:
        stmt = (
            select(TaskRun.id)
            .where(
                TaskRun.status == "cancel_requested",
                or_(TaskRun.next_action_at.is_(None), TaskRun.next_action_at <= datetime.now(UTC)),
            )
            .order_by(TaskRun.id.asc())
            .limit(available)
            .with_for_update(skip_locked=True, of=TaskRun)
        )
        if _cancel_jobs:
            stmt = stmt.where(TaskRun.id.not_in(sorted(_cancel_jobs)))
        ids = [int(item) for item in (await db.execute(stmt)).scalars().all()]
        for task_id in ids:
            if await cancel_running_task(task_id):
                continue
            claimed.append(task_id)
    for task_id in claimed:
        _cancel_jobs[task_id] = asyncio.create_task(_run_cancel_request(task_id), name=f"task-cancel-{task_id}")


# 取消路径只调用状态/结算收敛，绝不进入业务 handler 或重新提交上游。
async def _run_cancel_request(task_id: int) -> None:
    try:
        async with AsyncSessionLocal() as db:
            task = await get_task_for_runtime(db, task_id)
            if task and task.status == "cancel_requested":
                if task_finalizing_window_open(task):
                    until = datetime.fromisoformat(str(task.payload[FINALIZING_UNTIL_KEY]))
                    task.next_action_at = until if until.tzinfo else until.replace(tzinfo=UTC)
                    await db.commit()
                    return
                lease_until = getattr(task, "lease_until", None)
                if lease_until is not None and lease_until.tzinfo is None:
                    lease_until = lease_until.replace(tzinfo=UTC)
                if lease_until and lease_until > datetime.now(UTC):
                    # Any live executor may still be writing media/usage in another
                    # process. Its heartbeat observes cancel_requested and cancels
                    # the owner coroutine; only that owner may settle until expiry.
                    return
                await _mark_cancelled(db, task)
    except Exception:  # noqa: BLE001
        logger.exception("task cancellation failed task_id=%s", task_id)
    finally:
        _cancel_jobs.pop(task_id, None)


def start_direct_task(task_id: int, lease_token: str) -> None:
    """显式提交的文字任务立即启动，不占调度队列槽位；保留取消和租约。"""
    if _job_alive(task_id):
        return
    _running_queues[task_id] = "direct"
    job = asyncio.create_task(_run_one(task_id, lease_token), name=f"llm-direct-{task_id}")
    _running_jobs[task_id] = job

    def completed(result):
        """取出异常，避免后台协程异常无人处理。"""
        if not result.cancelled() and result.exception():
            logger.error("direct LLM task failed task_id=%s", task_id, exc_info=result.exception())

    job.add_done_callback(completed)


async def _claim_direct_llm_tasks(now: datetime) -> None:
    """旧版待执行任务、定时任务及中断恢复直接启动，不等待媒体容量。"""
    claimed = []
    async with AsyncSessionLocal() as db:
        rows = list((await db.execute(select(TaskRun).where(
            llm_task_condition(TaskRun, runnable_only=True), TaskRun.status == "pending",
            TaskRun.cancel_requested.is_(False), TaskRun.next_action_at.is_not(None), TaskRun.next_action_at <= now,
        ).order_by(TaskRun.id).limit(128).with_for_update(skip_locked=True))).scalars().all())
        for task in rows:
            if _job_alive(task.id):
                continue
            task.status = "running"
            task.started_at = task.started_at or now
            task.next_action_at = None
            task.lease_token = uuid.uuid4().hex
            task.lease_until = now + timedelta(minutes=10)
            claimed.append((task.id, task.lease_token))
        if claimed:
            await db.commit()
    for task_id, token in claimed:
        start_direct_task(task_id, token)


# 包装执行器并在结束后释放运行槽位。
async def _run_one(task_id: int, lease_token: str | None = None) -> None:
    heartbeat = asyncio.create_task(_renew_lease(task_id, lease_token)) if lease_token else None
    try:
        await execute_task_run(task_id)
    except asyncio.CancelledError:
        # 直接执行可能在预扣阶段被取消，此时执行器尚未进入 handler 的取消收尾。
        if _running_queues.get(task_id) == "direct":
            from app.services.tasks.executor import _requeue_interrupted_task
            async with AsyncSessionLocal() as db:
                task = await get_task_for_runtime(db, task_id)
                if task and task.status not in {"succeeded", "failed", "cancelled"}:
                    if task.cancel_requested:
                        await _mark_cancelled(db, task)
                    else:
                        await _requeue_interrupted_task(db, task)
        raise
    finally:
        if heartbeat:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        _running_jobs.pop(task_id, None)
        _running_queues.pop(task_id, None)


async def _renew_lease(task_id: int, lease_token: str) -> None:
    while True:
        await asyncio.sleep(10)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(update(TaskRun).where(
                    TaskRun.id == task_id, TaskRun.lease_token == lease_token,
                    TaskRun.status.in_(("leased", "running")),
                ).values(lease_until=datetime.now(UTC) + timedelta(minutes=10)))
                await db.commit()
                if not result.rowcount:
                    cancelled = await db.scalar(select(TaskRun.cancel_requested).where(
                        TaskRun.id == task_id, TaskRun.lease_token == lease_token,
                    ))
                    if cancelled:
                        await cancel_running_task(task_id)
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("task lease heartbeat failed task_id=%s", task_id)


# 取消指定任务的本地执行协程。
async def cancel_running_task(task_id: int) -> bool:
    task = _running_jobs.get(task_id)
    if not task or task.done():
        return False
    task.cancel()
    return True


# 把僵死的 leased/running 放回队列；跳过本进程仍持有协程的任务。
async def recover_orphaned_tasks() -> int:
    now = datetime.now(UTC)
    grace_sec = max(5, int(get_settings().task_runtime_recover_grace_sec))
    stale_before = now - timedelta(seconds=grace_sec)
    async with AsyncSessionLocal() as db:
        stmt = select(TaskRun).where(
            or_(
                and_(
                    TaskRun.status == "leased",
                    or_(
                        and_(TaskRun.lease_until.is_(None), TaskRun.updated_at < stale_before),
                        and_(TaskRun.lease_until.is_not(None), TaskRun.lease_until < now),
                    ),
                ),
                and_(
                    TaskRun.status == "running",
                    TaskRun.updated_at.is_not(None),
                    TaskRun.updated_at < stale_before,
                    or_(TaskRun.lease_until.is_(None), TaskRun.lease_until < now),
                ),
            )
        )
        rows = list((await db.execute(stmt.with_for_update(skip_locked=True))).scalars().all())
        changed = 0
        for task in rows:
            if _job_alive(int(task.id)):
                continue
            from app.services.tasks.inline import INLINE_LEASE_PREFIX
            if str(task.lease_token or "").startswith(INLINE_LEASE_PREFIX):
                # HTTP inline executors have no replayable job. A restarted
                # process must not queue their noop handler or resubmit a POST.
                from app.services.billing.settlement import settle_task
                task.status = "cancelled" if task.cancel_requested else "failed"
                task.error_code = "inline_execution_interrupted"
                task.error_message = "生成请求执行中断，请重新发起"
                task.finished_at = now
                task.next_action_at = None
                task.lease_token = None
                task.lease_until = None
                await append_task_event(
                    db, task.id, event_type=f"task.{task.status}", status=task.status,
                    phase=task.current_step_key, message=task.error_message,
                )
                if task.billing_status in {"frozen", "reserved"}:
                    await settle_task(db, task.id)
                changed += 1
                continue
            task.status = "cancel_requested" if task.cancel_requested else "pending"
            task.next_action_at = now
            task.lease_token = None
            task.lease_until = None
            await append_task_event(
                db,
                task.id,
                event_type="task.recovered",
                status=task.status,
                phase=task.current_step_key,
                message="检测到任务执行中断或租约过期，已重新排队",
            )
            changed += 1
        if changed:
            await db.commit()
            logger.warning("recovered orphaned task runs count=%s", changed)
        return changed
