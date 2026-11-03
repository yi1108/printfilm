"""媒体生命周期测试不连接 OSS，不启动真实转码。"""
import asyncio
import sys

import pytest

from app.marketplace import runtime
from app.config import get_settings


def test_media_tools_fall_back_to_environment_paths(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import config
    from app.marketplace import worker
    executable = tmp_path / 'ffprobe.exe'
    executable.touch()
    monkeypatch.setattr(worker.shutil, 'which', lambda value: None)
    monkeypatch.setattr(config, 'Settings', lambda: SimpleNamespace(ffprobe_path=str(executable)))
    assert worker.resolve_tool('ffprobe') == str(executable)
    explicit = str(tmp_path / 'custom.exe')
    assert worker.resolve_tool(explicit) == explicit


async def test_media_command_selector_loop_fallback(monkeypatch):
    from app.marketplace import worker
    async def unsupported(*args, **kwargs):
        raise NotImplementedError
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', unsupported)
    output = await worker.command(sys.executable, '-c', 'print("selector-compatible")', timeout=10)
    assert output.strip() == b'selector-compatible'


async def test_media_thread_command_timeout_and_cancellation(monkeypatch):
    from app.marketplace import worker
    original = worker.subprocess.Popen
    processes = []
    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(worker.subprocess, 'Popen', capture)
    args = (sys.executable, '-c', 'import time; time.sleep(10)')
    with pytest.raises(TimeoutError):
        await worker.threaded_command(args, .1)
    assert processes[-1].poll() is not None
    task = asyncio.create_task(worker.threaded_command(args, 20))
    while len(processes) < 2:
        await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[-1].poll() is not None


async def test_market_runtime_disabled_does_not_start(monkeypatch):
    monkeypatch.setattr(get_settings(), "marketplace_enabled", False)
    await runtime.start_marketplace_runtime()
    assert runtime._watchdog is None and runtime._worker is None


async def test_market_runtime_idempotent_and_clean_shutdown(monkeypatch):
    monkeypatch.setattr(get_settings(), "marketplace_enabled", True)
    started, stopped = asyncio.Event(), asyncio.Event()
    async def loop():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    monkeypatch.setattr(runtime, "run_loop", loop)
    try:
        await runtime.start_marketplace_runtime()
        await asyncio.wait_for(started.wait(), 1)
        original = runtime._worker
        await runtime.start_marketplace_runtime()
        assert runtime._worker is original
    finally:
        await runtime.stop_marketplace_runtime()
    assert stopped.is_set()
    assert runtime._worker is None and runtime._watchdog is None
    await runtime.stop_marketplace_runtime()


@pytest.mark.parametrize("cancelled", [False, True])
async def test_market_runtime_recovers_failed_or_cancelled_loop(monkeypatch, cancelled):
    monkeypatch.setattr(get_settings(), "marketplace_enabled", True)
    started, restarted = asyncio.Event(), asyncio.Event()
    calls = 0
    async def loop():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            if cancelled:
                raise asyncio.CancelledError
            raise RuntimeError("test unexpected exit")
        restarted.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(runtime, "run_loop", loop)
    try:
        await runtime.start_marketplace_runtime()
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(restarted.wait(), 4)
        assert calls == 2 and not runtime._worker.done()
    finally:
        await runtime.stop_marketplace_runtime()


def test_regular_market_tables_exclude_registered_app_financial_models():
    """注册App路由后，普通市场初始化也不能顺带创建观影币及Apple财务表。"""
    from app.marketplace.app_schema import legacy_marketplace_tables, register_models
    from app.marketplace.models import MarketBase
    app_tables, legacy_tables = set(register_models()), set(legacy_marketplace_tables())
    assert app_tables and legacy_tables
    assert not app_tables.intersection(legacy_tables)
    assert app_tables | legacy_tables == set(MarketBase.metadata.tables.values())
    assert {table.name for table in legacy_tables}.issuperset({"marketplace_assets", "marketplace_publications"})
    assert {table.name for table in app_tables}.issuperset({"marketplace_app_media", "marketplace_apple_transactions"})


@pytest.mark.parametrize("opened,ready", [(False, False), (False, True), (True, False), (True, True)])
async def test_app_media_only_runs_after_open_and_schema_checks(monkeypatch, opened, ready):
    """默认关闭不检查App表；开启但未迁移也不领取任务，不影响既有媒体循环。"""
    from app.marketplace import app_access, app_bootstrap, app_media, worker
    calls = []

    async def schema_ready():
        calls.append("schema")
        return ready

    async def media_once():
        calls.append("media")
        return True

    monkeypatch.setattr(app_access, "app_open", lambda: opened)
    monkeypatch.setattr(app_bootstrap, "schema_ready", schema_ready)
    monkeypatch.setattr(app_media, "run_app_media_once", media_once)
    assert await worker.run_app_media_if_ready() is (opened and ready)
    assert calls == (["schema", "media"] if opened and ready else ["schema"] if opened else [])


async def test_app_media_runs_after_existing_jobs_under_same_market_lock(monkeypatch):
    """App封装沿用市场共享锁，原有任务执行顺序和入口保持不变。"""
    from types import SimpleNamespace
    from app.marketplace import handoff, preview_worker, worker
    calls = []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            calls.append("unlock")
            return False

        async def scalar(self, statement):
            assert "pg_try_advisory_xact_lock" in str(statement)
            calls.append("lock")
            return True

    def task(name):
        """以记录调用替身隔离数据库、OSS和编码子进程。"""
        async def run():
            calls.append(name)
        return run

    async def finish(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "is_marketplace_enabled", lambda: True)
    monkeypatch.setattr(worker.storage, "configured", lambda: True)
    monkeypatch.setattr(worker.storage, "bucket", lambda: calls.append("bucket"))
    monkeypatch.setattr(worker, "engine", SimpleNamespace(begin=lambda: Connection()))
    monkeypatch.setattr(worker, "maintenance", task("maintenance"))
    monkeypatch.setattr(preview_worker, "run_episode_preview_once", task("episode_preview"))
    monkeypatch.setattr(preview_worker, "run_preview_once", task("preview"))
    monkeypatch.setattr(preview_worker, "release_finished_series_once", task("release"))
    monkeypatch.setattr(handoff, "run_handoff_once", task("handoff"))
    monkeypatch.setattr(worker, "run_once", task("asset"))
    monkeypatch.setattr(worker, "package_publication_once", task("publication"))
    monkeypatch.setattr(worker, "run_app_media_if_ready", task("app_media"))
    monkeypatch.setattr(worker.asyncio, "sleep", finish)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_loop()
    assert calls == ["lock", "bucket", "maintenance", "episode_preview", "preview", "release",
                     "handoff", "asset", "publication", "app_media", "unlock"]
