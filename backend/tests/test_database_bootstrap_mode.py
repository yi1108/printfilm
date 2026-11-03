"""Existing shared DB mode: offline tests with isolated, fully mocked startup."""

import ast
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import app.services
from app.config import Settings
from app.startup_database_retry import run_database_startup_steps


def test_bootstrap_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("DATABASE_BOOTSTRAP_ENABLED", raising=False)
    assert Settings(_env_file=None).database_bootstrap_enabled is True


def test_bootstrap_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("DATABASE_BOOTSTRAP_ENABLED", "false")
    assert Settings(_env_file=None).database_bootstrap_enabled is False


def _isolated_startup(monkeypatch, bootstrap_enabled):
    # Compile only this function with mocked globals. Importing app.main would
    # construct the real app and engine, which this offline regression avoids.
    path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    startup = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_startup")
    startup.decorator_list = []
    callbacks = {
        name: AsyncMock(name=name)
        for name in (
            "init_db", "_apply_schema_patches", "_load_startup_model_settings",
            "seed_templates", "bootstrap_admins", "seed_agent_skills", "start_task_runtime",
            "start_app_services", "apply_marketplace_switch",
        )
    }
    oss = ModuleType("app.services.oss")
    oss.ensure_browser_cors = Mock()
    monkeypatch.setattr(app.services, "oss", oss, raising=False)
    from app.marketplace import app_bootstrap, bootstrap
    monkeypatch.setattr(app_bootstrap, "start_app_services", callbacks["start_app_services"])
    monkeypatch.setattr(bootstrap, "apply_marketplace_switch", callbacks["apply_marketplace_switch"])
    globals_ = {
        **callbacks,
        "settings": SimpleNamespace(database_bootstrap_enabled=bootstrap_enabled),
        "engine": SimpleNamespace(dispose=AsyncMock()),
        "logger": Mock(),
        "run_database_startup_steps": run_database_startup_steps,
    }
    exec(compile(ast.Module(body=[startup], type_ignores=[]), str(path), "exec"), globals_)
    return globals_["on_startup"], callbacks, oss


@pytest.mark.parametrize("enabled", [True, False])
async def test_mode_controls_mutations_but_always_loads_cache_and_starts_runtime(monkeypatch, enabled):
    startup, callbacks, oss = _isolated_startup(monkeypatch, enabled)
    await startup()

    callbacks["_load_startup_model_settings"].assert_awaited_once()
    callbacks["start_task_runtime"].assert_awaited_once()
    callbacks["start_app_services"].assert_awaited_once()
    callbacks["apply_marketplace_switch"].assert_awaited_once()
    oss.ensure_browser_cors.assert_called_once()
    for name in ("init_db", "_apply_schema_patches", "seed_templates", "bootstrap_admins", "seed_agent_skills"):
        assert callbacks[name].await_count == int(enabled), name


async def test_existing_database_mode_still_propagates_model_cache_failures(monkeypatch):
    startup, callbacks, oss = _isolated_startup(monkeypatch, False)
    original = RuntimeError("missing model settings table")
    callbacks["_load_startup_model_settings"].side_effect = original
    with pytest.raises(RuntimeError) as caught:
        await startup()
    assert caught.value is original
    callbacks["start_task_runtime"].assert_not_awaited()
    oss.ensure_browser_cors.assert_not_called()


async def test_missing_enabled_app_schema_stops_before_starting_workers(monkeypatch):
    """App迁移检查失败时不启动AI与市场循环，不执行任何真实启动操作。"""
    startup, callbacks, _oss = _isolated_startup(monkeypatch, False)
    callbacks["start_app_services"].side_effect = RuntimeError("App数据库结构未准备")
    with pytest.raises(RuntimeError, match="App数据库结构未准备"):
        await startup()
    callbacks["start_task_runtime"].assert_not_awaited()
    callbacks["apply_marketplace_switch"].assert_not_awaited()
