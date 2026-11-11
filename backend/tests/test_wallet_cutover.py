"""Cutover failure boundaries; no connection to a real financial database."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.billing import wallet_cutover as cutover


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"ready": 1}, {"blocked": 1}, {"opening": 1}, {"active_tasks": True}, {"missing_schema": ["wallet_accounts"]},
])
async def test_switch_refuses_incomplete_reconciliation(monkeypatch, changes):
    result = dict(ready=0, blocked=0, active_tasks=False, missing_schema=[])
    result.update(changes)
    monkeypatch.setattr(cutover, "report", AsyncMock(return_value=result))
    with pytest.raises(ValueError, match="尚未完成核对"):
        await cutover.validate_activation(object(), "Production")


@pytest.mark.asyncio
async def test_switch_accepts_fully_reconciled_report(monkeypatch):
    monkeypatch.setattr(cutover, "report", AsyncMock(return_value={
        "ready": 0, "blocked": 0, "active_tasks": False, "missing_schema": []}))
    await cutover.validate_activation(object(), "Production")


@pytest.mark.asyncio
async def test_repeated_apply_does_not_backup_or_credit_again(monkeypatch):
    value = {"paused": True, "job_id": "a" * 32, "phase": "completed"}
    monkeypatch.setattr(cutover, "exclusive", AsyncMock())
    monkeypatch.setattr(cutover, "state", AsyncMock(return_value=value))
    backup = AsyncMock()
    monkeypatch.setattr(cutover, "backup", backup)
    assert await cutover.apply(object(), value["job_id"], 1, "retry") == value
    backup.assert_not_awaited()
    with pytest.raises(ValueError, match="编号已变化"):
        await cutover.apply(object(), "b" * 32, 1, "stale")


class MigrationDB:
    def __init__(self):
        self.statements = []
        self.commit = AsyncMock()
        self.flush = AsyncMock()

    async def execute(self, sql, *_args):
        self.statements.append(str(sql))

    async def connection(self):
        return SimpleNamespace(run_sync=AsyncMock(return_value={"users", "orders", "wallet_ledger", "app_settings"}))


@pytest.fixture
def migration(monkeypatch):
    db = MigrationDB()
    state = {"paused": True, "phase": "paused", "job_id": "a" * 32}
    monkeypatch.setattr(cutover, "exclusive", AsyncMock())
    monkeypatch.setattr(cutover, "state", AsyncMock(return_value=dict(state)))
    monkeypatch.setattr(cutover, "report", AsyncMock(return_value={"missing_schema": [], "blocked": 0, "active_tasks": False}))
    monkeypatch.setattr(cutover, "assert_no_active_tasks", AsyncMock())
    monkeypatch.setattr(cutover, "get_settings", lambda: SimpleNamespace(wallet_environment="Production"))
    monkeypatch.setattr(cutover, "sync_runtime", AsyncMock())
    monkeypatch.setattr(cutover, "configured_flat", AsyncMock(return_value={"wallet_environment": "Production"}))
    return db, state


@pytest.mark.asyncio
async def test_backup_failure_prevents_any_financial_migration(monkeypatch, migration):
    db, state = migration
    monkeypatch.setattr(cutover, "backup", AsyncMock(side_effect=ValueError("备份失败")))
    apply = AsyncMock()
    monkeypatch.setattr(cutover, "apply_plans", apply)
    with pytest.raises(ValueError, match="备份失败"):
        await cutover.apply(db, state["job_id"], 1, "test")
    apply.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert "LOCK TABLE task_runs IN SHARE MODE" in db.statements


@pytest.mark.asyncio
async def test_locked_recheck_blocks_changed_balances(monkeypatch, migration):
    db, state = migration
    monkeypatch.setattr(cutover, "backup", AsyncMock(return_value="digest"))
    monkeypatch.setattr(cutover, "build_report", AsyncMock(return_value=([{"status": "blocked"}], [])))
    apply = AsyncMock()
    monkeypatch.setattr(cutover, "apply_plans", apply)
    with pytest.raises(ValueError, match="锁内重新核对"):
        await cutover.apply(db, state["job_id"], 1, "test")
    apply.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_migration_enables_wallet_but_keeps_maintenance(monkeypatch, migration):
    from app.services import model_settings
    db, state = migration
    row = SimpleNamespace(config_json={"flat": {"unified_wallet_enabled": False}})
    monkeypatch.setattr(cutover, "backup", AsyncMock(return_value="digest"))
    monkeypatch.setattr(cutover, "build_report", AsyncMock(return_value=([{"status": "ready"}], ["plan"])))
    apply = AsyncMock()
    monkeypatch.setattr(cutover, "apply_plans", apply)
    monkeypatch.setattr(cutover, "validate_activation", AsyncMock())
    save = AsyncMock()
    monkeypatch.setattr(cutover, "save_state", save)
    monkeypatch.setattr(model_settings, "_get_or_create_app_row", AsyncMock(return_value=row))
    monkeypatch.setattr(model_settings, "_decrypt_flat_config", lambda config: config["flat"])
    monkeypatch.setattr(model_settings, "_encrypt_flat_config", lambda flat: flat)
    monkeypatch.setattr(model_settings, "_effective_flat", lambda flat: flat)
    result = await cutover.apply(db, state["job_id"], 5, "verified backup")
    assert result["paused"] and result["phase"] == "completed"
    assert result["migrated_count"] == 1 and result["backup_sha256"] == "digest"
    assert row.config_json["flat"]["unified_wallet_enabled"] is True
    assert result["history"][-1]["operator_id"] == 5
    assert "sha256:digest" in apply.await_args.args[-1]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_rechecks_before_reopening(monkeypatch):
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(cutover, "exclusive", AsyncMock())
    monkeypatch.setattr(cutover, "state", AsyncMock(return_value={"paused": True, "phase": "completed", "job_id": "a" * 32}))
    monkeypatch.setattr(cutover, "sync_runtime", AsyncMock())
    monkeypatch.setattr(cutover, "get_settings", lambda: SimpleNamespace(unified_wallet_enabled=True, wallet_environment="Production"))
    monkeypatch.setattr(cutover, "configured_flat", AsyncMock(return_value={"unified_wallet_enabled": True, "wallet_environment": "Production"}))
    monkeypatch.setattr(cutover, "validate_activation", AsyncMock(side_effect=ValueError("异常")))
    with pytest.raises(ValueError, match="异常"):
        await cutover.resume(db, "a" * 32, 5, "resume")
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_backup_credentials_are_not_in_command_arguments(monkeypatch, tmp_path):
    monkeypatch.setattr(cutover, "BACKUPS", tmp_path)
    monkeypatch.setattr(cutover, "get_settings", lambda: SimpleNamespace(database_url="postgresql+asyncpg://u:secret@db:5432/platform?sslmode=require"))
    calls = []
    async def command(*args, env=None):
        calls.append((args, env))
        if args[0] == "pg_dump":
            from pathlib import Path
            Path(args[-1]).write_bytes(b"PGDMP-backup")
    monkeypatch.setattr(cutover, "command", command)
    digest = await cutover.backup("a" * 32)
    assert len(digest) == 64
    assert all("secret" not in str(args) for args, _ in calls)
    assert calls[0][1]["PGPASSWORD"] == "secret"
    assert calls[0][1]["PGSSLMODE"] == "require"
    assert calls[1][0][0:2] == ("pg_restore", "--list")


def test_barrier_includes_get_payment_callbacks_but_not_login_or_report():
    from app.wallet_cutover_middleware import guarded
    assert guarded("GET", "/api/billing/epay/notify")
    assert guarded("POST", "/api/billing/apple/notifications")
    assert guarded("POST", "/api/tasks/123/retry")
    assert not guarded("POST", "/api/auth/login")
    assert not guarded("POST", "/api/admin/settings/wallet-migration/apply")
    assert not guarded("GET", "/api/billing/wallet")
