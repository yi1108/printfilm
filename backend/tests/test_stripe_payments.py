"""Stripe Checkout: signed callbacks, wallet accounting, and account isolation."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import billing as billing_api
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Order, User, WalletLedger
from app.services import stripe_payments
from tests.conftest import _resolve_test_database_url, make_user


@pytest.fixture
def stripe_config(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_unit")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_unit")
    monkeypatch.setattr(settings, "stripe_frontend_url", "https://app.example.test")
    return settings


@pytest_asyncio.fixture
async def client(db_session, stripe_config):
    """Exercise real routes without application startup or external requests."""
    user = await make_user(db_session, balance_fen=500)
    await db_session.commit()
    app = FastAPI()
    app.include_router(billing_api.router, prefix="/api")

    async def db_override():
        yield db_session

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://app.example.test"
    ) as api_client:
        yield api_client, user


async def make_order(db, user, **overrides):
    values = dict(
        out_trade_no=f"PFTEST{uuid.uuid4().hex}",
        user_id=user.id,
        sku_id="topup_49",
        amount_fen=49000,
        credit_fen=52000,
        pay_type="stripe",
        trade_no=f"cs_test_{uuid.uuid4().hex}",
        status="pending",
    )
    values.update(overrides)
    order = Order(**values)
    db.add(order)
    await db.commit()
    return order


def paid_session(order):
    return {
        "id": order.trade_no,
        "object": "checkout.session",
        "mode": "payment",
        "status": "complete",
        "payment_status": "paid",
        "amount_total": order.amount_fen,
        "currency": "cny",
        "client_reference_id": order.out_trade_no,
        "metadata": {
            "out_trade_no": order.out_trade_no,
            "user_id": str(order.user_id),
            "sku_id": order.sku_id,
        },
        "payment_intent": "pi_test_paid",
        "livemode": False,
    }


def signed_payload(session, event_type="checkout.session.completed", *, timestamp=None):
    payload = json.dumps({
        "id": f"evt_test_{uuid.uuid4().hex}",
        "object": "event",
        "type": event_type,
        "livemode": False,
        "data": {"object": session},
    }).encode()
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(
        b"whsec_unit", str(timestamp).encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    return payload, f"t={timestamp},v1={digest}"


async def webhook(api_client, session, event_type="checkout.session.completed"):
    payload, signature = signed_payload(session, event_type)
    return await api_client.post(
        "/api/billing/stripe/webhook", content=payload,
        headers={"content-type": "application/json", "stripe-signature": signature},
    )


@pytest.mark.asyncio
async def test_stripe_skus_require_enabled_and_complete_configuration(client, monkeypatch, stripe_config):
    api_client, _ = client
    assert "stripe" in (await api_client.get("/api/billing/skus")).json()["pay_types"]
    for key, value in (("stripe_enabled", False), ("stripe_secret_key", ""), ("stripe_webhook_secret", "")):
        old = getattr(stripe_config, key)
        monkeypatch.setattr(stripe_config, key, value)
        assert "stripe" not in (await api_client.get("/api/billing/skus")).json()["pay_types"]
        monkeypatch.setattr(stripe_config, key, old)


@pytest.mark.asyncio
async def test_create_checkout_persists_server_priced_order(client, db_session, monkeypatch):
    api_client, user = client
    session = {"id": "cs_test_created", "url": "https://checkout.stripe.com/c/pay/test", "expires_at": int(time.time()) + 1800}
    create = AsyncMock(return_value=session)
    monkeypatch.setattr(stripe_payments, "create_checkout_session", create)
    response = await api_client.post(
        "/api/billing/orders", json={"sku_id": "topup_49", "pay_type": "stripe", "amount_fen": 1, "credit_fen": 999999}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    order = (await db_session.execute(select(Order).where(Order.out_trade_no == data["out_trade_no"]))).scalar_one()
    assert (order.user_id, order.amount_fen, order.credit_fen) == (user.id, 49000, 49000)
    assert order.status == "pending"
    assert order.trade_no == session["id"]
    assert data["pay_mode"] == "redirect"
    assert data["payurl"] == session["url"]
    assert data["expire_seconds"] >= 1700
    assert user.balance_fen == 500
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_stripe_rejects_direct_order_creation(client, monkeypatch, stripe_config):
    api_client, _ = client
    monkeypatch.setattr(stripe_config, "stripe_enabled", False)
    create = AsyncMock()
    monkeypatch.setattr(stripe_payments, "create_checkout_session", create)
    response = await api_client.post("/api/billing/orders", json={"sku_id": "topup_49", "pay_type": "stripe"})
    assert response.status_code == 503
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkout_creation_uses_trusted_price_urls_and_idempotency(stripe_config, monkeypatch):
    order = Order(out_trade_no="PF_SERVER_ORDER", user_id=42, amount_fen=12345, credit_fen=24680, pay_type="stripe", sku_id="snapshot")
    create = AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {
        "id": "cs_test_sdk", "url": "https://checkout.stripe.com/c/pay/sdk", "expires_at": 2000001860,
    }))
    sdk = MagicMock(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create))))
    sdk.__aenter__.return_value = sdk
    monkeypatch.setattr(stripe_payments, "_client", lambda: sdk)
    monkeypatch.setattr(stripe_payments.time, "time", lambda: 2000000000)
    result = await stripe_payments.create_checkout_session(order=order, sku_name="测试充值")
    assert result["id"] == "cs_test_sdk"
    args, kwargs = create.await_args
    params = args[0]
    assert params["mode"] == "payment"
    assert "payment_method_types" not in params
    assert re.fullmatch(r"printfilm-wallet-[a-z]{8}", params["integration_identifier"])
    assert params["expires_at"] == 2000001860
    assert params["adaptive_pricing"] == {"enabled": False}
    assert params["line_items"][0]["price_data"]["unit_amount"] == 12345
    assert params["line_items"][0]["price_data"]["currency"] == "cny"
    assert params["line_items"][0]["quantity"] == 1
    assert params["client_reference_id"] == order.out_trade_no
    assert params["metadata"] == {"out_trade_no": order.out_trade_no, "user_id": "42"}
    success = urlsplit(params["success_url"])
    assert success.netloc == "app.example.test"
    assert success.path == "/pricing"
    assert parse_qs(success.query) == {"payment": ["success"], "order": [order.out_trade_no], "session_id": ["{CHECKOUT_SESSION_ID}"]}
    assert parse_qs(urlsplit(params["cancel_url"]).query) == {"payment": ["cancelled"], "order": [order.out_trade_no]}
    assert kwargs["options"]["idempotency_key"] == f"wallet-checkout:{order.out_trade_no}"
    await stripe_payments.create_checkout_session(order=order, sku_name="测试充值")
    assert create.await_args.args[0]["integration_identifier"] == params["integration_identifier"]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://checkout.stripe.com/pay", "https://checkout.stripe.com.evil.test/pay", "https://evil.test/pay", ""])
async def test_checkout_rejects_invalid_gateway_redirect(stripe_config, monkeypatch, url):
    order = Order(out_trade_no="PF_SERVER_ORDER", user_id=42, amount_fen=49000)
    create = AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {"id": "cs_test_sdk", "url": url}))
    sdk = MagicMock(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create))))
    sdk.__aenter__.return_value = sdk
    monkeypatch.setattr(stripe_payments, "_client", lambda: sdk)
    with pytest.raises(ValueError):
        await stripe_payments.create_checkout_session(order=order, sku_name="test")


@pytest.mark.parametrize("url", ["http://public.example.test", "https://user:password@app.example.test", "https://app.example.test?next=evil", "https://app.example.test#fragment"])
def test_checkout_availability_rejects_unsafe_configured_return_url(stripe_config, monkeypatch, url):
    monkeypatch.setattr(stripe_config, "stripe_frontend_url", url)
    assert stripe_payments.is_ready() is False


@pytest.mark.asyncio
async def test_gateway_failure_closes_order_without_credit_or_error_leak(client, db_session, monkeypatch):
    api_client, user = client
    monkeypatch.setattr(stripe_payments, "create_checkout_session", AsyncMock(side_effect=ValueError("sk_test_do_not_expose")))
    response = await api_client.post("/api/billing/orders", json={"sku_id": "topup_49", "pay_type": "stripe"})
    assert response.status_code == 503
    assert "sk_test_do_not_expose" not in response.text
    order = (await db_session.execute(select(Order).where(Order.user_id == user.id))).scalar_one()
    assert order.status == "closed"
    assert order.trade_no is None
    await db_session.refresh(user)
    assert user.balance_fen == 500


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["checkout.session.completed", "checkout.session.async_payment_succeeded"])
async def test_paid_webhook_credits_snapshot_once(client, db_session, event_type):
    api_client, user = client
    order = await make_order(db_session, user)
    session = paid_session(order)
    for _ in range(2):
        response = await webhook(api_client, session, event_type)
        assert response.status_code == 200, response.text
    await db_session.refresh(user)
    assert user.balance_fen == 52500
    assert order.status == "paid"
    assert order.paid_at is not None
    rows = (await db_session.execute(select(WalletLedger).where(WalletLedger.ref_id == order.out_trade_no))).scalars().all()
    assert len(rows) == 1
    assert (rows[0].kind, rows[0].delta_fen) == ("topup", 52000)


@pytest.mark.asyncio
async def test_completed_then_async_success_are_idempotent(client, db_session):
    api_client, user = client
    order = await make_order(db_session, user)
    session = paid_session(order)
    assert (await webhook(api_client, session)).status_code == 200
    assert (await webhook(api_client, session, "checkout.session.async_payment_succeeded")).status_code == 200
    await db_session.refresh(user)
    assert user.balance_fen == 52500


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("amount_total", 1), ("currency", "usd"), ("id", "cs_test_wrong"),
    ("client_reference_id", "PF_WRONG"), ("mode", "subscription"),
])
async def test_mismatched_session_never_credits(client, db_session, field, value):
    api_client, user = client
    order = await make_order(db_session, user)
    session = paid_session(order)
    session[field] = value
    response = await webhook(api_client, session)
    assert response.status_code >= 400
    await db_session.refresh(user)
    await db_session.refresh(order)
    assert user.balance_fen == 500
    assert order.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{}, {"out_trade_no": "PF_WRONG"}, {"user_id": "9999999"}])
async def test_mismatched_or_missing_metadata_never_credits(client, db_session, metadata):
    api_client, user = client
    order = await make_order(db_session, user)
    session = paid_session(order)
    session["metadata"] = metadata
    response = await webhook(api_client, session)
    assert response.status_code >= 400
    await db_session.refresh(user)
    assert user.balance_fen == 500


@pytest.mark.asyncio
async def test_stripe_webhook_cannot_credit_epay_order(client, db_session):
    api_client, user = client
    order = await make_order(db_session, user, pay_type="alipay")
    response = await webhook(api_client, paid_session(order))
    assert response.status_code >= 400
    await db_session.refresh(user)
    await db_session.refresh(order)
    assert user.balance_fen == 500
    assert order.status == "pending"


@pytest.mark.asyncio
async def test_epay_webhook_cannot_credit_stripe_order(client, db_session, monkeypatch):
    api_client, user = client
    order = await make_order(db_session, user)
    monkeypatch.setattr(billing_api.epay, "verify", lambda params: True)
    response = await api_client.get("/api/billing/epay/notify", params={
        "out_trade_no": order.out_trade_no, "trade_no": "epay_123", "money": "490.00", "trade_status": "TRADE_SUCCESS",
    })
    assert response.status_code >= 400
    await db_session.refresh(user)
    assert user.balance_fen == 500
    assert order.status == "pending"


@pytest.mark.asyncio
async def test_unpaid_session_waits_for_async_success(client, db_session):
    api_client, user = client
    order = await make_order(db_session, user)
    session = paid_session(order)
    session["payment_status"] = "unpaid"
    assert (await webhook(api_client, session)).status_code == 200
    await db_session.refresh(user)
    assert user.balance_fen == 500
    assert order.status == "pending"
    session["payment_status"] = "paid"
    assert (await webhook(api_client, session, "checkout.session.async_payment_succeeded")).status_code == 200
    await db_session.refresh(user)
    assert user.balance_fen == 52500


@pytest.mark.asyncio
async def test_late_paid_webhook_credits_closed_order(client, db_session):
    api_client, user = client
    order = await make_order(db_session, user, status="closed")
    assert (await webhook(api_client, paid_session(order))).status_code == 200
    await db_session.refresh(user)
    assert user.balance_fen == 52500
    assert order.status == "paid"


@pytest.mark.asyncio
async def test_disabling_new_checkouts_does_not_lose_paid_webhooks(client, db_session, monkeypatch, stripe_config):
    api_client, user = client
    order = await make_order(db_session, user)
    monkeypatch.setattr(stripe_config, "stripe_enabled", False)
    assert (await webhook(api_client, paid_session(order))).status_code == 200
    await db_session.refresh(user)
    assert user.balance_fen == 52500
    assert order.status == "paid"


@pytest.mark.asyncio
async def test_expiry_callback_closes_pending_but_cannot_revert_paid(client, db_session):
    api_client, user = client
    order = await make_order(db_session, user)
    session = paid_session(order)
    session.update(status="expired", payment_status="unpaid")
    assert (await webhook(api_client, session, "checkout.session.expired")).status_code == 200
    assert order.status == "closed"
    session.update(status="complete", payment_status="paid")
    assert (await webhook(api_client, session)).status_code == 200
    assert (await webhook(api_client, session, "checkout.session.expired")).status_code == 200
    assert order.status == "paid"
    await db_session.refresh(user)
    assert user.balance_fen == 52500


@pytest.mark.asyncio
async def test_stripe_order_does_not_expire_after_epay_five_minutes(client, db_session):
    api_client, user = client
    order = await make_order(db_session, user, created_at=datetime.now(timezone.utc) - timedelta(minutes=6))
    response = await api_client.get(f"/api/billing/orders/{order.out_trade_no}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_unknown_events_are_acknowledged_without_wallet_changes(client, db_session):
    api_client, user = client
    order = await make_order(db_session, user)
    assert (await webhook(api_client, paid_session(order), "customer.created")).status_code == 200
    await db_session.refresh(user)
    assert user.balance_fen == 500
    assert order.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("signature_kind", ["missing", "wrong", "stale", "tampered"])
async def test_invalid_signature_never_reaches_fulfillment(client, monkeypatch, signature_kind):
    api_client, _ = client
    payload, signature = signed_payload({}, timestamp=int(time.time()) - 1000 if signature_kind == "stale" else None)
    if signature_kind == "missing":
        signature = ""
    elif signature_kind == "wrong":
        signature = f"t={int(time.time())},v1=bad"
    elif signature_kind == "tampered":
        payload += b" "
    fulfill = AsyncMock()
    monkeypatch.setattr(stripe_payments, "fulfill_checkout", fulfill)
    response = await api_client.post(
        "/api/billing/stripe/webhook", content=payload,
        headers={"stripe-signature": signature, "content-type": "application/json"},
    )
    assert response.status_code == 400
    fulfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_users_cannot_read_or_close_order(client, db_session):
    api_client, user = client
    other = await make_user(db_session)
    order = await make_order(db_session, other)
    assert (await api_client.get(f"/api/billing/orders/{order.out_trade_no}")).status_code == 404
    assert (await api_client.post(f"/api/billing/orders/{order.out_trade_no}/close")).status_code == 404
    assert order.status == "pending"
    assert user.balance_fen == 500


@pytest.mark.asyncio
async def test_close_stripe_order_expires_gateway_session_first(client, db_session, monkeypatch):
    api_client, user = client
    order = await make_order(db_session, user)

    async def expire(session_id):
        assert session_id == order.trade_no
        assert order.status == "pending"

    expire_mock = AsyncMock(side_effect=expire)
    monkeypatch.setattr(stripe_payments, "expire_checkout_session", expire_mock)
    response = await api_client.post(f"/api/billing/orders/{order.out_trade_no}/close")
    assert response.status_code == 200
    assert order.status == "closed"
    expire_mock.assert_awaited_once_with(order.trade_no)
    await db_session.refresh(user)
    assert user.balance_fen == 500


@pytest.mark.asyncio
async def test_close_does_not_locally_cancel_already_completed_checkout(client, db_session, monkeypatch):
    api_client, user = client
    order = await make_order(db_session, user)
    monkeypatch.setattr(stripe_payments, "expire_checkout_session", AsyncMock(side_effect=ValueError("already complete")))
    response = await api_client.post(f"/api/billing/orders/{order.out_trade_no}/close")
    assert response.status_code == 409
    assert order.status == "pending"
    assert (await webhook(api_client, paid_session(order))).status_code == 200
    await db_session.refresh(user)
    assert user.balance_fen == 52500


@pytest.mark.asyncio
async def test_order_cannot_close_while_checkout_creation_in_flight(client, db_session, monkeypatch):
    api_client, user = client
    order = await make_order(db_session, user, trade_no=None)
    expire = AsyncMock()
    monkeypatch.setattr(stripe_payments, "expire_checkout_session", expire)
    response = await api_client.post(f"/api/billing/orders/{order.out_trade_no}/close")
    assert response.status_code == 409
    assert order.status == "pending"
    expire.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [("pending", 200), ("closed", 200), ("paid", 400)])
async def test_epay_order_close_keeps_existing_behavior(client, db_session, monkeypatch, status, expected):
    api_client, user = client
    order = await make_order(db_session, user, pay_type="alipay", status=status)
    expire = AsyncMock()
    monkeypatch.setattr(stripe_payments, "expire_checkout_session", expire)
    response = await api_client.post(f"/api/billing/orders/{order.out_trade_no}/close")
    assert response.status_code == expected
    assert order.status == ("paid" if status == "paid" else "closed")
    expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_gateway_session_can_expire_after_checkout_disabled_and_transport_closes(stripe_config, monkeypatch):
    monkeypatch.setattr(stripe_config, "stripe_enabled", False)
    expire = AsyncMock()
    sdk = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(expire_async=expire))))
    transport = SimpleNamespace(close_async=AsyncMock())
    monkeypatch.setattr(stripe_payments.stripe, "HTTPXClient", lambda **kwargs: transport)
    monkeypatch.setattr(stripe_payments.stripe, "StripeClient", lambda *args, **kwargs: sdk)
    await stripe_payments.expire_checkout_session("cs_test_expire")
    expire.assert_awaited_once_with("cs_test_expire")
    transport.close_async.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("same_order", [True, False])
async def test_concurrent_callbacks_keep_wallet_accounting_atomic(db_session, stripe_config, same_order):
    """Real independent PostgreSQL transactions must serialize order/wallet locks."""
    test_url, _ = _resolve_test_database_url(get_settings().database_url)
    engine = create_async_engine(test_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = None
    try:
        async with sessions() as setup:
            user = await make_user(setup, balance_fen=500)
            user_id = user.id
            orders = [await make_order(setup, user) for _ in range(1 if same_order else 4)]
            payloads = [paid_session(order) for order in orders]

        async def deliver(session_data):
            async with sessions() as db:
                await stripe_payments.fulfill_checkout(db, session_data)
                await db.commit()

        await asyncio.gather(*(deliver(payloads[index % len(payloads)]) for index in range(8)))
        async with sessions() as verify:
            user = await verify.get(User, user_id)
            assert user.balance_fen == 500 + 52000 * len(orders)
            ledger = (await verify.execute(select(WalletLedger).where(WalletLedger.user_id == user_id))).scalars().all()
            assert len(ledger) == len(orders)
            assert sorted(row.balance_after for row in ledger) == [500 + 52000 * index for index in range(1, len(orders) + 1)]
    finally:
        if user_id is not None:
            async with sessions() as cleanup:
                await cleanup.execute(delete(WalletLedger).where(WalletLedger.user_id == user_id))
                await cleanup.execute(delete(Order).where(Order.user_id == user_id))
                await cleanup.execute(delete(User).where(User.id == user_id))
                await cleanup.commit()
        await engine.dispose()
