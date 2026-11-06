"""Apple边界与可靠履约回归；签名网络替身仅存在测试，金融数据隔离在随机schema。"""
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import Order, User
from app.models_wallet import WalletBase, WalletEvent, WalletFundingLot
from app.services.billing import wallet
from app.marketplace import apple_api, apple_client, apple_runtime, apple_service
from app.marketplace.apple_models import AppleAccountToken, AppleNotification, AppleNotificationCursor
from app.marketplace.app_models import AppleProduct, AppleTransaction, CoinEntry, CoinLot, CoinWallet
from app.marketplace.app_settings import MarketplaceAppSettings, get_app_settings
from app.marketplace.coin_refunds import refund_apple_transaction
from app.marketplace.models import MarketBase
from app.marketplace.service import now
from conftest import _ensure_test_database, _resolve_test_database_url


@pytest.fixture
def apple_cfg(monkeypatch):
    """测试不读取真实Apple密钥，也不访问App Store。"""
    cfg = MarketplaceAppSettings(_env_file=None, enabled=False, apple_iap_enabled=False,
                                  apple_bundle_id="test.printfilm.app", apple_environment="Production", apple_app_id=123)
    for module in (apple_api, apple_client, apple_runtime):
        monkeypatch.setattr(module, "get_app_settings", lambda: cfg)
    return cfg


def signed_payload(**changes):
    """构造已验签模型的业务字段，不当作真实JWS传给生产验证器。"""
    return {"bundleId": "test.printfilm.app", "environment": "Production", "type": "Consumable",
            "quantity": 1, "currency": "CNY", "storefront": "CHN", "price": 6000,
            "productId": "coins.600", "transactionId": "123456789", "originalTransactionId": "123456789",
            "appAccountToken": "d38ad1bc-c7a4-45bf-a1f0-2b7ad3a87643", "signedDate": int(now().timestamp() * 1000),
            **changes}


def test_marketplace_switch_does_not_enable_app(monkeypatch):
    """预发可以只有市场开关、没有 .env。不能因此在启动时做 App 建表。"""
    monkeypatch.setenv("MARKETPLACE_ENABLED", "true")
    monkeypatch.delenv("MARKETPLACE_APP_ENABLED", raising=False)
    cfg = MarketplaceAppSettings(_env_file=None)
    assert cfg.enabled is False


def test_app_switch_reads_its_own_variable(monkeypatch):
    """显式打开 App 时仍以 MARKETPLACE_APP_ENABLED 为准，市场开关取反也不覆盖。"""
    monkeypatch.setenv("MARKETPLACE_ENABLED", "false")
    monkeypatch.setenv("MARKETPLACE_APP_ENABLED", "true")
    cfg = MarketplaceAppSettings(_env_file=None)
    assert cfg.enabled is True


def test_blank_configuration_is_safe(apple_cfg):
    """默认关闭、空AppID和密钥都不能被误报为支付可用。"""
    blank = MarketplaceAppSettings(_env_file=None, apple_app_id="")
    assert blank.apple_app_id is None
    assert not blank.enabled and not blank.apple_iap_enabled
    assert not apple_client.apple_configured()
    with pytest.raises(HTTPException) as error:
        apple_client.require_apple_configured()
    assert error.value.status_code == 503


@pytest.mark.parametrize("changes", [
    {"bundleId": "other.app"}, {"environment": "Sandbox"}, {"type": "Non-Consumable"},
    {"quantity": 2}, {"quantity": True}, {"currency": "EUR"}, {"storefront": "USA"},
    {"price": 6001}, {"price": True}, {"price": -10}, {"appAccountToken": "not-a-uuid"},
])
def test_transaction_boundary_rejects_wrong_app_environment_or_amount(apple_cfg, changes):
    """不能把外币、其他App、沙箱、非整分或多数量交易当本期充值。"""
    with pytest.raises(HTTPException):
        apple_client.normalize_transaction(signed_payload(**changes))


def test_official_model_normalization_preserves_milliunit_price(apple_cfg):
    """真实官方attrs/枚举结构能安全序列化，6000毫单位为600分。"""
    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.models.Type import Type
    from appstoreserverlibrary.models.JWSTransactionDecodedPayload import JWSTransactionDecodedPayload
    decoded = JWSTransactionDecodedPayload(**signed_payload(environment=Environment.PRODUCTION, type=Type.CONSUMABLE))
    result = apple_client.normalize_transaction(decoded)
    assert result["amount_fen"] == 600
    assert result["status"] == "paid"
    assert result["raw_payload"]["environment"] == "Production"


@pytest.mark.asyncio
async def test_signature_must_succeed_before_reading_fields(apple_cfg, monkeypatch):
    """即使客户端提供看似有效字段，官方验证器失败时不读取或授予交易。"""
    def reject(_signed):
        raise ValueError("bad signature")
    monkeypatch.setattr(apple_client, "_objects", lambda: (SimpleNamespace(verify_and_decode_signed_transaction=reject), None))
    with pytest.raises(HTTPException) as error:
        await apple_client.verify_transaction("unsigned.client.claim")
    assert error.value.detail["code"] == "MARKETPLACE_IAP_TRANSACTION_INVALID"


@pytest_asyncio.fixture
async def apple_ctx(apple_cfg, monkeypatch):
    """独立测试库和随机schema，提交savepoint后仍由外层事务回滚。"""
    url, name = _resolve_test_database_url(get_settings().database_url)
    monkeypatch.setattr(get_settings(), "unified_wallet_enabled", True)
    import app.models_drama, app.models_teams, app.models_team_billing  # noqa: F401
    await _ensure_test_database(url, name)
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        outer = await connection.begin()
        schema = f"apple_test_{uuid.uuid4().hex}"
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection = await connection.execution_options(schema_translate_map={None: schema})
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(MarketBase.metadata.create_all)
        await connection.run_sync(WalletBase.metadata.create_all)
        db = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        buyer, other = User(email="apple-buyer@test.invalid", hashed_password="unused"), User(email="apple-other@test.invalid", hashed_password="unused")
        db.add_all([buyer, other, AppleProduct(product_id="coins.600", sku_id="test_600",
            sku_snapshot={"id": "test_600", "name": "测试共同套餐", "amount_fen": 600, "credit_fen": 600},
            coins=600, price_fen=600, enabled=True)])
        await db.flush()
        await wallet.initialize_account(db, buyer)
        await wallet.initialize_account(db, other)
        token = await apple_service.account_token(db, buyer.id)
        state = SimpleNamespace(db=db, buyer=buyer, other=other, user=buyer, token=token)

        async def database_override():
            yield db

        async def actor_override():
            return state.user

        @asynccontextmanager
        async def runtime_session():
            yield db

        app = FastAPI()
        app.include_router(apple_api.router, prefix="/api/marketplace/app/v1")
        app.include_router(apple_api.notifications_router)
        app.include_router(apple_api.billing_router)
        app.dependency_overrides[get_db] = database_override
        app.dependency_overrides[get_current_user] = actor_override
        monkeypatch.setattr(apple_runtime, "AsyncSessionLocal", runtime_session)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                state.client = client
                yield state
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


def verified_transaction(ctx, **changes):
    """只用于替换Apple网络边界，账号归属和入账仍跑真实数据库逻辑。"""
    return {"environment": "Production", "transaction_id": "123456789", "original_transaction_id": "123456789",
            "product_id": "coins.600", "amount_fen": 600, "currency": "CNY", "app_account_token": ctx.token.token,
            "status": "paid", "signed_at": now(), "revoked_at": None,
            "raw_payload": {"_server_observed_at": now().isoformat()}, **changes}


def stub_apple(monkeypatch, ctx, **changes):
    """测试替身不进入产品代码，也不绕过数据库归属验证。"""
    transaction = verified_transaction(ctx, **changes)

    async def verify(_signed):
        return transaction.copy()

    async def query(_transaction_id):
        return transaction.copy()

    monkeypatch.setattr(apple_client, "verify_transaction", verify)
    monkeypatch.setattr(apple_client, "query_transaction", query)
    return transaction


@pytest.mark.asyncio
async def test_verified_payment_is_fulfilled_with_new_purchase_disabled(apple_ctx, monkeypatch):
    """入口关闭不丢已付款交易；丢响应重试只加币一次。"""
    ctx = apple_ctx
    stub_apple(monkeypatch, ctx)
    path = "/api/marketplace/app/v1/iap/apple/transactions/verify"
    for _ in range(2):
        response = await ctx.client.post(path, json={"signed_transaction_info": "signed-test-transaction"})
        assert response.status_code == 200, response.text
        assert response.json()["balance_coins"] == 600
        assert response.json()["finish_transaction"] is True
    assert await ctx.db.scalar(select(func.count()).select_from(AppleTransaction)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(WalletEvent)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(CoinWallet)) == 0
    disabled = await ctx.client.post("/api/marketplace/app/v1/iap/apple/purchase-intents", json={"product_id": "coins.600", "idempotency_key": "new-payment-disabled"})
    assert disabled.status_code == 503


@pytest.mark.asyncio
async def test_transaction_cannot_be_claimed_by_another_account(apple_ctx, monkeypatch):
    ctx = apple_ctx
    stub_apple(monkeypatch, ctx)
    ctx.user = ctx.other
    response = await ctx.client.post("/api/marketplace/app/v1/iap/apple/transactions/verify", json={"signed_transaction_info": "signed-test-transaction"})
    assert response.status_code == 403
    assert await ctx.db.scalar(select(func.count()).select_from(AppleTransaction)) == 0


@pytest.mark.asyncio
async def test_purchase_intent_and_account_token_are_idempotent(apple_ctx):
    ctx = apple_ctx
    first = await apple_service.purchase_intent(ctx.db, ctx.buyer.id, "Production", "coins.600", "one-intent-key")
    second = await apple_service.purchase_intent(ctx.db, ctx.buyer.id, "Production", "coins.600", "one-intent-key")
    assert first["intent_id"] == second["intent_id"]
    assert first["app_account_token"] == second["app_account_token"] == ctx.token.token
    ctx.db.add(AppleProduct(product_id="coins.100", sku_id="test_100",
        sku_snapshot={"id": "test_100", "name": "测试共同套餐", "amount_fen": 100, "credit_fen": 100},
        coins=100, price_fen=100, enabled=True))
    await ctx.db.flush()
    with pytest.raises(HTTPException) as error:
        await apple_service.purchase_intent(ctx.db, ctx.buyer.id, "Production", "coins.100", "one-intent-key")
    assert error.value.detail["code"] == "MARKETPLACE_IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_older_query_cannot_restore_refunded_balance(apple_ctx):
    ctx = apple_ctx
    earlier = verified_transaction(ctx)
    await apple_service.apply_verified_transaction(ctx.db, earlier)
    later = verified_transaction(ctx, status="refunded", signed_at=now() + timedelta(seconds=1), revoked_at=now(),
                                 raw_payload={"_server_observed_at": (now() + timedelta(seconds=1)).isoformat()})
    await apple_service.apply_verified_transaction(ctx.db, later)
    await apple_service.apply_verified_transaction(ctx.db, earlier)
    account = await ctx.db.get(User, ctx.buyer.id)
    assert account.balance_fen == 0
    newest = verified_transaction(ctx, signed_at=now() + timedelta(seconds=2),
                                  raw_payload={"_server_observed_at": (now() + timedelta(seconds=2)).isoformat()})
    await apple_service.apply_verified_transaction(ctx.db, newest, event_type="REFUND_REVERSED")
    await apple_service.apply_verified_transaction(ctx.db, newest, event_type="REFUND_REVERSED")
    assert account.balance_fen == 600


@pytest.mark.asyncio
async def test_refund_reversal_before_original_charge_credits_once(apple_ctx):
    ctx = apple_ctx
    transaction = verified_transaction(ctx)
    await apple_service.apply_verified_transaction(ctx.db, transaction, event_type="REFUND_REVERSED")
    await apple_service.apply_verified_transaction(ctx.db, transaction)
    account = await ctx.db.get(User, ctx.buyer.id)
    assert account.balance_fen == 600
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == 1


@pytest.mark.asyncio
async def test_notification_is_durable_and_duplicate_safe(apple_ctx, monkeypatch):
    ctx = apple_ctx
    transaction = stub_apple(monkeypatch, ctx)
    payload = {"environment": "Production", "notification_uuid": str(uuid.uuid4()), "notification_type": "ONE_TIME_CHARGE",
               "transaction": transaction, "observed_at": now(), "raw_payload": {}}

    async def verify(_signed):
        return payload

    monkeypatch.setattr(apple_client, "verify_notification", verify)
    for _ in range(2):
        response = await ctx.client.post("/api/marketplace/payments/apple/notifications", json={"signedPayload": "signed-apple-notification"})
        assert response.status_code == 200
    assert await ctx.db.scalar(select(func.count()).select_from(AppleNotification)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(AppleTransaction)) == 0
    assert await apple_runtime.process_notification_once()
    notification = await ctx.db.scalar(select(AppleNotification))
    assert notification.status == "done"
    assert await ctx.db.scalar(select(func.count()).select_from(AppleTransaction)) == 1


@pytest.mark.asyncio
async def test_consumption_data_is_not_sent_without_user_consent(apple_ctx, monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("必须先取得用户授权")
    monkeypatch.setattr(apple_client, "send_consumption", forbidden)
    snapshot = await apple_service.consumption_request_snapshot(apple_ctx.db, verified_transaction(apple_ctx))
    note = await apple_service.send_consumption_snapshot(snapshot)
    assert "未授权" in note
    response = await apple_ctx.client.patch("/api/marketplace/app/v1/iap/apple/consumption-consent", json={"consented": True})
    assert response.status_code == 200 and response.json()["consented"] is True


@pytest.mark.asyncio
async def test_expired_notification_lease_can_resume(apple_ctx, monkeypatch):
    ctx = apple_ctx
    transaction = stub_apple(monkeypatch, ctx)
    await apple_service.persist_notification(ctx.db, {"environment": "Production", "notification_uuid": str(uuid.uuid4()),
        "notification_type": "ONE_TIME_CHARGE", "transaction": transaction, "observed_at": now(), "raw_payload": {}})
    item = await ctx.db.scalar(select(AppleNotification))
    item.status, item.lease_token, item.lease_until = "running", "crashed-process", now() - timedelta(seconds=1)
    await ctx.db.commit()
    assert await apple_runtime.process_notification_once()
    assert item.status == "done"


@pytest.mark.asyncio
async def test_delayed_refund_reversal_uses_current_apple_status(apple_ctx, monkeypatch):
    """迟到的撤销通知不能按事件名复活当前仍处于退款状态的交易。"""
    ctx = apple_ctx
    paid = verified_transaction(ctx)
    await apple_service.apply_verified_transaction(ctx.db, paid)
    refunded = verified_transaction(ctx, status="refunded", signed_at=now() + timedelta(seconds=1),
                                   revoked_at=now(), raw_payload={"_server_observed_at": (now() + timedelta(seconds=1)).isoformat()})
    await apple_service.apply_verified_transaction(ctx.db, refunded)
    await apple_service.persist_notification(ctx.db, {"environment": "Production", "notification_uuid": str(uuid.uuid4()),
        "notification_type": "REFUND_REVERSED", "transaction": paid, "observed_at": now(), "raw_payload": {}})
    await ctx.db.commit()

    async def current_status(_transaction_id):
        return refunded.copy()

    monkeypatch.setattr(apple_client, "query_transaction", current_status)
    assert await apple_runtime.process_notification_once()
    account = await ctx.db.get(User, ctx.buyer.id)
    assert account.balance_fen == 0
    assert (await ctx.db.scalar(select(AppleTransaction))).status == "refunded"
    assert (await ctx.db.scalar(select(AppleNotification))).status == "done"


@pytest.mark.asyncio
async def test_consumption_network_call_holds_no_database_transaction(apple_ctx, monkeypatch):
    """读快照、释放事务再回传，Apple慢请求不能占通知/钱包锁。"""
    ctx = apple_ctx
    transaction = verified_transaction(ctx)
    await apple_service.apply_verified_transaction(ctx.db, transaction)
    ctx.token.consumption_data_consent = True
    await wallet.consume(ctx.db, ctx.buyer.id, 150, business_type="ai_task", business_ref="test-consumed-task")
    await apple_service.persist_notification(ctx.db, {"environment": "Production", "notification_uuid": str(uuid.uuid4()),
        "notification_type": "CONSUMPTION_REQUEST", "transaction": transaction, "observed_at": now(), "raw_payload": {}})
    await ctx.db.commit()
    contexts, sent = [], []

    @asynccontextmanager
    async def isolated_session():
        contexts.append(True)
        try:
            yield ctx.db
        finally:
            # 测试共用同一连接；提交只读savepoint模拟独立Session关闭后的释放。
            if ctx.db.in_transaction():
                await ctx.db.commit()
            contexts.pop()

    async def send(transaction_id, **data):
        assert contexts == []
        assert not ctx.db.in_transaction()
        sent.append((transaction_id, data))

    monkeypatch.setattr(apple_runtime, "AsyncSessionLocal", isolated_session)
    monkeypatch.setattr(apple_client, "send_consumption", send)
    assert await apple_runtime.process_notification_once()
    assert sent == [(transaction["transaction_id"], {"delivered": True, "consumed_milli_percent": 25000})]
    assert (await ctx.db.scalar(select(AppleNotification))).status == "done"


@pytest.mark.asyncio
async def test_history_compensation_persists_pagination_and_deduplicates(apple_ctx, monkeypatch):
    """补偿分页状态落库，重叠窗口重复记录不产生重复收件箱或入账。"""
    ctx = apple_ctx
    calls, uid = [], str(uuid.uuid4())
    payload = {"environment": "Production", "notification_uuid": uid, "notification_type": "ONE_TIME_CHARGE",
               "transaction": verified_transaction(ctx), "observed_at": now(), "raw_payload": {}}

    async def history(start, end, page):
        calls.append((start, end, page))
        return SimpleNamespace(notificationHistory=[SimpleNamespace(signedPayload="signed-notification-history")],
                               hasMore=page is None, paginationToken="page-2" if page is None else None)

    async def verify(_signed):
        return payload

    monkeypatch.setattr(apple_client, "notification_history", history)
    monkeypatch.setattr(apple_client, "verify_notification", verify)
    assert await apple_runtime.reconcile_history_once()
    cursor = await ctx.db.scalar(select(AppleNotificationCursor))
    assert cursor.pagination_token == "page-2"
    assert cursor.window_start is not None and cursor.window_end is not None
    await apple_runtime.reconcile_history_once()
    assert len(calls) == 2
    assert calls[0][:2] == calls[1][:2] and calls[1][2] == "page-2"
    assert cursor.pagination_token is None and cursor.window_start is None
    assert cursor.last_end_at == calls[1][1]
    assert await ctx.db.scalar(select(func.count()).select_from(AppleNotification)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(AppleTransaction)) == 0


@pytest.mark.asyncio
async def test_invalid_notification_is_not_persisted(apple_ctx, monkeypatch):
    async def reject(_signed):
        raise HTTPException(400, {"code": "MARKETPLACE_IAP_NOTIFICATION_INVALID", "message": "苹果通知签名验证失败。"})

    monkeypatch.setattr(apple_client, "verify_notification", reject)
    response = await apple_ctx.client.post("/api/marketplace/payments/apple/notifications", json={"signedPayload": "bad-apple-signature"})
    assert response.status_code == 400
    assert await apple_ctx.db.scalar(select(func.count()).select_from(AppleNotification)) == 0


@pytest.mark.asyncio
async def test_consumption_uses_current_official_api(apple_cfg, monkeypatch):
    """实际SDK请求构造保持V2字段和100000为100%的单位定义。"""
    calls = []

    def send(transaction_id, request):
        calls.append((transaction_id, request))

    monkeypatch.setattr(apple_client, "_objects", lambda: (None, SimpleNamespace(send_consumption_information=send)))
    await apple_client.send_consumption("123456789", delivered=True, consumed_milli_percent=25000)
    assert calls[0][0] == "123456789"
    request = calls[0][1]
    assert request.customerConsented is True
    assert request.consumptionPercentage == 25000
    assert request.sampleContentProvided is False
    from appstoreserverlibrary.models.RefundPreference import RefundPreference
    assert request.refundPreference == RefundPreference.DECLINE


@pytest.mark.asyncio
async def test_common_billing_alias_and_app_retry_share_one_order_and_balance(apple_ctx, monkeypatch):
    """通知或共同入口先履约，旧 App 路径重试不能建立第二订单或第二钱包。"""
    ctx = apple_ctx
    intent = await apple_service.purchase_intent(ctx.db, ctx.buyer.id, "Production", "coins.600", "shared-intent-key")
    stub_apple(monkeypatch, ctx)
    for path in ("/api/billing/apple/transactions/verify", "/api/marketplace/app/v1/iap/apple/transactions/verify"):
        response = await ctx.client.post(path, json={"signed_transaction_info": "signed-test-transaction", "intent_id": intent["intent_id"]})
        assert response.status_code == 200, response.text
        assert response.json()["balance_fen"] == response.json()["balance_coins"] == 600
        assert response.json()["order_id"] == intent["order_id"]
    assert await ctx.db.scalar(select(func.count()).select_from(Order)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(CoinWallet)) == 0
    order = await ctx.db.get(Order, intent["order_id"])
    assert (order.pay_type, order.status, order.credit_fen, order.amount_fen) == ("apple_iap", "paid", 600, 600)


@pytest.mark.asyncio
async def test_two_real_apple_transactions_cannot_overwrite_one_intent_order(apple_ctx):
    """同一次意向被客户端用于两笔真实付款，分别入账，不能用幂等意向吞掉第二笔。"""
    ctx = apple_ctx
    intent = await apple_service.purchase_intent(ctx.db, ctx.buyer.id, "Production", "coins.600", "two-payments-intent")
    first = await apple_service.apply_verified_transaction(ctx.db, verified_transaction(ctx), intent_id=intent["intent_id"])
    second = await apple_service.apply_verified_transaction(ctx.db, verified_transaction(ctx, transaction_id="second-real-payment"), intent_id=intent["intent_id"])
    assert first.recharge_order_id != second.recharge_order_id
    assert await ctx.db.scalar(select(func.count()).select_from(Order)) == 2
    assert await ctx.db.scalar(select(User.balance_fen).where(User.id == ctx.buyer.id)) == 1200
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == 2


@pytest.mark.asyncio
async def test_shared_gift_package_keeps_credit_and_actual_paid_separate(apple_ctx):
    """与Web相同的赠额不要求币数等于实付款，全部到账按真实付款累计分摊。"""
    ctx = apple_ctx
    ctx.db.add(AppleProduct(product_id="shared.gift", sku_id="topup_99",
        sku_snapshot={"id": "topup_99", "name": "进阶充值", "amount_fen": 99000, "credit_fen": 104000},
        coins=104000, price_fen=99000, enabled=True))
    await ctx.db.flush()
    item = await apple_service.apply_verified_transaction(ctx.db, verified_transaction(ctx,
        transaction_id="gift-package-payment", product_id="shared.gift", amount_fen=99000))
    assert item.coins == 104000 and item.amount_fen == 99000
    order = await ctx.db.get(Order, item.recharge_order_id)
    assert order.credit_fen == 104000 and order.amount_fen == 99000
    allocated = await wallet.consume(ctx.db, ctx.buyer.id, 104000, business_type="ai_task", business_ref="gift-complete-consumption")
    assert sum(row.amount_fen for row in allocated) == 99000
    assert ctx.buyer.balance_fen == 0
