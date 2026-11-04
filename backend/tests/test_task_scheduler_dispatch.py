"""调度维护隔离、成功心跳、公平领取与取消路径；全部使用内存替身。"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Update

from app.services.tasks import scheduler


@pytest.fixture(autouse=True)
async def isolated_scheduler(monkeypatch):
    """隔离进程内调度状态，并在退出时清理所有后台协程。"""
    monkeypatch.setattr(scheduler, "_scheduler_task", None)
    monkeypatch.setattr(scheduler, "_maintenance_task", None)
    monkeypatch.setattr(scheduler, "_running_jobs", {})
    monkeypatch.setattr(scheduler, "_running_queues", {})
    monkeypatch.setattr(scheduler, "_cancel_jobs", {})
    monkeypatch.setattr(scheduler, "_stop_event", asyncio.Event())
    monkeypatch.setattr(scheduler, "_intentionally_stopped", False)
    monkeypatch.setattr(scheduler, "_loop_started_mono", 0.0)
    monkeypatch.setattr(scheduler, "_claim_direct_llm_tasks", AsyncMock())
    monkeypatch.setattr(scheduler, "get_settings", lambda: SimpleNamespace(
        task_runtime_max_concurrency=4,
        task_user_max_concurrency=1,
        task_runtime_tick_stale_sec=60,
        task_runtime_orphan_check_sec=30,
    ))
    yield
    await scheduler.stop_scheduler()


class _Rows:
    """模拟查询结果，避免触发真实数据库。"""

    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        """兼容单列查询。"""
        return self

    def all(self):
        """返回预设查询行。"""
        return self.rows


class _QueueSession:
    """按页返回候选任务，记录领取 SQL 和成功领取的 ID。"""

    def __init__(self, pages, *, rowcount=1):
        self.pages = list(pages)
        self.rowcount = rowcount
        self.selects = []
        self.claimed = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def __aenter__(self):
        """进入内存事务。"""
        return self

    async def __aexit__(self, *_args):
        """无需提交真实资源。"""
        return False

    async def scalar(self, _statement, _params=None):
        """No pre-existing tasks occupy the per-lane database capacity."""
        return 0

    async def execute(self, statement):
        """模拟领取 CAS 与有上限的候选查询。"""
        if isinstance(statement, Update):
            return SimpleNamespace(rowcount=self.rowcount)
        self.selects.append(statement)
        return _Rows(self.pages.pop(0) if self.pages else [])

    async def get(self, _model, task_id):
        """记录领取成功的任务。"""
        self.claimed.append(task_id)
        return SimpleNamespace(current_step_key="submit")

    async def commit(self):
        """模拟短事务提交。"""
        return None


@pytest.mark.asyncio
async def test_claim_pages_past_user_filled_by_this_tick(monkeypatch):
    """本轮第一名用户占满后，应继续领取后页其他用户，而非闲置槽位。"""
    first_page = [SimpleNamespace(id=i, status="pending", requested_by=1) for i in range(1, 17)]
    other_user = SimpleNamespace(id=17, status="pending", requested_by=2)
    db = _QueueSession([first_page, [other_user], []])
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(scheduler, "_claim_cancel_requests", AsyncMock())
    monkeypatch.setattr(scheduler, "count_user_active_runtime_tasks", AsyncMock(return_value=0))
    monkeypatch.setattr(scheduler, "append_task_event", AsyncMock())
    monkeypatch.setattr(scheduler, "_run_one", AsyncMock())
    await scheduler._claim_queue("text", datetime.now(UTC))
    assert db.claimed == [1, 17]
    sql = str(db.selects[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "count(" in sql and "requested_by" in sql
    assert "FOR UPDATE OF task_runs SKIP LOCKED" in sql
    assert "task_runs.priority ASC, task_runs.created_at ASC, task_runs.id ASC" in sql
    next_sql = str(db.selects[1].compile(compile_kwargs={"literal_binds": True}))
    assert "requested_by NOT IN (1)" in next_sql


@pytest.mark.asyncio
async def test_failed_compare_and_swap_never_launches_executor(monkeypatch):
    """并发领取失手时不能重复执行；候选扫描有固定页数上限。"""
    pages = [[SimpleNamespace(id=i, status="pending", requested_by=i)] for i in range(1, 20)]
    db = _QueueSession(pages, rowcount=0)
    executor = AsyncMock()
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(scheduler, "_claim_cancel_requests", AsyncMock())
    monkeypatch.setattr(scheduler, "count_user_active_runtime_tasks", AsyncMock(return_value=0))
    monkeypatch.setattr(scheduler, "_run_one", executor)
    await scheduler._claim_queue("text", datetime.now(UTC))
    assert len(db.selects) == scheduler._MAX_CLAIM_PAGES
    assert db.claimed == []
    executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_runs_when_normal_capacity_is_full(monkeypatch):
    """取消独立于普通容量，并且只执行取消收敛，不进入业务 handler。"""
    active = asyncio.create_task(asyncio.Event().wait())
    scheduler._running_jobs.update({i: active for i in range(100, 112)})
    scheduler._running_queues.update({i: ("text", "image", "video")[(i - 100) // 4] for i in range(100, 112)})
    db = _QueueSession([[9]])
    cancelled = AsyncMock()
    business = AsyncMock()
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(scheduler, "get_task_for_runtime", AsyncMock(return_value=SimpleNamespace(status="cancel_requested")))
    monkeypatch.setattr(scheduler, "_mark_cancelled", cancelled)
    monkeypatch.setattr(scheduler, "execute_task_run", business)
    await scheduler._tick()
    await asyncio.sleep(0)
    cancelled.assert_awaited_once()
    business.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalizing_cancellation_waits_until_its_existing_deadline(monkeypatch):
    """收尾认领内的取消等待既有期限，不每秒重复领取或提前退款。"""
    until = datetime.now(UTC) + timedelta(minutes=5)
    task = SimpleNamespace(status="cancel_requested", payload={"finalizing_until": until.isoformat()})
    db = _QueueSession([])
    cancelled = AsyncMock()
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(scheduler, "get_task_for_runtime", AsyncMock(return_value=task))
    monkeypatch.setattr(scheduler, "_mark_cancelled", cancelled)
    await scheduler._run_cancel_request(9)
    assert task.next_action_at == until
    cancelled.assert_not_awaited()


@pytest.mark.asyncio
async def test_timed_out_tick_does_not_refresh_success_heartbeat(monkeypatch):
    """反复超时不能伪装成正常心跳，看门狗必须可识别老化。"""
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(scheduler, "_last_tick_mono", 10.0)
    monkeypatch.setattr(scheduler, "_last_success_mono", 10.0)
    monkeypatch.setattr(scheduler, "_consecutive_failures", 0)
    monkeypatch.setattr(scheduler, "_tick", AsyncMock(side_effect=asyncio.TimeoutError()))

    async def stop_after_tick(_seconds):
        """一轮后退出，不等待真实定时器。"""
        scheduler._stop_event.set()

    monkeypatch.setattr(scheduler.asyncio, "sleep", stop_after_tick)
    await scheduler._scheduler_loop()
    assert scheduler.scheduler_tick_age_sec() == 90
    assert scheduler.scheduler_tick_stale()
    assert scheduler.scheduler_diagnostics() == {
        "scheduler_success_age_sec": 90.0, "scheduler_consecutive_failures": 1,
    }


@pytest.mark.asyncio
async def test_successful_tick_resets_failure_count(monkeypatch):
    """调度恢复后清除失败计数并记录真实成功时间。"""
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(scheduler, "_consecutive_failures", 3)
    monkeypatch.setattr(scheduler, "_tick", AsyncMock())

    async def stop_after_tick(_seconds):
        """一轮后退出。"""
        scheduler._stop_event.set()

    monkeypatch.setattr(scheduler.asyncio, "sleep", stop_after_tick)
    await scheduler._scheduler_loop()
    assert scheduler.scheduler_diagnostics() == {
        "scheduler_success_age_sec": 0.0, "scheduler_consecutive_failures": 0,
    }


@pytest.mark.asyncio
async def test_one_blocked_maintenance_operation_does_not_skip_others(monkeypatch):
    """单项维护超时后继续其他维护，不永久卡在第一项。"""
    visited = []

    async def operation(name):
        """首项模拟锁等待，其余直接完成。"""
        visited.append(name)
        if name == "orphan_recovery":
            await asyncio.Event().wait()
        if name == "billing_reconcile":
            scheduler._stop_event.set()

    monkeypatch.setattr(scheduler, "_run_maintenance_operation", operation)
    monkeypatch.setattr(scheduler, "_MAINTENANCE_TIMEOUT_SEC", 0.001)
    monkeypatch.setattr(scheduler.asyncio, "sleep", AsyncMock())
    await scheduler._maintenance_loop()
    assert visited == ["orphan_recovery", "sequential_queue", "stale_fragments", "billing_reconcile", "wallet_refunds"]


@pytest.mark.asyncio
async def test_restart_reuses_maintenance_and_stop_cleans_it_up(monkeypatch):
    """维护阻塞不挡住调度；watchdog 重启不复制维护，停机必须结束它。"""
    dispatched = asyncio.Event()
    maintenance_entered = asyncio.Event()

    async def blocked_maintenance(_name):
        """模拟维护持锁等待。"""
        maintenance_entered.set()
        await asyncio.Event().wait()

    async def dispatch():
        """模拟成功领取，证明维护没有挡在调度前面。"""
        dispatched.set()

    monkeypatch.setattr(scheduler, "_run_maintenance_operation", blocked_maintenance)
    monkeypatch.setattr(scheduler, "_tick", dispatch)
    await scheduler.start_scheduler()
    await asyncio.wait_for(maintenance_entered.wait(), timeout=1)
    await asyncio.wait_for(dispatched.wait(), timeout=1)
    maintenance = scheduler._maintenance_task
    await scheduler.restart_scheduler_loop(reason="test")
    assert scheduler._maintenance_task is maintenance
    assert not maintenance.done()
    await scheduler.stop_scheduler()
    assert maintenance.done()


def test_watchdog_restart_grace_does_not_erase_failure_diagnostics(monkeypatch):
    """重启宽限只防止反复中断重试，不能把成功时间或失败计数清零。"""
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(scheduler, "_last_tick_mono", 10.0)
    monkeypatch.setattr(scheduler, "_last_success_mono", 10.0)
    monkeypatch.setattr(scheduler, "_loop_started_mono", 99.0)
    monkeypatch.setattr(scheduler, "_consecutive_failures", 3)
    assert not scheduler.scheduler_tick_stale()
    assert scheduler.scheduler_diagnostics() == {
        "scheduler_success_age_sec": 90.0, "scheduler_consecutive_failures": 3,
    }
