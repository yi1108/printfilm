"""Concurrent receipts use real PostgreSQL locks in an isolated test schema."""
import asyncio
import pytest
from sqlalchemy import func, select

from test_unified_wallet_core import wallet_ctx
from test_google_play_billing import checkout, proof
from app.config import get_settings
from app.models import Order
from app.models_teams import Team
from app.models_wallet import WalletFundingLot
from app.marketplace import google_service as service
from app.marketplace.google_config import DEFAULT_PRODUCTS
from app.marketplace.google_models import (GoogleSettings, GoogleAccount, GoogleIntent,
    GooglePurchase, GoogleWork, GoogleVoid, GoogleAudit, GoogleNotification, GoogleCursor)


@pytest.mark.asyncio
async def test_parallel_receipts_credit_once(wallet_ctx, monkeypatch):
    ctx = wallet_ctx
    monkeypatch.setattr(get_settings(), "wallet_environment", "Production")
    monkeypatch.setattr(service, "available", lambda *_: True)
    connection = await ctx.db.connection()
    for model in (Team, Order, GoogleSettings, GoogleAccount, GoogleIntent, GooglePurchase,
                  GoogleWork, GoogleVoid, GoogleAudit, GoogleNotification, GoogleCursor):
        await connection.run_sync(lambda sync, model=model: model.__table__.create(sync, checkfirst=True))
    config = dict(package_name="com.deep.printfilm", purchasing_enabled=True, test_user_ids=[],
        products=[{**DEFAULT_PRODUCTS[0], "credit_fen": 10000, "reference_amount_fen": 10000}])
    ctx.db.add(GoogleSettings(key="billing", version=1, credentials="unused", config=config))
    await ctx.db.commit()
    _, intent = await checkout(ctx)

    async def receive():
        async with ctx.factory() as db:
            result = await service.apply_proof(db, config["package_name"], "printfilm_credits_trial",
                "concurrent-receipt", proof(intent), config, user_id=ctx.user.id)
            await db.commit()
            return result["status"]

    results = await asyncio.wait_for(asyncio.gather(receive(), receive()), timeout=30)
    assert sorted(results) == ["already_credited", "credited"]
    await ctx.db.refresh(ctx.user)
    assert ctx.user.balance_fen == 10000
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(GooglePurchase)) == 1
