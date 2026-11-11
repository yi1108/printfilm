"""Real PostgreSQL cutover transactions in a random test-only schema."""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text, func
from sqlalchemy.exc import DBAPIError

from app.models import User, WalletLedger
from app.models_settings import AppSettings
from app.models_wallet import WalletAccount, WalletFundingLot
from app.services.billing import wallet_cutover as cutover
from test_unified_wallet_core import wallet_ctx  # noqa: F401
from test_unified_wallet_migration import prepare_legacy_tables


async def setup(ctx):
    from app.services.billing.wallet_schema import register_models
    from app.models_wallet import WalletBase
    register_models()
    connection = await ctx.db.connection()
    schema = connection.sync_connection.get_execution_options()["schema_translate_map"][None]
    # Raw table-lock SQL must resolve ONLY inside this random test schema.
    await ctx.db.execute(text(f'SET search_path TO "{schema}"'))
    await connection.run_sync(WalletBase.metadata.create_all)
    await connection.run_sync(AppSettings.__table__.create)
    await prepare_legacy_tables(ctx)
    await ctx.db.execute(text("CREATE TABLE task_runs (id integer PRIMARY KEY, status text, billing_status text)"))
    legacy = User(email="legacy-cutover@test.invalid", hashed_password="unused", balance_fen=100, frozen_fen=0)
    ctx.db.add(legacy)
    await ctx.db.flush()
    ctx.db.add(WalletLedger(user_id=legacy.id, delta_fen=100, balance_after=100,
                           kind="grant", ref_type="signup", ref_id="signup"))
    ctx.db.add(AppSettings(id="default", config_json={"flat": {
        "unified_wallet_enabled": False, "wallet_environment": "Production"}}))
    await ctx.db.commit()
    return legacy, schema


@pytest.mark.asyncio
async def test_cutover_is_atomic_and_repeatable(wallet_ctx, monkeypatch):
    ctx = wallet_ctx
    legacy, _ = await setup(ctx)
    monkeypatch.setattr(cutover, "backup", AsyncMock(return_value="a" * 64))
    monkeypatch.setattr(cutover, "sync_runtime", AsyncMock())
    initial = await cutover.report(ctx.db, "Production")
    assert initial["ready"] == 1 and initial["already_migrated"] == 1
    with pytest.raises(ValueError, match="待迁移 1 个"):
        await cutover.validate_activation(ctx.db, "Production")
    from app.services.model_settings import patch_admin_model_settings
    from app.schemas_settings import AdminModelSettingsPatch
    with pytest.raises(ValueError, match="待迁移 1 个"):
        await patch_admin_model_settings(ctx.db, AdminModelSettingsPatch(unified_wallet_enabled=True))
    assert await ctx.db.scalar(select(WalletAccount.id).where(WalletAccount.user_id == legacy.id)) is None
    state = await cutover.pause(ctx.db, 1, "planned migration")
    final = await cutover.apply(ctx.db, state["job_id"], 1, "verified report")
    assert final["paused"] and final["phase"] == "completed"
    await ctx.db.refresh(legacy)
    assert legacy.balance_fen == 100
    assert (await cutover.report(ctx.db))["ready"] == 0
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot).where(WalletFundingLot.user_id == legacy.id)) == 1
    settings = await ctx.db.get(AppSettings, "default", populate_existing=True)
    assert settings.config_json["flat"]["unified_wallet_enabled"] is True
    with pytest.raises(ValueError, match="不能切回旧记账"):
        await patch_admin_model_settings(ctx.db, AdminModelSettingsPatch(unified_wallet_enabled=False))
    await cutover.apply(ctx.db, state["job_id"], 1, "network retry")
    assert cutover.backup.await_count == 1
    restored = await cutover.resume(ctx.db, state["job_id"], 1, "checked sources")
    assert not restored["paused"]


@pytest.mark.asyncio
async def test_failed_financial_write_rolls_back_but_pause_survives(wallet_ctx, monkeypatch):
    ctx = wallet_ctx
    legacy, _ = await setup(ctx)
    legacy_id = legacy.id
    monkeypatch.setattr(cutover, "backup", AsyncMock(return_value="b" * 64))
    state = await cutover.pause(ctx.db, 1, "planned migration")
    original = cutover.apply_plans
    async def fail_after_writing(*args):
        await original(*args)
        raise RuntimeError("simulated write failure")
    monkeypatch.setattr(cutover, "apply_plans", fail_after_writing)
    with pytest.raises(RuntimeError, match="simulated"):
        await cutover.apply(ctx.db, state["job_id"], 1, "execute")
    await ctx.db.rollback()
    assert (await cutover.state(ctx.db))["paused"] is True
    assert await ctx.db.scalar(select(WalletAccount.id).where(WalletAccount.user_id == legacy_id)) is None
    assert await ctx.db.scalar(select(User.balance_fen).where(User.id == legacy_id)) == 100
    settings = await ctx.db.get(AppSettings, "default", populate_existing=True)
    assert settings.config_json["flat"]["unified_wallet_enabled"] is False


@pytest.mark.asyncio
async def test_shared_write_barrier_and_exclusive_cutover_are_mutually_exclusive(wallet_ctx):
    ctx = wallet_ctx
    async with ctx.factory() as writer, ctx.factory() as migration:
        await writer.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": cutover.LOCK})
        # A migration cannot pass a live callback/write request.
        await migration.execute(text("SET LOCAL lock_timeout='100ms'"))
        with pytest.raises(DBAPIError):
            await migration.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": cutover.LOCK})
        await migration.rollback()
        await writer.rollback()
        await cutover.exclusive(migration)
        await writer.execute(text("SET LOCAL lock_timeout='100ms'"))
        with pytest.raises(DBAPIError):
            await writer.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": cutover.LOCK})


@pytest.mark.asyncio
async def test_http_maintenance_blocks_callbacks_and_writes_but_allows_reads(wallet_ctx, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app import wallet_cutover_middleware as barrier
    ctx = wallet_ctx
    await setup(ctx)
    await cutover.pause(ctx.db, 1, "test maintenance")
    monkeypatch.setattr(barrier, "BarrierSession", ctx.factory)
    monkeypatch.setattr(barrier, "AsyncSessionLocal", ctx.factory)
    app = FastAPI()
    app.middleware("http")(barrier.middleware)
    writes = []
    @app.post("/api/test-write")
    async def write():
        writes.append(True)
        return {"ok": True}
    @app.get("/api/billing/epay/notify")
    async def callback():
        writes.append(True)
        return {"ok": True}
    @app.get("/api/test-read")
    async def read():
        return {"ok": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test.invalid") as client:
        response = await client.post("/api/test-write")
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "30"
        assert response.json()["code"] == "WALLET_MIGRATION_MAINTENANCE"
        assert (await client.get("/api/billing/epay/notify")).status_code == 503
        assert (await client.get("/api/test-read")).status_code == 200
    assert not writes


@pytest.mark.asyncio
async def test_approval_is_invalidated_by_fresh_database_state(wallet_ctx, monkeypatch):
    ctx = wallet_ctx
    await setup(ctx)
    unknown = User(email="opening-approval@test.invalid", hashed_password="unused", balance_fen=50, frozen_fen=0)
    ctx.db.add(unknown)
    await ctx.db.commit()
    user_id = unknown.id
    job = await cutover.pause(ctx.db, 1, "核对期初余额")
    first = next(row for row in (await cutover.report(ctx.db))["accounts"] if row["user_id"] == user_id)
    assert first["approval_status"] == "required"
    await cutover.approve(ctx.db, user_id, first["fingerprint"], "Production", job["job_id"], 1, "人工核对确认")
    # Load an identity-map snapshot, then simulate a late external write in the
    # isolated test schema. A locked recheck must not reuse this cached balance.
    assert (await ctx.db.get(User, user_id)).balance_fen == 50
    async with ctx.factory() as writer:
        await writer.execute(User.__table__.update().where(User.id == user_id).values(balance_fen=60))
        await writer.commit()
    current = next(row for row in (await cutover.report(ctx.db))["accounts"] if row["user_id"] == user_id)
    assert current["balance_fen"] == 60 and current["approval_status"] == "required"
    assert current["fingerprint"] != first["fingerprint"]
    backup = AsyncMock()
    monkeypatch.setattr(cutover, "backup", backup)
    with pytest.raises(ValueError):
        await cutover.apply(ctx.db, job["job_id"], 1, "使用旧确认迁移")
    backup.assert_not_awaited()
    await ctx.db.rollback()
    assert (await cutover.state(ctx.db))["paused"]


@pytest.mark.asyncio
async def test_overlapping_funding_ranges_block_existing_account(wallet_ctx):
    ctx = wallet_ctx
    await setup(ctx)
    ctx.user.balance_fen = 100
    ctx.db.add(WalletFundingLot(user_id=ctx.user.id, environment="Production", source_type="signup_grant",
        source_ref="bad-interval", total_units=100, total_amount_fen=0,
        available_ranges=[[0, 60], [50, 90]], void_ranges=[], active=True, revision=0, settlement_status="reconciled"))
    await ctx.db.flush()
    result = await cutover.report(ctx.db)
    row = next(row for row in result["accounts"] if row["user_id"] == ctx.user.id)
    assert row["status"] == "blocked" and "区间" in row["reason"]
