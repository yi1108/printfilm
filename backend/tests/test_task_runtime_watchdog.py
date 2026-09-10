"""Tests for task runtime watchdog, heartbeat, and orphan recovery guards."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tasks import poller as poller_mod
from app.services.tasks import runtime as runtime_mod
from app.services.tasks import scheduler as scheduler_mod


@pytest.fixture(autouse=True)
async def _reset_runtime_state():
    """每个用例前后停掉调度/轮询/看门狗，避免泄漏协程。"""
    await runtime_mod.stop_task_runtime()
    scheduler_mod._running_jobs.clear()
    poller_mod._poll_inflight.clear()
    yield
    await runtime_mod.stop_task_runtime()
    scheduler_mod._running_jobs.clear()
    poller_mod._poll_inflight.clear()


@pytest.mark.asyncio
async def test_scheduler_status_and_heartbeat():
    """启动后调度状态为 running，心跳年龄应接近 0。"""
    with (
        patch.object(scheduler_mod, "recover_orphaned_tasks", new=AsyncMock(return_value=0)),
        patch.object(scheduler_mod, "_tick", new=AsyncMock()),
    ):
        await scheduler_mod.start_scheduler()
        assert scheduler_mod.scheduler_status() == "running"
        assert scheduler_mod.scheduler_tick_age_sec() < 5
        assert not scheduler_mod.scheduler_tick_stale()
        await scheduler_mod.stop_scheduler()
        assert scheduler_mod.scheduler_status() == "stopped"


@pytest.mark.asyncio
async def test_watchdog_restarts_dead_scheduler():
    """调度循环退出后，看门狗应重新拉起。"""
    with (
        patch.object(scheduler_mod, "recover_orphaned_tasks", new=AsyncMock(return_value=0)),
        patch.object(scheduler_mod, "_tick", new=AsyncMock()),
        patch.object(poller_mod, "_select_and_poll_due", new=AsyncMock()),
        patch.object(poller_mod, "_poll_ephemeral_deferred_tasks", new=AsyncMock()),
        patch(
            "app.services.tasks.runtime.get_settings",
            return_value=SimpleNamespace(task_runtime_watchdog_interval_sec=0.05),
        ),
    ):
        await runtime_mod.start_task_runtime()
        first = scheduler_mod._scheduler_task
        assert first is not None and not first.done()
        # 人为结束调度循环（不走 stop，模拟异常退出）
        scheduler_mod._intentionally_stopped = False
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass
        for _ in range(40):
            current = scheduler_mod._scheduler_task
            if (
                scheduler_mod.scheduler_status() == "running"
                and current is not None
                and current is not first
                and not current.done()
            ):
                break
            await asyncio.sleep(0.05)
        current = scheduler_mod._scheduler_task
        assert scheduler_mod.scheduler_status() == "running"
        assert current is not None and current is not first
        assert runtime_mod.runtime_summary()["healthy"] is True


@pytest.mark.asyncio
async def test_recover_skips_local_alive_jobs():
    """本进程仍持有执行协程的 running 任务不应被孤儿恢复改写。"""
    alive = asyncio.create_task(asyncio.sleep(60))
    scheduler_mod._running_jobs[42] = alive

    fake_task = SimpleNamespace(
        id=42,
        status="running",
        cancel_requested=False,
        current_step_key="step",
        next_action_at=None,
        lease_token="x",
        lease_until=None,
    )

    class _FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [fake_task]

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *_args, **_kwargs):
            return _FakeResult()

        async def commit(self):
            return None

    with (
        patch.object(scheduler_mod, "AsyncSessionLocal", return_value=_FakeSession()),
        patch.object(scheduler_mod, "reconcile_sequential_batches", new=AsyncMock()),
        patch.object(scheduler_mod, "reconcile_stale_pending_tasks", new=AsyncMock()),
        patch.object(scheduler_mod, "append_task_event", new=AsyncMock()),
        patch(
            "app.services.tasks.scheduler.get_settings",
            return_value=SimpleNamespace(task_runtime_recover_grace_sec=1),
        ),
    ):
        changed = await scheduler_mod.recover_orphaned_tasks()
        assert changed == 0
        assert fake_task.status == "running"

    alive.cancel()
    with pytest.raises(asyncio.CancelledError):
        await alive


@pytest.mark.asyncio
async def test_runtime_summary_reports_components():
    """runtime_summary 应暴露 scheduler/poller/watchdog 与 healthy。"""
    with (
        patch.object(scheduler_mod, "recover_orphaned_tasks", new=AsyncMock(return_value=0)),
        patch.object(scheduler_mod, "_tick", new=AsyncMock()),
        patch.object(poller_mod, "_select_and_poll_due", new=AsyncMock()),
        patch.object(poller_mod, "_poll_ephemeral_deferred_tasks", new=AsyncMock()),
    ):
        await runtime_mod.start_task_runtime()
        summary = runtime_mod.runtime_summary()
        assert summary["scheduler"] == "running"
        assert summary["poller"] == "running"
        assert summary["watchdog"] == "running"
        assert summary["healthy"] is True
        assert "scheduler_tick_age_sec" in summary
