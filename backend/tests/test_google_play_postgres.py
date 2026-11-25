"""Concurrent receipts use real PostgreSQL locks in an isolated test schema."""
import asyncio
import pytest
from sqlalchemy import func, select, text

from test_unified_wallet_core import wallet_ctx
from test_google_play_billing import checkout, proof
from app.config import get_settings
from app.models import Order
from app.models_teams import Team
from app.models_wallet import WalletFundingLot
from app.marketplace import google_service as service
from app.marketplace.app_models import AppleTransaction
from app.marketplace.sandbox_models import SandboxAccount, SandboxEntry, SandboxLot
from app.marketplace.google_config import DEFAULT_PRODUCTS
from app.marketplace.google_models import (GoogleSettings, GoogleAccount, GoogleIntent,
    GooglePurchase, GoogleWork, GoogleVoid, GoogleAudit, GoogleNotification, GoogleCursor)


@pytest.mark.asyncio
@pytest.mark.parametrize("sandbox", [False, True])
async def test_parallel_receipts_credit_once(wallet_ctx, monkeypatch, sandbox):
    ctx = wallet_ctx
    monkeypatch.setattr(get_settings(), "wallet_environment", "Production")
    monkeypatch.setattr(service, "available", lambda *_: True)
    connection = await ctx.db.connection()
    for model in (Team, Order, GoogleSettings, GoogleAccount, GoogleIntent, GooglePurchase,
                  GoogleWork, GoogleVoid, GoogleAudit, GoogleNotification, GoogleCursor,
                  AppleTransaction, SandboxAccount, SandboxEntry, SandboxLot):
        await connection.run_sync(lambda sync, model=model: model.__table__.create(sync, checkfirst=True))
    config = dict(package_name="com.deep.printfilm", purchasing_enabled=True, test_user_ids=[ctx.user.id] if sandbox else [],
        products=[{**DEFAULT_PRODUCTS[0], "credit_fen": 10000, "reference_amount_fen": 10000}])
    ctx.db.add(GoogleSettings(key="billing", version=1, credentials="unused", config=config))
    await ctx.db.commit()
    _, intent = await checkout(ctx)

    async def receive():
        async with ctx.factory() as db:
            result = await service.apply_proof(db, config["package_name"], "printfilm_credits_trial",
                "concurrent-receipt", proof(intent, **({"purchaseType": 0} if sandbox else {})),
                config, user_id=ctx.user.id)
            await db.commit()
            return result["status"]

    results = await asyncio.wait_for(asyncio.gather(receive(), receive()), timeout=30)
    assert sorted(results) == ["already_credited", "credited"]
    await ctx.db.refresh(ctx.user)
    assert ctx.user.balance_fen == (0 if sandbox else 10000)
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == int(not sandbox)
    assert await ctx.db.scalar(select(func.count()).select_from(SandboxLot)) == int(sandbox)
    assert await ctx.db.scalar(select(func.count()).select_from(SandboxEntry)) == int(sandbox)
    assert await ctx.db.scalar(select(func.count()).select_from(GooglePurchase)) == 1



@pytest.mark.asyncio
async def test_existing_sandbox_lot_schema_upgrades_twice_preserving_apple(wallet_ctx):
    from app.marketplace.app_schema import _add_google_sandbox_source, acquire_schema_lock
    from app.marketplace.service import now

    ctx = wallet_ctx
    async with ctx.factory().bind.begin() as conn:
        for model in (AppleTransaction, GooglePurchase):
            await conn.run_sync(lambda sync, model=model: model.__table__.create(sync))
    apple = AppleTransaction(environment="Sandbox", transaction_id="old-apple", user_id=ctx.user.id,
                             product_id="coins.600", app_account_token="test", coins=600, amount_fen=600,
                             signed_at=now())
    ctx.db.add(apple)
    await ctx.db.commit()
    async with ctx.factory().bind.begin() as conn:
        schema = conn.sync_connection.get_execution_options()["schema_translate_map"][None]
        assert schema.startswith("wallet_core_") and schema.removeprefix("wallet_core_").isalnum()
        await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        assert await conn.scalar(text("SELECT current_schema()")) == schema
        await conn.execute(text("""
            CREATE TABLE marketplace_sandbox_lots (
                id INTEGER PRIMARY KEY,
                transaction_id INTEGER NOT NULL UNIQUE REFERENCES marketplace_apple_transactions(id),
                total_units BIGINT NOT NULL,
                available_units BIGINT NOT NULL
            )
        """))
        await conn.execute(text(
            "INSERT INTO marketplace_sandbox_lots VALUES (1, :apple_id, 600, 400)"
        ), {"apple_id": apple.id})
        await conn.run_sync(acquire_schema_lock)
        await conn.run_sync(_add_google_sandbox_source)
        await conn.run_sync(_add_google_sandbox_source)
        row = (await conn.execute(text(
            "SELECT transaction_id, google_purchase_id, total_units, available_units FROM marketplace_sandbox_lots"
        ))).one()
        assert row == (apple.id, None, 600, 400)
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await conn.execute(text("""
                    INSERT INTO marketplace_sandbox_lots (id, total_units, available_units)
                    VALUES (2, 1000, 1000)
                """))
