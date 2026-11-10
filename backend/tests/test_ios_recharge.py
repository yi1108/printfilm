"""Fixed retail prices and foreign receipts; isolated PostgreSQL schemas only."""
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import Order
from app.models_wallet import WalletAllocation, WalletFundingLot
from app.marketplace import apple_api, apple_client, apple_service
from app.marketplace.app_models import AppleExchangeRate, AppleTransactionRevision
from app.marketplace.apple_fx import finalize_valuation
from app.services import stripe_payments
from app.services.billing import pricing, wallet
from test_marketplace_apple_iap import apple_cfg, apple_ctx, signed_payload, verified_transaction
from test_marketplace_coins import coin_ctx, content


@pytest.mark.asyncio
async def test_apple_skus_reject_unprepared_schema(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.api.billing import list_skus
    from app.marketplace import app_bootstrap

    async def not_ready():
        return False

    monkeypatch.setattr(app_bootstrap, "schema_ready", not_ready)
    request = Request({"type": "http", "path": "/api/billing/skus", "headers": []})
    with pytest.raises(HTTPException) as error:
        await list_skus(request, channel="apple_iap", db=None)
    assert error.value.status_code == 503


@pytest.mark.parametrize("sku,usd", zip(pricing.SKUS, [1499, 6999, 13999, 27999]))
def test_fixed_usd_quotes_ignore_accounting_rate(sku, usd):
    for rate in ("6", "8"):
        settings = SimpleNamespace(stripe_currency="usd", stripe_usd_cny_rate=rate)
        quote = stripe_payments.quote_payment(sku["amount_fen"], settings, sku_id=sku["id"])
        assert quote["payment_amount_minor"] == usd
        assert pricing.topup_prices(sku) == {"CNY": sku["amount_fen"], "USD": usd}


def test_usd_is_not_normalized_as_cny(apple_cfg):
    txn = apple_client.normalize_transaction(signed_payload(currency="USD", storefront="USA", price=14990))
    assert txn["payment_amount_minor"] == 1499
    assert txn["apple_price_milliunits"] == 14990
    assert txn["amount_fen"] == 0


def test_market_closed_does_not_disable_recharge(apple_cfg, monkeypatch):
    apple_cfg.apple_iap_enabled = True
    monkeypatch.setattr(wallet, "enabled", lambda: True)
    monkeypatch.setattr(apple_api, "is_marketplace_enabled", lambda: False)
    monkeypatch.setattr(apple_client, "apple_configured", lambda: True)
    assert apple_api.purchasing_enabled()


@pytest.mark.asyncio
async def test_usd_receipt_credits_then_valuation_preserves_balance_and_audit(apple_ctx):
    ctx = apple_ctx
    payload = verified_transaction(ctx, currency="USD", payment_amount_minor=1499, apple_price_milliunits=14990, storefront="USA", amount_fen=0)
    txn = await apple_service.apply_verified_transaction(ctx.db, payload)
    await apple_service.apply_verified_transaction(ctx.db, payload)
    assert txn.valuation_status == "pending" and txn.amount_fen == 0
    assert ctx.buyer.balance_fen == 600
    lot = await ctx.db.scalar(select(WalletFundingLot))
    assert lot.settlement_status == "pending_fx"
    await wallet.consume(ctx.db, ctx.buyer.id, 300, business_type="test", business_ref="consume")
    rate = AppleExchangeRate(currency="USD", cny_per_unit="7.2", source="test accounting version", operator_id=ctx.other.id)
    ctx.db.add(rate)
    await ctx.db.flush()
    await finalize_valuation(ctx.db, txn.id, rate.id, ctx.other.id)
    await finalize_valuation(ctx.db, txn.id, rate.id, ctx.other.id)
    assert ctx.buyer.balance_fen == 300
    assert txn.amount_fen == 10793 and lot.total_amount_fen == 10793
    allocation = await ctx.db.scalar(select(WalletAllocation))
    assert allocation.amount_fen == 10793 // 2
    order = await ctx.db.get(Order, txn.recharge_order_id)
    assert (order.payment_currency, order.payment_amount_minor, order.amount_fen) == ("usd", 1499, 10793)
    assert await ctx.db.scalar(select(func.count()).select_from(AppleTransactionRevision)) == 2
    from app.marketplace.coin_refunds import refund_apple_transaction
    await refund_apple_transaction(ctx.db, "Production", txn.transaction_id)
    await refund_apple_transaction(ctx.db, "Production", txn.transaction_id, reversed=True)
    assert ctx.buyer.balance_fen == 300
    assert txn.amount_fen == 10793 and txn.fx_snapshot["version"] == rate.id


@pytest.mark.asyncio
async def test_refund_before_valuation_keeps_source_pending(apple_ctx):
    ctx = apple_ctx
    txn = await apple_service.apply_verified_transaction(ctx.db, verified_transaction(ctx, currency="USD", payment_amount_minor=1499, amount_fen=0))
    from app.marketplace.coin_refunds import refund_apple_transaction
    await refund_apple_transaction(ctx.db, "Production", txn.transaction_id)
    lot = await ctx.db.scalar(select(WalletFundingLot))
    assert lot.settlement_status == "pending_fx"
    rate = AppleExchangeRate(currency="USD", cny_per_unit="7", source="test", operator_id=ctx.other.id)
    ctx.db.add(rate)
    await ctx.db.flush()
    await finalize_valuation(ctx.db, txn.id, rate.id, ctx.other.id)
    await refund_apple_transaction(ctx.db, "Production", txn.transaction_id, reversed=True)
    assert ctx.buyer.balance_fen == 600
    assert await ctx.db.scalar(select(func.sum(AppleTransactionRevision.delta_gross_fen))) == 10493


@pytest.mark.asyncio
async def test_pending_video_earnings_are_finalized_before_payout(coin_ctx):
    from app.marketplace.app_models import AppleProduct
    from app.marketplace.coin_service import apply_apple_transaction, unlock_publication
    from app.marketplace.models import RevenueLedger
    from app.marketplace.service import now
    ctx = coin_ctx
    await wallet.initialize_account(ctx.db, ctx.buyer)
    ctx.db.add(AppleProduct(product_id="usd.test", sku_id="topup_10", coins=10000, price_fen=10000,
        expected_prices={"CNY": 10000, "USD": 1499}, enabled=True,
        sku_snapshot={"id": "topup_10", "amount_fen": 10000, "credit_fen": 10000}))
    await ctx.db.flush()
    txn = await apply_apple_transaction(ctx.db, {"environment": "Production", "transaction_id": "usd-video",
        "user_id": ctx.buyer.id, "product_id": "usd.test", "currency": "USD", "payment_amount_minor": 1499,
        "amount_fen": 0, "app_account_token": ctx.token, "signed_at": now(), "status": "paid"})
    publication = await content(ctx, 5000)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 5000, "pending-fx-unlock")
    ledger = await ctx.db.scalar(select(RevenueLedger))
    assert ledger.gross_fen == 0
    rate = AppleExchangeRate(currency="USD", cny_per_unit="7", source="receipt statement", operator_id=ctx.owner.id)
    ctx.db.add(rate)
    await ctx.db.flush()
    await finalize_valuation(ctx.db, txn.id, rate.id, ctx.owner.id)
    assert ledger.gross_fen == 10493 // 2
    assert ledger.platform_fen + ledger.creator_fen == ledger.gross_fen
    assert ctx.buyer.balance_fen == 5000
    from app.marketplace.coin_refunds import refund_apple_transaction
    await refund_apple_transaction(ctx.db, "Production", txn.transaction_id)
    assert ledger.settlement_status == "revoked"
