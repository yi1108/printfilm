"""共同充值接口与混合来源收益的真实数据库验证，不调用外部支付。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import func, select

from app.api import billing as billing_api
from app.database import get_db
from app.deps import get_current_admin, get_current_user
from app.models import Order
from app.models_wallet import WalletFundingLot
from app.models_wallet_finance import WalletFundingReview
from app.services.billing import wallet
from app.marketplace import app_bootstrap, apple_api
from app.marketplace.app_admin import FundingReviewInput, PayoutInput, SettlementInput
from app.marketplace.app_finance import create_payout, reconcile
from app.marketplace.app_models import AppleProduct
from app.marketplace.app_settings import get_app_settings
from app.marketplace.bootstrap import install
from app.marketplace.coin_service import apply_apple_transaction, unlock_publication
from app.marketplace.models import RevenueLedger
from app.marketplace.unified_admin import review_web_funding
from test_marketplace_coins import coin_ctx, content, topup


@asynccontextmanager
async def client_for(ctx, monkeypatch):
    """真实路由共用同一已隔离会话，外部请求和鉴权使用测试替身。"""
    app = FastAPI()
    app.include_router(billing_api.router, prefix="/api")
    install(app)

    async def database():
        yield ctx.db

    async def actor():
        return ctx.buyer

    async def administrator():
        return ctx.owner

    async def schema_ready():
        return None

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    app.dependency_overrides[get_current_admin] = administrator
    app.dependency_overrides[app_bootstrap.require_schema] = schema_ready
    monkeypatch.setattr(billing_api.epay, "verify", lambda _params: True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def web_credit(ctx, reference="WEB-PAID", units=150, cash=90):
    """建立真实已付款Web订单与冻结来源，金额不借用苹果参考标价。"""
    order = Order(out_trade_no=reference, user_id=ctx.buyer.id, sku_id="test_gift",
                  amount_fen=cash, credit_fen=units, pay_type="alipay", status="paid")
    ctx.db.add(order)
    await wallet.credit(ctx.db, ctx.buyer.id, units, source_type="web_order", source_ref=reference, amount_fen=cash)
    await ctx.db.commit()
    return await ctx.db.scalar(select(WalletFundingLot).where(WalletFundingLot.source_ref == reference))


@pytest.mark.asyncio
async def test_web_callback_and_app_wallet_share_balance_and_preserve_ai_freeze(coin_ctx, monkeypatch):
    """重复易支付回调只入账一次，App所见余额立即扣除AI冻结和预留。"""
    ctx = coin_ctx
    order = Order(out_trade_no="WEB-CALLBACK", user_id=ctx.buyer.id, sku_id="test_gift",
                  amount_fen=90, credit_fen=150, pay_type="wxpay", status="pending")
    ctx.db.add(order)
    await ctx.db.commit()
    async with client_for(ctx, monkeypatch) as client:
        params = {"out_trade_no": order.out_trade_no, "money": "0.90", "trade_status": "TRADE_SUCCESS"}
        assert (await client.get("/api/billing/epay/notify", params=params)).text == "success"
        assert (await client.get("/api/billing/epay/notify", params=params)).text == "success"
        await wallet.reserve_task(ctx.db, ctx.buyer.id, 4567, 50)
        await ctx.db.commit()
        web = (await client.get("/api/billing/wallet")).json()
        app = (await client.get("/api/marketplace/app/v1/me/wallet")).json()
        assert web["unified_wallet_enabled"] is True
        assert web["balance_fen"] == app["balance_fen"] == app["balance_coins"] == 100
        assert web["frozen_fen"] == app["frozen_fen"] == 50
        assert web["debt_fen"] == app["debt_coins"] == 0
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == 1


@pytest.mark.asyncio
async def test_apple_common_order_freezes_sku_gift_and_accepts_channel_actual_price(coin_ctx, monkeypatch):
    """统一套餐保留赠额，Apple实付可与Web/参考标价不同，不能多入账。"""
    ctx = coin_ctx
    ctx.db.add(AppleProduct(product_id="shared.test.gift", sku_id="test_gift",
        sku_snapshot={"id": "test_gift", "name": "共同赠额套餐", "amount_fen": 90, "credit_fen": 150},
        coins=150, price_fen=100, enabled=True))
    await ctx.db.commit()
    monkeypatch.setattr(apple_api, "purchasing_enabled", lambda user_id=None: True)
    monkeypatch.setattr(get_app_settings(), "apple_iap_enabled", True)
    async with client_for(ctx, monkeypatch) as client:
        skus = (await client.get("/api/billing/skus?channel=apple_iap")).json()
        assert skus["skus"][0]["credit_fen"] == 150
        response = await client.post("/api/billing/orders", json={"sku_id": "test_gift", "pay_type": "apple_iap", "idempotency_key": "shared-recharge-1"})
        assert response.status_code == 200, response.text
        intent = response.json()
        again = await client.post("/api/billing/orders", json={"sku_id": "test_gift", "pay_type": "apple_iap", "idempotency_key": "shared-recharge-1"})
        assert again.json()["out_trade_no"] == intent["out_trade_no"]
        params = {"out_trade_no": intent["out_trade_no"], "money": "1.00", "trade_status": "TRADE_SUCCESS"}
        assert (await client.get("/api/billing/epay/notify", params=params)).status_code == 400
    from app.marketplace.service import now
    txn = await apply_apple_transaction(ctx.db, {"user_id": ctx.buyer.id, "environment": "Production",
        "transaction_id": "real-gift-payment", "app_account_token": intent["app_account_token"],
        "product_id": "shared.test.gift", "currency": "CNY", "amount_fen": 95,
        "status": "paid", "signed_at": now(), "raw_payload": {}})
    await ctx.db.commit()
    order = await ctx.db.get(Order, txn.recharge_order_id)
    assert (order.amount_fen, order.credit_fen, order.pay_type) == (95, 150, "apple_iap")
    assert txn.anomaly and ctx.buyer.balance_fen == 150
    await reconcile(ctx.db, SettlementInput(environment="Production", month="2026-10", transaction_ids=[txn.id],
        channel_fee_fen=5, tax_fen=0, received_fen=90, note="官方报表确认真实售价，参考价差异已核对",
        idempotency_key="gift-payment-reconcile"), ctx.owner.id)
    await wallet.reserve_task(ctx.db, ctx.buyer.id, 4568, 100)
    await wallet.settle_task(ctx.db, ctx.buyer.id, 4568, 80)
    assert ctx.buyer.balance_fen == 70 and ctx.buyer.frozen_fen == 0
    assert txn.anomaly  # 原参考价差保留审计，不清空或改写凭证。


@pytest.mark.asyncio
async def test_mixed_gifts_web_and_apple_revenue_requires_all_cash_sources_reconciled(coin_ctx):
    """赠额零现金，折扣按实付分摊；不能只核对Apple而漏掉Web来源就打款。"""
    ctx = coin_ctx
    await wallet.credit(ctx.db, ctx.buyer.id, 20, source_type="signup_grant", source_ref="registration", amount_fen=0)
    lot = await web_credit(ctx)
    txn, _ = await topup(ctx)
    publication = await content(ctx, 200)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 200, "mixed-source-unlock")
    await ctx.db.commit()
    ledger = await ctx.db.scalar(select(RevenueLedger))
    assert (ledger.gross_fen, ledger.platform_fen, ledger.creator_fen) == (120, 24, 96)
    await reconcile(ctx.db, SettlementInput(environment="Production", month="2026-10", transaction_ids=[txn.id],
        channel_fee_fen=0, tax_fen=0, received_fen=600, note="核对苹果报表", idempotency_key="mixed-apple-reconcile"), ctx.owner.id)
    await ctx.db.commit()
    payout = PayoutInput(environment="Production", owner_id=ctx.owner.id, ledger_ids=[ledger.id], amount_fen=96,
                        note="线下打款回执", idempotency_key="mixed-creator-payout")
    with pytest.raises(HTTPException) as unavailable:
        await create_payout(ctx.db, payout, ctx.owner.id)
    assert unavailable.value.detail["code"] == "MARKETPLACE_PAYOUT_NOT_ELIGIBLE"
    await ctx.db.rollback()
    await ctx.db.refresh(lot)
    await ctx.db.refresh(ctx.owner)
    review = FundingReviewInput(lot_id=lot.id, channel_fee_fen=5, tax_fen=0, received_fen=85,
        note="核对易支付真实收款流水", idempotency_key="mixed-web-reconcile")
    item = await review_web_funding(ctx.db, review, ctx.owner.id)
    await ctx.db.commit()
    duplicate = await review_web_funding(ctx.db, review, ctx.owner.id)
    assert duplicate.id == item.id
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingReview)) == 1
    assert (await create_payout(ctx.db, payout, ctx.owner.id)).amount_fen == 96
