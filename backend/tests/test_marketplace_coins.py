"""观影币账务集成测试，只使用派生测试库及随机隔离 schema。"""
import asyncio
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base
from app.models import User
from app.models_wallet import WalletBase, WalletAllocation, WalletEvent
from app.services.billing import wallet
from app.marketplace.app_models import AppleProduct, AppleTransaction, AppPayout, CoinAllocation, CoinEntry, CoinGrant, CoinLot, CoinUnlock, CoinWallet, CreatorAccount, RevenueAdjustment
from app.marketplace.app_schema import check_schema, register_models
from app.marketplace.coin_service import apply_apple_transaction, has_access, refund_apple_transaction, unlock_publication
from app.marketplace.models import Asset, ContentOrder, Entitlement, MarketBase, Publication, RevenueLedger, Rights, Work
from conftest import _ensure_test_database, _resolve_test_database_url


@pytest_asyncio.fixture
async def coin_ctx(monkeypatch):
    """提交只落到随机测试 schema，允许独立连接验证真实并发锁。"""
    url, name = _resolve_test_database_url(get_settings().database_url)
    monkeypatch.setattr(get_settings(), "unified_wallet_enabled", True)
    from app.services.billing import pricing
    monkeypatch.setattr(pricing, "SKUS", [*pricing.SKUS,
        {"id": "test_600", "name": "测试共同套餐", "amount_fen": 600, "credit_fen": 600},
        {"id": "test_800", "name": "测试共同套餐二", "amount_fen": 800, "credit_fen": 800}])
    import app.models_drama, app.models_teams, app.models_team_billing  # noqa: F401
    await _ensure_test_database(url, name)
    schema = f"coin_test_{uuid.uuid4().hex}"
    engine = create_async_engine(url)
    register_models()
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with scoped.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(MarketBase.metadata.create_all)
            await conn.run_sync(WalletBase.metadata.create_all)
        factory = async_sessionmaker(scoped, expire_on_commit=False)
        async with factory() as db:
            buyer = User(email=f"buyer-{uuid.uuid4().hex}@test.invalid", hashed_password="unused", balance_fen=0)
            owner = User(email=f"owner-{uuid.uuid4().hex}@test.invalid", hashed_password="unused")
            db.add_all([buyer, owner])
            await db.flush()
            await wallet.initialize_account(db, buyer)
            await wallet.initialize_account(db, owner)
            await db.commit()
            ctx = SimpleNamespace(db=db, factory=factory, buyer=buyer, owner=owner, token=str(uuid.uuid4()), schema=schema)
            yield ctx
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def topup(ctx, coins=600, *, transaction_id=None, environment="Production", status="paid"):
    """测试替身仅代替已验证的 Apple 输入，业务环境没有模拟入口。"""
    from app.marketplace.service import now
    await wallet.initialize_account(ctx.db, ctx.buyer)
    product_id = f"test.coins.{coins}"
    if not await ctx.db.scalar(select(AppleProduct.id).where(AppleProduct.product_id == product_id)):
        ctx.db.add(AppleProduct(product_id=product_id, sku_id=f"test_{coins}",
            sku_snapshot={"id": f"test_{coins}", "name": "测试共同套餐", "amount_fen": coins, "credit_fen": coins},
            coins=coins, price_fen=coins, enabled=True))
        await ctx.db.commit()
    txn = {"environment": environment, "transaction_id": transaction_id or uuid.uuid4().hex,
           "original_transaction_id": "original", "user_id": ctx.buyer.id, "product_id": product_id,
           "app_account_token": ctx.token, "coins": coins, "amount_fen": coins, "currency": "CNY",
           "status": status, "signed_at": now(), "raw_payload": {}}
    item = await apply_apple_transaction(ctx.db, txn)
    await ctx.db.commit()
    return item, txn


async def content(ctx, coins=100):
    """建立已审核的真实市场模型，媒体签名和实际上传不在本测试范围。"""
    asset = Asset(owner_id=ctx.owner.id, kind="video", filename="movie.mp4", content_type="video/mp4", size_bytes=100,
                  object_key=f"marketplace/test/{uuid.uuid4().hex}.mp4", status="ready")
    ctx.db.add(asset)
    await ctx.db.flush()
    ctx.db.add(Rights(owner_id=ctx.owner.id, asset_id=asset.id, basic_status="approved", full_status="approved",
                      certificate_asset_id=asset.id, details={"source": "external"}))
    work = Work(owner_id=ctx.owner.id, title="test", asset_id=asset.id, price_fen=0, sale_type="platform_unlock",
                unlock_price_fen=coins, listed=True, audit_status="approved")
    ctx.db.add(work)
    await ctx.db.flush()
    publication = Publication(content_type="work", content_id=work.id, version=1, owner_id=ctx.owner.id,
                              asset_id=asset.id, sale_type="platform_unlock", unlock_price_fen=coins, share_bps=2000,
                              audit_status="approved", listed=True, playback_status="done", playback_manifest_key="marketplace/hls/test/index.m3u8")
    ctx.db.add(publication)
    await ctx.db.commit()
    return publication


async def balance(ctx, environment="Production"):
    """读库而非信任服务返回的余额。"""
    await ctx.db.flush()
    return await ctx.db.scalar(select(User.balance_fen).where(User.id == ctx.buyer.id))


@pytest.mark.asyncio
async def test_topup_duplicate_updates_shared_balance_without_creator_revenue(coin_ctx):
    ctx = coin_ctx
    transaction, payload = await topup(ctx)
    await apply_apple_transaction(ctx.db, payload)
    await ctx.db.commit()
    assert await balance(ctx) == 600
    assert await ctx.db.scalar(select(func.count()).select_from(WalletEvent)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(CoinWallet)) == 0
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueLedger)) == 0
    await ctx.db.refresh(ctx.buyer)
    assert ctx.buyer.balance_fen == 600


@pytest.mark.asyncio
async def test_fifo_unlock_and_duplicate_do_not_charge_twice(coin_ctx):
    ctx = coin_ctx
    await topup(ctx, 600)
    await topup(ctx, 300)
    publication = await content(ctx, 700)
    result = await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 700, "same-unlock-key")
    await ctx.db.commit()
    duplicate = await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 700, "same-unlock-key")
    another = await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 700, "other-unlock-key")
    await ctx.db.commit()
    assert result["charged_coins"] == 700 and duplicate["duplicate"] and another["charged_coins"] == 0
    assert await balance(ctx) == 200
    assert await ctx.db.scalar(select(func.count()).select_from(WalletAllocation)) == 2
    ledger = await ctx.db.scalar(select(RevenueLedger))
    assert (ledger.gross_fen, ledger.platform_fen, ledger.creator_fen) == (700, 140, 560)


@pytest.mark.asyncio
async def test_price_or_insufficient_balance_leaves_no_orders(coin_ctx):
    ctx = coin_ctx
    await topup(ctx, 600)
    publication = await content(ctx, 700)
    for expected in (600, 700):
        with pytest.raises(HTTPException) as error:
            await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, expected, "attempt-unlock")
        assert error.value.status_code == 409
    await ctx.db.commit()
    assert await balance(ctx) == 600
    assert await ctx.db.scalar(select(func.count()).select_from(ContentOrder)) == 0


@pytest.mark.asyncio
async def test_refund_mixed_sources_returns_other_funds_and_reverses_whole_order(coin_ctx):
    ctx = coin_ctx
    first, _ = await topup(ctx, 600)
    second, _ = await topup(ctx, 600)
    publication = await content(ctx, 950)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 950, "mixed-source-unlock")
    await ctx.db.commit()
    await refund_apple_transaction(ctx.db, "Production", first.transaction_id)
    await refund_apple_transaction(ctx.db, "Production", first.transaction_id)
    await ctx.db.commit()
    assert await balance(ctx) == 600
    assert not await has_access(ctx.db, ctx.buyer.id, publication.id, "Production")
    adjustment = await ctx.db.scalar(select(RevenueAdjustment))
    assert (adjustment.gross_fen, adjustment.creator_fen) == (-950, -760)
    await refund_apple_transaction(ctx.db, "Production", second.transaction_id)
    await ctx.db.commit()
    assert await balance(ctx) == 0
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueAdjustment)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("refund_order", [(0, 1), (1, 0)])
async def test_refund_order_does_not_change_final_balances(coin_ctx, refund_order):
    ctx = coin_ctx
    first, _ = await topup(ctx, 600)
    second, _ = await topup(ctx, 600)
    publication = await content(ctx, 950)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 950, "mixed-order-refund")
    await ctx.db.commit()
    for index in refund_order:
        await refund_apple_transaction(ctx.db, "Production", (first, second)[index].transaction_id)
        await ctx.db.commit()
    assert await balance(ctx) == 0
    assert await ctx.db.scalar(select(func.sum(RevenueAdjustment.gross_fen))) == -950


@pytest.mark.asyncio
async def test_refund_reversed_restores_coins_not_old_access(coin_ctx):
    ctx = coin_ctx
    transaction, payload = await topup(ctx, 600)
    publication = await content(ctx, 100)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "initial-unlock")
    await ctx.db.commit()
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await ctx.db.commit()
    await apply_apple_transaction(ctx.db, payload)  # 迟到的旧 paid 不能复活充值。
    await ctx.db.commit()
    assert await balance(ctx) == 0
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id, reversed=True)
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id, reversed=True)
    await ctx.db.commit()
    assert await balance(ctx) == 600
    assert not await has_access(ctx.db, ctx.buyer.id, publication.id, "Production")
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "new-unlock-after-refund")
    await ctx.db.commit()
    assert await balance(ctx) == 500 and await has_access(ctx.db, ctx.buyer.id, publication.id, "Production")


@pytest.mark.asyncio
async def test_sandbox_cannot_create_web_or_production_access(coin_ctx):
    ctx = coin_ctx
    with pytest.raises(HTTPException) as mismatch:
        await topup(ctx, environment="Sandbox")
    assert mismatch.value.detail["code"] == "WALLET_ENVIRONMENT_MISMATCH"
    assert await ctx.db.scalar(select(func.count()).select_from(Entitlement)) == 0
    assert await ctx.db.scalar(select(func.count()).select_from(CoinGrant)) == 0
    assert await balance(ctx) == 0


@pytest.mark.asyncio
async def test_refunded_first_then_paid_does_not_credit(coin_ctx):
    ctx = coin_ctx
    item, payload = await topup(ctx, status="refunded")
    await apply_apple_transaction(ctx.db, {**payload, "status": "paid"})
    await ctx.db.commit()
    assert await balance(ctx) == 0


@pytest.mark.asyncio
async def test_two_devices_concurrent_unlock_only_charge_once(coin_ctx):
    ctx = coin_ctx
    await topup(ctx)
    publication = await content(ctx, 100)

    async def execute(key):
        async with ctx.factory() as db:
            result = await unlock_publication(db, ctx.buyer.id, "Production", publication.id, 100, key)
            await db.commit()
            return result

    results = await asyncio.gather(execute("device-one-unlock"), execute("device-two-unlock"))
    assert sum(result.get("charged_coins", 0) for result in results) == 100
    assert await balance(ctx) == 500
    assert await ctx.db.scalar(select(func.count()).select_from(CoinGrant)) == 1


@pytest.mark.asyncio
async def test_payout_requires_reconciliation_and_refund_becomes_creator_debt(coin_ctx):
    from app.marketplace.app_admin import PayoutInput, SettlementInput
    from app.marketplace.app_finance import create_payout, reconcile
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    publication = await content(ctx, 100)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "payout-unlock")
    await ctx.db.commit()
    ledger = await ctx.db.scalar(select(RevenueLedger))
    payout = PayoutInput(environment="Production", owner_id=ctx.owner.id, ledger_ids=[ledger.id], amount_fen=80, note="银行打款回执", idempotency_key="payout-idempotency")
    with pytest.raises(HTTPException):
        await create_payout(ctx.db, payout, ctx.owner.id)
    statement = SettlementInput(environment="Production", month="2026-10", transaction_ids=[transaction.id], channel_fee_fen=180, tax_fen=0, received_fen=420, note="苹果报表2026-10", idempotency_key="settlement-idempotency")
    await reconcile(ctx.db, statement, ctx.owner.id)
    await ctx.db.commit()
    await create_payout(ctx.db, payout, ctx.owner.id)
    await ctx.db.commit()
    await create_payout(ctx.db, payout, ctx.owner.id)
    await ctx.db.commit()
    assert await ctx.db.scalar(select(func.count()).select_from(AppPayout)) == 1
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await ctx.db.commit()
    assert await ctx.db.scalar(select(CreatorAccount.debt_fen).where(CreatorAccount.owner_id == ctx.owner.id)) == 80
    assert (await ctx.db.get(RevenueLedger, ledger.id)).creator_fen == 80
    assert (await ctx.db.scalar(select(AppPayout))).amount_fen == 80


@pytest.mark.asyncio
async def test_schema_check_covers_registered_app_tables(coin_ctx):
    async with coin_ctx.factory.kw["bind"].connect() as conn:
        # Inspector 的默认 schema 需要显式 search_path，避免误查public。
        await conn.execute(text(f'SET LOCAL search_path TO "{coin_ctx.schema}"'))
        assert await conn.run_sync(check_schema) == []


@pytest.mark.asyncio
async def test_http_financial_routes_and_admin_survive_disabled_market(coin_ctx, monkeypatch):
    """通过真实总挂载测试开关、鉴权、商品冻结和敏感字段白名单。"""
    from fastapi import FastAPI
    import httpx
    from app.database import get_db
    from app.deps import get_current_admin, get_current_user
    from app.marketplace import app_access, app_bootstrap, apple_client, coin_api
    from app.marketplace.bootstrap import install
    from app.marketplace.app_settings import MarketplaceAppSettings
    ctx = coin_ctx
    app = FastAPI()
    install(app)

    async def database():
        yield ctx.db

    async def actor():
        return ctx.buyer

    async def admin():
        if ctx.buyer.role != "admin":
            raise HTTPException(403, "仅管理员可访问")
        return ctx.buyer

    async def schema_ready():
        return None

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    app.dependency_overrides[get_current_admin] = admin
    app.dependency_overrides[app_bootstrap.require_schema] = schema_ready
    monkeypatch.setattr(app_access, "app_open", lambda: False)
    monkeypatch.setattr(coin_api, "current_environment", lambda: "Production")
    monkeypatch.setattr("app.marketplace.apple_client.get_app_settings", lambda: MarketplaceAppSettings(_env_file=None))
    monkeypatch.setattr(apple_client, "apple_configured", lambda: False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        prefix = "/api/marketplace/app/v1"
        assert (await client.get(prefix + "/me/wallet")).json()["balance_coins"] == 0
        assert (await client.get(prefix + "/me/entitlements")).status_code == 200
        assert (await client.get(prefix + "/coin-products")).json()["purchasing_enabled"] is False
        no_payment = await client.post(prefix + "/iap/apple/transactions/verify", json={"signed_transaction_info": "x" * 30})
        assert no_payment.status_code == 503
        notify = await client.post("/api/marketplace/payments/apple/notifications", json={"signedPayload": "x" * 30})
        assert notify.status_code == 503
        admin_prefix = "/api/admin/marketplace/app"
        assert (await client.get(admin_prefix + "/summary")).status_code == 403
        ctx.buyer.role = "admin"
        await ctx.db.commit()
        assert (await client.get(admin_prefix + "/summary")).status_code == 200
        product = {"product_id": "test.immutable", "sku_id": "test_600", "coins": 600, "price_fen": 600, "enabled": False}
        assert (await client.put(admin_prefix + "/products", json=product)).status_code == 200
        immutable = await client.put(admin_prefix + "/products", json={**product, "sku_id": "test_800", "coins": 800, "price_fen": 800})
        assert immutable.status_code == 409
        await topup(ctx)
        rows = await client.get(admin_prefix + "/transactions")
        assert rows.status_code == 200
        assert "raw_payload" not in rows.text and "app_account_token" not in rows.text
        assert (await client.get(admin_prefix + "/not-a-table")).status_code == 404


@pytest.mark.asyncio
async def test_refund_and_payout_concurrent_keeps_exact_debt(coin_ctx):
    """相反并发次序可先打款再记债，或先冲正拒打款，均不能漏账。"""
    from app.marketplace.app_admin import PayoutInput, SettlementInput
    from app.marketplace.app_finance import create_payout, reconcile
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    publication = await content(ctx, 100)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "concurrent-refund-payout")
    ledger = await ctx.db.scalar(select(RevenueLedger))
    await reconcile(ctx.db, SettlementInput(environment="Production", month="2026-10", transaction_ids=[transaction.id],
        channel_fee_fen=180, tax_fen=0, received_fen=420, note="对账", idempotency_key="concurrent-statement"), ctx.owner.id)
    await ctx.db.commit()

    async def refund():
        async with ctx.factory() as db:
            await refund_apple_transaction(db, "Production", transaction.transaction_id)
            await db.commit()

    async def payout():
        async with ctx.factory() as db:
            try:
                await create_payout(db, PayoutInput(environment="Production", owner_id=ctx.owner.id, ledger_ids=[ledger.id],
                    amount_fen=80, note="银行回执", idempotency_key="concurrent-payout-key"), ctx.owner.id)
                await db.commit()
            except HTTPException as exc:
                assert exc.detail["code"] == "MARKETPLACE_PAYOUT_NOT_ELIGIBLE"

    await asyncio.wait_for(asyncio.gather(refund(), payout()), timeout=15)
    await ctx.db.rollback()
    paid = await ctx.db.scalar(select(func.count()).select_from(AppPayout))
    debt = await ctx.db.scalar(select(CreatorAccount.debt_fen).where(CreatorAccount.owner_id == ctx.owner.id))
    assert (paid, debt) in ((0, 0), (1, 80))
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueAdjustment)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_before_refund", [True, False])
async def test_inflight_epay_purchase_survives_apple_refund(coin_ctx, monkeypatch, callback_before_refund):
    """在途或后续真实易支付购买保留独立来源，苹果只能撤回自己的权益。"""
    from starlette.requests import Request
    from urllib.parse import urlencode
    from app.marketplace import commerce
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    publication = await content(ctx, 100)
    pending = ContentOrder(out_trade_no="LEGACY-IN-FLIGHT", user_id=ctx.buyer.id, publication_id=publication.id,
        amount_fen=100, pay_type="alipay", status="pending", idempotency_key="inflight-epay-order")
    ctx.db.add(pending)
    await ctx.db.commit()
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "coin-before-inflight-epay")
    await ctx.db.commit()
    monkeypatch.setattr(commerce, "_payment_ready", lambda: True)
    monkeypatch.setattr(commerce.epay, "verify", lambda params: True)
    request = Request({"type": "http", "method": "GET", "query_string": urlencode({"out_trade_no": pending.out_trade_no,
        "trade_no": "real-epay-trade", "money": "1.00", "trade_status": "TRADE_SUCCESS"}).encode(), "headers": []})
    if callback_before_refund:
        response = await commerce.epay_notify(request, ctx.db)
        assert response.body == b"success"
        # 此时余额购买仍有效，不同时给重复实收计第二份创作者收益。
        assert await ctx.db.scalar(select(func.count()).select_from(RevenueLedger)) == 1
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await ctx.db.commit()
    if not callback_before_refund:
        response = await commerce.epay_notify(request, ctx.db)
        assert response.body == b"success"
    assert await has_access(ctx.db, ctx.buyer.id, publication.id, "Production")
    entitlement = await ctx.db.scalar(select(Entitlement))
    assert entitlement.active and entitlement.order_id == pending.id
    assert await ctx.db.scalar(select(func.count()).select_from(CoinGrant).where(CoinGrant.active.is_(True))) == 0
    surviving_ledger = await ctx.db.scalar(select(RevenueLedger).where(RevenueLedger.order_id == pending.id))
    assert surviving_ledger and (surviving_ledger.gross_fen, surviving_ledger.creator_fen) == (100, 80)
    # 旧购买冲正后净收入仍等于存活的Web实收，不丢收益也不重复分成。
    gross = await ctx.db.scalar(select(func.sum(RevenueLedger.gross_fen)))
    reversed_gross = await ctx.db.scalar(select(func.sum(RevenueAdjustment.gross_fen)))
    assert gross + reversed_gross == 100
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await ctx.db.commit()
    assert (await commerce.epay_notify(request, ctx.db)).body == b"success"
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueLedger)) == 2
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueAdjustment)) == 1


@pytest.mark.asyncio
async def test_epay_callback_cannot_reactivate_coin_order(coin_ctx, monkeypatch):
    """即便易支付签名有效，也不能修改另一渠道的币订单。"""
    from starlette.requests import Request
    from urllib.parse import urlencode
    from app.marketplace import commerce
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    publication = await content(ctx, 100)
    result = await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "coin-channel-isolation")
    await ctx.db.commit()
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await ctx.db.commit()
    order = await ctx.db.get(ContentOrder, result["order_id"])
    monkeypatch.setattr(commerce, "_payment_ready", lambda: True)
    monkeypatch.setattr(commerce.epay, "verify", lambda params: True)
    request = Request({"type": "http", "method": "GET", "query_string": urlencode({"out_trade_no": order.out_trade_no,
        "money": "1.00", "trade_status": "TRADE_SUCCESS"}).encode(), "headers": []})
    response = await commerce.epay_notify(request, ctx.db)
    assert response.status_code == 400
    assert not await has_access(ctx.db, ctx.buyer.id, publication.id, "Production")


@pytest.mark.asyncio
async def test_schema_rejects_nonunique_active_grant_index(coin_ctx):
    """错误同名索引不能通过财务结构验收。"""
    async with coin_ctx.factory.kw["bind"].begin() as conn:
        await conn.execute(text(f'SET LOCAL search_path TO "{coin_ctx.schema}"'))
        await conn.execute(text('DROP INDEX marketplace_one_active_coin_grant'))
        await conn.execute(text('CREATE INDEX marketplace_one_active_coin_grant ON marketplace_coin_grants(user_id, environment, publication_id) WHERE active = false'))
        failures = await conn.run_sync(check_schema)
        assert any("index-definition" in value for value in failures)
        assert any("index-predicate" in value for value in failures)


@pytest.mark.asyncio
async def test_wallet_unlock_refreshes_cached_entitlement_after_epay_fulfillment(coin_ctx, monkeypatch):
    """App预检后Web完成付款，同一会话缓存的旧无效权益不能导致余额再扣一次。"""
    from starlette.requests import Request
    from urllib.parse import urlencode
    from app.marketplace import commerce
    ctx = coin_ctx
    await topup(ctx)
    publication = await content(ctx, 100)
    old_order = ContentOrder(out_trade_no="OLD-REVOKED-BALANCE-ORDER", user_id=ctx.buyer.id,
        publication_id=publication.id, amount_fen=100, pay_type="platform_balance", status="revoked",
        idempotency_key="old-revoked-balance-order")
    pending = ContentOrder(out_trade_no="EPAY-AFTER-APP-PREFLIGHT", user_id=ctx.buyer.id,
        publication_id=publication.id, amount_fen=100, pay_type="alipay", status="pending",
        idempotency_key="epay-after-app-preflight")
    ctx.db.add_all([old_order, pending])
    await ctx.db.flush()
    inactive = Entitlement(user_id=ctx.buyer.id, publication_id=publication.id,
        order_id=old_order.id, active=False)
    ctx.db.add(inactive)
    await ctx.db.commit()
    monkeypatch.setattr(commerce, "_payment_ready", lambda: True)
    monkeypatch.setattr(commerce.epay, "verify", lambda params: True)
    request = Request({"type": "http", "method": "GET", "query_string": urlencode({
        "out_trade_no": pending.out_trade_no, "money": "1.00", "trade_status": "TRADE_SUCCESS"}).encode(), "headers": []})
    async with ctx.factory() as reader:
        cached = await reader.get(Entitlement, inactive.id)
        assert cached.active is False
        assert not await has_access(reader, ctx.buyer.id, publication.id, "Production")
        assert (await commerce.epay_notify(request, ctx.db)).body == b"success"
        result = await unlock_publication(reader, ctx.buyer.id, "Production", publication.id, 100, "after-web-callback")
        await reader.commit()
        assert result["duplicate"] and result["charged_coins"] == 0
        assert cached.active is True
    assert await balance(ctx) == 600
    assert await ctx.db.scalar(select(func.count()).select_from(CoinUnlock)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["publication", "work", "rights"])
async def test_wallet_unlock_rechecks_cached_content_after_preflight(coin_ctx, changed):
    """App预检后作者下架或版权受限，旧会话内容缓存不能继续通过扣款校验。"""
    ctx = coin_ctx
    await topup(ctx)
    publication = await content(ctx, 100)
    async with ctx.factory() as reader:
        cached_publication = await reader.get(Publication, publication.id)
        cached_work = await reader.get(Work, publication.content_id)
        cached_rights = await reader.scalar(select(Rights).where(Rights.asset_id == publication.asset_id))
        assert cached_publication.listed and cached_work.listed and not cached_rights.blocked
        if changed == "publication":
            target = await ctx.db.get(Publication, publication.id)
            target.listed = False
        elif changed == "work":
            target = await ctx.db.get(Work, publication.content_id)
            target.listed = False
        else:
            target = await ctx.db.scalar(select(Rights).where(Rights.asset_id == publication.asset_id))
            target.blocked = True
        await ctx.db.commit()
        with pytest.raises(HTTPException) as error:
            await unlock_publication(reader, ctx.buyer.id, "Production", publication.id, 100,
                                     f"content-changed-after-preflight-{changed}")
        assert error.value.detail["code"] == "MARKETPLACE_CONTENT_CHANGED"
        await reader.commit()
    assert await balance(ctx) == 600
    assert await ctx.db.scalar(select(func.count()).select_from(CoinUnlock)) == 0
