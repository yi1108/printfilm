"""Lifecycle helpers for the in-process task runtime."""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.tasks.poller import (
    poller_status,
    poller_tick_age_sec,
    poller_tick_stale,
    restart_poller_loop,
    start_poller,
    stop_poller,
)
from app.services.tasks.scheduler import (
    restart_scheduler_loop,
    running_count,
    scheduler_status,
    scheduler_tick_age_sec,
    scheduler_tick_stale,
    start_scheduler,
    stop_scheduler,
)

logger = logging.getLogger("app.tasks.runtime")

_watchdog_task: asyncio.Task | None = None
_watchdog_stop = asyncio.Event()
_watchdog_intentionally_stopped: bool = True


# 启动统一任务平台运行时（Worker 调度 + Selector 轮询 + 看门狗）。
async def start_task_runtime() -> None:
    await start_scheduler()
    await start_poller()
    await start_watchdog()


# 停止统一任务平台运行时。
async def stop_task_runtime() -> None:
    await stop_watchdog()
    await stop_poller()
    await stop_scheduler()


# 启动看门狗：调度/轮询循环退出或心跳过期时自动拉起。
async def start_watchdog() -> None:
    global _watchdog_task, _watchdog_intentionally_stopped
    if _watchdog_task and not _watchdog_task.done():
        return
    _watchdog_intentionally_stopped = False
    _watchdog_stop.clear()
    _watchdog_task = asyncio.create_task(_watchdog_loop(), name="task-runtime-watchdog")


# 停止看门狗。
async def stop_watchdog() -> None:
    global _watchdog_intentionally_stopped
    _watchdog_intentionally_stopped = True
    _watchdog_stop.set()
    if _watchdog_task and not _watchdog_task.done():
        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except asyncio.CancelledError:
            pass


# 看门狗状态。
def watchdog_status() -> str:
    if _watchdog_intentionally_stopped:
        return "stopped"
    if _watchdog_task and not _watchdog_task.done():
        return "running"
    return "stopped"


# 周期检查调度器与 Selector 存活，必要时软重启。
async def _watchdog_loop() -> None:
    while not _watchdog_stop.is_set():
        try:
            await _watchdog_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("task runtime watchdog failed")
        interval = max(2.0, float(get_settings().task_runtime_watchdog_interval_sec))
        await asyncio.sleep(interval)


# 单次看门狗检查。
async def _watchdog_once() -> None:
    if scheduler_status() != "running" or scheduler_tick_stale():
        reason = "dead" if scheduler_status() != "running" else "tick_stale"
        await restart_scheduler_loop(reason=f"watchdog:{reason}")
    if poller_status() != "running" or poller_tick_stale():
        reason = "dead" if poller_status() != "running" else "tick_stale"
        await restart_poller_loop(reason=f"watchdog:{reason}")


# 返回任务平台运行时摘要（槽位 + 循环存活 + 心跳年龄）。
def runtime_summary() -> dict[str, int | str | float | bool]:
    sched = scheduler_status()
    poll = poller_status()
    dog = watchdog_status()
    healthy = sched == "running" and poll == "running" and dog == "running"
    return {
        "healthy": healthy,
        "scheduler": sched,
        "scheduler_running_jobs": running_count(),
        "scheduler_tick_age_sec": round(scheduler_tick_age_sec(), 1),
        "poller": poll,
        "poller_tick_age_sec": round(poller_tick_age_sec(), 1),
        "watchdog": dog,
    }
