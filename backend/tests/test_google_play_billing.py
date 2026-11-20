"""Google receipt and real ORM payment invariants; no real store requests."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import User, Order, WalletLedger
from app.models_teams import Team
from app.models_wallet import WalletBase, WalletAccount, WalletFundingLot, WalletDebt
from app.marketplace import google_service as service, google_client
from app.marketplace.google_models import (GoogleSettings, GoogleAccount, GoogleIntent, GooglePurchase,
    GoogleWork, GoogleVoid, GoogleAudit, GoogleNotification, GoogleCursor)
from app.marketplace.google_config import DEFAULT_PRODUCTS, SettingsInput, save
from app.marketplace.google_api import IntentInput, VerifyInput
from app.marketplace.service import now


@pytest.fixture
def ctx(monkeypatch):
    from app.services.billing.wallet_schema import register_models
    register_models()
    engine = create_engine("sqlite:///:memory:")
    for model in (User, Team, Order, WalletLedger):
        model.__table__.create(engine)
    WalletBase.metadata.create_all(engine)
    for model in (GoogleSettings, GoogleAccount, GoogleIntent, GooglePurchase, GoogleWork, GoogleVoid, GoogleAudit, GoogleNotification, GoogleCursor):
        model.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    class DB:
        bind = engine
        def add(self, row): session.add(row)
        async def scalar(self, stmt): return session.scalar(stmt)
        async def scalars(self, stmt): return session.scalars(stmt)
        async def execute(self, stmt): return session.execute(stmt)
        async def get(self, model, key): return session.get(model, key)
        async def flush(self): session.flush()
        async def commit(self): session.commit()
        async def rollback(self): session.rollback()
        async def run_sync(self, callback): return callback(session)
        async def connection(self):
            class Connection:
                async def run_sync(self, callback): return callback(session.connection())
            return Connection()
    monkeypatch.setattr(get_settings(), "unified_wallet_enabled", True)
    monkeypatch.setattr(get_settings(), "wallet_environment", "Production")
    config = dict(package_name="com.deep.printfilm", purchasing_enabled=True, test_user_ids=[],
        rtdn_audience="https://notify.example", rtdn_service_account="push@example.invalid",
        products=[{**DEFAULT_PRODUCTS[0], "credit_fen": 10000, "reference_amount_fen": 10000}])
    session.add(GoogleSettings(key="billing", version=1, credentials="unused", config=config))
    user = User(email="google@test.invalid", hashed_password="unused", balance_fen=0, frozen_fen=0)
    session.add(user)
    session.flush()
    session.add(WalletAccount(user_id=user.id, environment="Production", migration_reference="new-account"))
    session.commit()
    monkeypatch.setattr(service, "available", lambda *_: True)
    try:
        yield NS(session=session, db=DB(), user=user, config=config)
    finally:
        session.close()
        engine.dispose()


async def checkout(ctx, key="checkout-test-123"):
    body = IntentInput(package_name="com.deep.printfilm", product_id="printfilm_credits_trial", sku_id="topup_10", idempotency_key=key)
    result = await service.create_intent(ctx.db, ctx.user.id, body)
    await ctx.db.commit()
    return body, result


def proof(intent, **changes):
    return {"purchaseState": 0, "quantity": 1, "purchaseTimeMillis": str(int(now().timestamp() * 1000)),
        "obfuscatedExternalAccountId": intent["obfuscated_account_id"],
        "obfuscatedExternalProfileId": intent["obfuscated_profile_id"], "orderId": "GPA.example", **changes}


async def apply(ctx, intent, purchase=None, token="raw-google-secret"):
    return await service.apply_proof(ctx.db, "com.deep.printfilm", "printfilm_credits_trial", token,
        purchase or proof(intent), ctx.config, user_id=ctx.user.id)


@pytest.mark.asyncio
async def test_intent_retries_account_stability_and_conflicting_key(ctx):
    body, first = await checkout(ctx)
    second = await service.create_intent(ctx.db, ctx.user.id, body)
    assert first == second
    assert first["credit_fen"] == 10000 and len(first["obfuscated_account_id"]) == 64
    _, third = await checkout(ctx, "checkout-new-123")
    assert third["obfuscated_account_id"] == first["obfuscated_account_id"]
    assert third["obfuscated_profile_id"] != first["obfuscated_profile_id"]
    # Request conflict must win even if the product is still available.
    row = ctx.session.scalar(select(GoogleIntent).where(GoogleIntent.intent_key == first["intent_id"]))
    row.request_hash = "different"
    with pytest.raises(HTTPException) as error:
        await service.create_intent(ctx.db, ctx.user.id, body)
    assert error.value.detail["code"] == "GOOGLE_IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_committed_credit_repeat_verify_and_encrypted_retry(ctx, monkeypatch):
    _, intent = await checkout(ctx)
    body = VerifyInput(package_name="com.deep.printfilm", product_id="printfilm_credits_trial", purchase_token="raw-google-secret")
    query = AsyncMock(return_value=proof(intent))
    monkeypatch.setattr(google_client, "query", query)
    first = await service.verify(ctx.db, ctx.user.id, body)
    assert first["status"] == "credited" and first["consume_purchase"] is True
    assert first["purchase_token_sha256"] == service.digest(body.purchase_token)
    assert ctx.user.balance_fen == 10000
    second = await service.verify(ctx.db, ctx.user.id, body)
    assert second["status"] == "already_credited" and ctx.user.balance_fen == 10000
    assert ctx.session.scalar(select(func.count()).select_from(WalletFundingLot)) == 1
    assert ctx.session.scalar(select(func.count()).select_from(GoogleWork)) == 1
    work = ctx.session.scalar(select(GoogleWork))
    assert body.purchase_token not in work.token_secret
    lot = ctx.session.scalar(select(WalletFundingLot))
    assert lot.settlement_status == "pending_fx" and lot.total_amount_fen == 0
    order = ctx.session.scalar(select(Order))
    assert order.pay_type == "google_play" and order.status == "paid" and order.payment_currency is None
    from app.services.stripe_payments import payment_snapshot
    assert payment_snapshot(order)["payment_currency"] is None


@pytest.mark.asyncio
async def test_pending_then_paid_and_consume_state(ctx):
    _, intent = await checkout(ctx)
    result = await apply(ctx, intent, proof(intent, purchaseState=2))
    assert result["status"] == "pending" and not result["consume_purchase"] and ctx.user.balance_fen == 0
    await ctx.db.commit()
    result = await apply(ctx, intent, proof(intent, consumptionState=1))
    assert result["credited"] and ctx.user.balance_fen == 10000
    assert ctx.session.scalar(select(GooglePurchase.consumed))


@pytest.mark.asyncio
async def test_restore_never_claims_unknown_owner_or_hint(ctx):
    _, intent = await checkout(ctx)
    for changes in ({"obfuscatedExternalProfileId": "unknown"}, {"obfuscatedExternalAccountId": "wrong"}):
        with pytest.raises(HTTPException) as error:
            await apply(ctx, intent, proof(intent, **changes))
        assert error.value.detail["code"] == "GOOGLE_ACCOUNT_MISMATCH"
    with pytest.raises(HTTPException):
        await service.apply_proof(ctx.db, "com.deep.printfilm", "printfilm_credits_trial", "raw", proof(intent),
            ctx.config, user_id=ctx.user.id + 1)
    with pytest.raises(HTTPException):
        await service.apply_proof(ctx.db, "com.deep.printfilm", "printfilm_credits_trial", "raw", proof(intent),
            ctx.config, user_id=ctx.user.id, hints={"intent_id": "wrong"})
    assert ctx.user.balance_fen == 0


@pytest.mark.asyncio
async def test_expired_intent_paid_purchase_still_delivered(ctx):
    _, intent = await checkout(ctx)
    row = ctx.session.scalar(select(GoogleIntent))
    row.expires_at = now() - timedelta(hours=1)
    await ctx.db.commit()
    result = await apply(ctx, intent)
    assert result["credited"] and ctx.user.balance_fen == 10000


@pytest.mark.asyncio
async def test_test_purchase_rejected_in_production_and_wrong_quantity(ctx):
    _, intent = await checkout(ctx)
    with pytest.raises(HTTPException) as error:
        await apply(ctx, intent, proof(intent, purchaseType=0))
    assert error.value.detail["code"] == "GOOGLE_TEST_PURCHASE_ISOLATED"
    for quantity in (2, True, "1", 0):
        with pytest.raises(HTTPException):
            await apply(ctx, intent, proof(intent, quantity=quantity))
    assert ctx.user.balance_fen == 0


@pytest.mark.asyncio
async def test_refund_is_terminal_and_preserves_ai_debt(ctx):
    from app.services.billing import wallet
    _, intent = await checkout(ctx)
    await apply(ctx, intent)
    await wallet.consume(ctx.db, ctx.user.id, 4000, business_type="ai_task", business_ref="123")
    await ctx.db.commit()
    result = await apply(ctx, intent, proof(intent, purchaseState=1))
    await ctx.db.commit()
    assert result["status"] == "refunded" and not result["consume_purchase"]
    assert ctx.user.balance_fen == 0 and ctx.session.scalar(select(WalletDebt.units)) == 4000
    result = await apply(ctx, intent)  # delayed purchase notification cannot undo a refund
    assert result["status"] == "refunded" and ctx.user.balance_fen == 0
    assert ctx.session.scalar(select(func.count()).select_from(WalletDebt)) == 1


@pytest.mark.asyncio
async def test_void_before_verify_never_credits(ctx):
    _, intent = await checkout(ctx)
    ctx.session.add(GoogleVoid(package_name="com.deep.printfilm", token_hash=service.digest("raw-google-secret")))
    await ctx.db.commit()
    result = await apply(ctx, intent)
    assert result["status"] == "refunded" and not result["consume_purchase"] and ctx.user.balance_fen == 0
    assert ctx.session.scalar(select(func.count()).select_from(WalletFundingLot)) == 0


@pytest.mark.asyncio
async def test_failed_credit_transaction_rolls_back(ctx):
    _, intent = await checkout(ctx)
    await apply(ctx, intent)
    await ctx.db.rollback()
    assert ctx.session.get(User, ctx.user.id).balance_fen == 0
    assert ctx.session.scalar(select(func.count()).select_from(GooglePurchase)) == 0
    assert ctx.session.scalar(select(func.count()).select_from(WalletFundingLot)) == 0


@pytest.mark.asyncio
async def test_registered_product_keeps_frozen_credit_and_rejects_overwrite(ctx):
    data = deepcopy(ctx.config)
    data.update(version=1, reason="核对谷歌商品", purchasing_enabled=False)
    data["products"][0]["credit_fen"] = 10001
    with pytest.raises(HTTPException) as error:
        await save(ctx.db, SettingsInput(**data), ctx.user.id)
    assert error.value.detail["code"] == "GOOGLE_PRODUCT_IMMUTABLE"
    data["products"][0]["credit_fen"] = 10000
    await save(ctx.db, SettingsInput(**data), ctx.user.id)
    await ctx.db.commit()
    assert ctx.session.scalar(select(GoogleSettings.version)) == 2
    assert ctx.session.scalar(select(func.count()).select_from(GoogleAudit)) == 1


@pytest.mark.asyncio
async def test_google_orders_not_expired_by_epay_timeout(ctx):
    from app.services.billing.settlement import close_expired_pending_orders
    await checkout(ctx)
    order = ctx.session.scalar(select(Order))
    order.created_at = now() - timedelta(days=1)
    await ctx.db.commit()
    assert await close_expired_pending_orders(ctx.db, user_id=ctx.user.id) == 0
    assert order.status == "pending"


@pytest.mark.asyncio
async def test_api_contract_auth_headers_and_real_success(ctx, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from app.database import get_db
    from app.deps import get_current_user
    from app.marketplace import google_api
    app = FastAPI()
    app.include_router(google_api.router, prefix="/api/marketplace/app/v1")
    app.include_router(google_api.admin_router)
    async def db_override(): yield ctx.db
    app.dependency_overrides[get_db] = db_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        base = "/api/marketplace/app/v1/iap/google"
        assert (await client.get(base + "/skus")).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: ctx.user
        assert (await client.get("/api/admin/settings/google-play")).status_code == 403
        catalog = (await client.get(base + "/skus")).json()
        assert catalog["skus"][0]["credit_fen"] == 10000 and catalog["purchasing_enabled"] is True
        request = dict(package_name="com.deep.printfilm", product_id="printfilm_credits_trial", sku_id="topup_10", idempotency_key="api-checkout-123")
        assert (await client.post(base + "/purchase-intents", json=request, headers={"Idempotency-Key": "wrong"})).status_code == 409
        response = await client.post(base + "/purchase-intents", json=request, headers={"Idempotency-Key": request["idempotency_key"]})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        intent = response.json()
        assert "+00:00" in intent["expires_at"] or intent["expires_at"].endswith("Z")
        monkeypatch.setattr(google_client, "query", AsyncMock(return_value=proof(intent)))
        verify = dict(package_name="com.deep.printfilm", product_id="printfilm_credits_trial", purchase_token="api-purchase-token", quantity=1)
        result = await client.post(base + "/transactions/verify", json=verify,
            headers={"Idempotency-Key": "google-" + service.digest(verify["purchase_token"])})
        assert result.status_code == 200 and result.json()["consume_purchase"] is True
        assert ctx.user.balance_fen == 10000
        ctx.user.role = "admin"
        config = (await client.get("/api/admin/settings/google-play")).json()
        assert config["has_credentials"] is True and "credentials" not in config


@pytest.mark.asyncio
async def test_commit_failure_never_authorizes_consume(ctx, monkeypatch):
    _, intent = await checkout(ctx)
    body = VerifyInput(package_name="com.deep.printfilm", product_id="printfilm_credits_trial", purchase_token="raw-google-secret")
    monkeypatch.setattr(google_client, "query", AsyncMock(return_value=proof(intent)))
    monkeypatch.setattr(ctx.db, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
    with pytest.raises(RuntimeError, match="commit failed"):
        await service.verify(ctx.db, ctx.user.id, body)
    await ctx.db.rollback()
    assert ctx.user.balance_fen == 0


@pytest.mark.asyncio
async def test_worker_retries_consume_only_after_credit_commit(ctx, monkeypatch):
    from app.marketplace import google_runtime as runtime
    _, intent = await checkout(ctx)
    await apply(ctx, intent)
    await ctx.db.commit()
    class Factory:
        async def __aenter__(self): return ctx.db
        async def __aexit__(self, *exc):
            if exc[0]: await ctx.db.rollback()
    monkeypatch.setattr(runtime, "AsyncSessionLocal", Factory)
    monkeypatch.setattr(google_client, "query", AsyncMock(return_value=proof(intent)))
    consume = AsyncMock(side_effect=RuntimeError("timeout"))
    monkeypatch.setattr(google_client, "consume", consume)
    assert await runtime.work_once()
    assert ctx.user.balance_fen == 10000
    work = ctx.session.scalar(select(GoogleWork))
    assert work.attempts == 1 and not ctx.session.scalar(select(GooglePurchase.consumed))
    # Client consumed while offline; retry confirms upstream state without double consumption.
    work.next_attempt_at = now() - timedelta(seconds=1)
    await ctx.db.commit()
    monkeypatch.setattr(google_client, "query", AsyncMock(return_value=proof(intent, consumptionState=1)))
    assert await runtime.work_once()
    assert ctx.session.scalar(select(GooglePurchase.consumed))
    assert ctx.user.balance_fen == 10000 and consume.await_count == 1


@pytest.mark.asyncio
async def test_push_jwt_exact_identity_and_audience(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from jose import jwt
    import time
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(google_client, "_certs", (time.time() + 3600, {"test-key": public}))
    config = {"rtdn_audience": "https://notify.example", "rtdn_service_account": "push@example.invalid"}
    claims = dict(iss="https://accounts.google.com", aud=config["rtdn_audience"], email=config["rtdn_service_account"],
        email_verified=True, iat=int(time.time()), exp=int(time.time()) + 300)
    token = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "test-key"})
    await google_client.verify_push(token, config)
    for change in ({"aud": "https://evil.example"}, {"email": "other@example.invalid"}, {"email_verified": False}, {"iss": "evil"}):
        token = jwt.encode({**claims, **change}, private, algorithm="RS256", headers={"kid": "test-key"})
        with pytest.raises(HTTPException) as error:
            await google_client.verify_push(token, config)
        assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_google_source_reconciliation_retains_proof(ctx):
    from app.services.billing.wallet_migration import build_report
    _, intent = await checkout(ctx)
    await apply(ctx, intent)
    await ctx.db.commit()
    rows, plans = await build_report(ctx.db, "Production")
    assert rows[0]["status"] == "already_migrated" and not plans
    assert rows[0]["pending_source_count"] == 1
    ctx.session.scalar(select(GooglePurchase)).credit_fen += 1
    await ctx.db.commit()
    rows, _ = await build_report(ctx.db, "Production")
    assert rows[0]["status"] == "blocked"


@pytest.mark.asyncio
async def test_rtdn_authenticated_deduplicated_and_queues_offline_purchase(ctx, monkeypatch):
    import base64
    import json
    import httpx
    from fastapi import FastAPI
    from app.database import get_db
    from app.marketplace import google_api
    app = FastAPI()
    app.include_router(google_api.public_router)
    async def db_override(): yield ctx.db
    app.dependency_overrides[get_db] = db_override
    verify = AsyncMock()
    monkeypatch.setattr(google_client, "verify_push", verify)
    payload = dict(packageName="com.deep.printfilm", oneTimeProductNotification={
        "notificationType": 1, "purchaseToken": "offline-purchase", "sku": "printfilm_credits_trial"})
    envelope = {"message": {"messageId": "message-1", "data": base64.b64encode(json.dumps(payload).encode()).decode()}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/billing/google/notifications"
        assert (await client.post(path, json=envelope)).status_code == 401
        for _ in range(2):
            response = await client.post(path, json=envelope, headers={"Authorization": "Bearer signed-oidc"})
            assert response.status_code == 200
    assert ctx.session.scalar(select(func.count()).select_from(GoogleNotification)) == 1
    assert ctx.session.scalar(select(func.count()).select_from(GoogleWork)) == 1
    assert ctx.user.balance_fen == 0  # authenticated RTDN still isn't a payment proof
