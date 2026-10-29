"""Stripe presentment currencies keep immutable quotes and CNY wallet credit."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app import config
from app.models import Order, WalletLedger
from app.models_settings import AppSettings
from app.services import stripe_payments
from tests.test_stripe_payments import make_order, paid_session
from tests.test_stripe_settings import (
    SETTINGS_URL,
    isolated_settings,
    save_stripe,
    settings_client,
    signature,
)


@pytest.fixture(autouse=True)
def currency_environment(monkeypatch, isolated_settings):
    monkeypatch.setenv("STRIPE_CURRENCY", "cny")
    monkeypatch.setenv("STRIPE_USD_CNY_RATE", "")
    monkeypatch.setenv("STRIPE_HKD_CNY_RATE", "")
    config.reload_settings()


def currency_settings(currency, *, usd="", hkd=""):
    return config.get_settings().model_copy(update={
        "stripe_enabled": True,
        "stripe_secret_key": "sk_test_currency",
        "stripe_webhook_secret": "whsec_currency",
        "stripe_frontend_url": "https://currency.example.test",
        "stripe_currency": currency,
        "stripe_usd_cny_rate": usd,
        "stripe_hkd_cny_rate": hkd,
    })


def quote_fields(value):
    return {key: value[key] for key in ("payment_currency", "payment_amount_minor", "payment_exchange_rate")}


@pytest.mark.parametrize("currency,amount,rate,expected", [
    ("cny", 49000, "", 49000),
    ("usd", 49000, "7", 7000),
    ("usd", 49000, "7.2", 6806),
    ("hkd", 49000, "0.9", 54444),
    ("usd", 5, "2", 3),
    ("hkd", 1, "2", 1),
    ("usd", 1, "0.000001", 1000000),
    ("cny", 99999999, "", 99999999),
])
def test_quote_converts_cny_fen_using_decimal_half_up(currency, amount, rate, expected):
    settings = currency_settings(currency, usd=rate, hkd=rate)
    quote = stripe_payments.quote_payment(amount, settings=settings)
    assert quote == {
        "payment_currency": currency,
        "payment_amount_minor": expected,
        "payment_exchange_rate": "1" if currency == "cny" else rate,
    }


@pytest.mark.parametrize("rate", ["", "0", "-1", "NaN", "Infinity", "-Infinity", "1000000.000001", "0.1234567", "not-a-rate", True])
def test_foreign_currency_requires_a_valid_rate_and_is_not_ready(rate):
    settings = currency_settings("usd", usd=rate)
    assert stripe_payments.is_ready(settings) is False
    with pytest.raises(ValueError):
        stripe_payments.quote_payment(49000, settings=settings)


@pytest.mark.parametrize("currency,amount,rate", [
    ("cny", 0, ""), ("cny", -1, ""), ("cny", 100000000, ""),
    ("usd", 1, "3"), ("usd", 100, "0.000001"), ("eur", 49000, "7"),
])
def test_quote_rejects_zero_negative_or_unrepresentable_payment(currency, amount, rate):
    with pytest.raises(ValueError):
        stripe_payments.quote_payment(amount, settings=currency_settings(currency, usd=rate))


def test_cny_quote_does_not_require_foreign_currency_rates():
    settings = currency_settings("cny", usd="invalid", hkd="")
    assert stripe_payments.is_ready(settings) is True
    assert stripe_payments.quote_payment(49000, settings=settings) == {
        "payment_currency": "cny", "payment_amount_minor": 49000, "payment_exchange_rate": "1",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("value,canonical", [(7.2, "7.2"), (7, "7"), (" 7.200000 ", "7.2"), ("0.000001", "0.000001"), ("1000000", "1000000")])
async def test_admin_saves_numeric_or_string_rate_as_canonical_decimal(settings_client, db_session, value, canonical):
    client, _ = settings_client
    await save_stripe(client)
    response = await client.patch(SETTINGS_URL, json={
        "stripe_currency": "usd", "stripe_usd_cny_rate": value, "stripe_hkd_cny_rate": "0.900000",
    })
    assert response.status_code == 200, response.text
    out = response.json()["settings"]
    assert out["stripe_currency"] == "usd"
    assert out["stripe_usd_cny_rate"] == canonical
    assert out["stripe_hkd_cny_rate"] == "0.9"
    if canonical in {"7", "7.2"}:
        assert out["stripe_ready"] is True
    row = await db_session.get(AppSettings, "default")
    assert row.config_json["flat"]["stripe_usd_cny_rate"] == canonical
    assert config.get_settings().stripe_usd_cny_rate == canonical
    assert (await client.get(SETTINGS_URL)).json()["stripe_usd_cny_rate"] == canonical


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", ["0", "-7", "NaN", "Infinity", "0.1234567", "1000001"])
async def test_admin_rejects_invalid_rate_without_mutating_current_config(settings_client, rate):
    client, _ = settings_client
    await save_stripe(client)
    response = await client.patch(SETTINGS_URL, json={"stripe_usd_cny_rate": rate})
    assert response.status_code in {400, 422}
    assert config.get_settings().stripe_currency == "cny"
    assert config.get_settings().stripe_usd_cny_rate == ""


@pytest.mark.asyncio
async def test_missing_selected_rate_disables_checkout_until_configured(settings_client, monkeypatch):
    client, _ = settings_client
    await save_stripe(client)
    response = await client.patch(SETTINGS_URL, json={"stripe_currency": "usd", "stripe_usd_cny_rate": ""})
    assert response.status_code == 200
    assert response.json()["settings"]["stripe_ready"] is False
    assert "stripe" not in (await client.get("/api/billing/skus")).json()["pay_types"]
    create = AsyncMock()
    monkeypatch.setattr(stripe_payments, "create_checkout_session", create)
    response = await client.post("/api/billing/orders", json={"sku_id": "topup_49", "pay_type": "stripe"})
    assert response.status_code == 503
    create.assert_not_awaited()
    response = await client.patch(SETTINGS_URL, json={"stripe_usd_cny_rate": "7.2"})
    assert response.status_code == 200
    assert response.json()["settings"]["stripe_ready"] is True
    assert "stripe" in (await client.get("/api/billing/skus")).json()["pay_types"]


@pytest.mark.asyncio
@pytest.mark.parametrize("currency,rate,amount", [("usd", "7.2", 6806), ("hkd", "0.9", 54444)])
async def test_order_creation_and_reads_expose_server_side_currency_snapshot(settings_client, db_session, monkeypatch, currency, rate, amount):
    client, user = settings_client
    await save_stripe(client)
    assert (await client.patch(SETTINGS_URL, json={"stripe_currency": currency, f"stripe_{currency}_cny_rate": rate})).status_code == 200
    expected = {"payment_currency": currency, "payment_amount_minor": amount, "payment_exchange_rate": rate}
    skus = (await client.get("/api/billing/skus")).json()["skus"]
    sku = next(item for item in skus if item["id"] == "topup_49")
    assert sku["stripe_quote"] == expected
    before = user.balance_fen

    async def create_checkout(*, order, sku_name):
        # The snapshot is persisted before the network request begins.
        row = (await db_session.execute(select(Order).where(Order.out_trade_no == order.out_trade_no))).scalar_one()
        assert row.id is not None
        assert (row.payment_currency, row.payment_amount_minor, row.payment_exchange_rate) == (currency, amount, rate)
        return {"id": f"cs_test_{currency}", "url": "https://checkout.stripe.com/c/pay/currency", "expires_at": int(time.time()) + 1860}

    monkeypatch.setattr(stripe_payments, "create_checkout_session", AsyncMock(side_effect=create_checkout))
    response = await client.post("/api/billing/orders", json={
        "sku_id": "topup_49", "pay_type": "stripe",
        "payment_currency": "cny", "payment_amount_minor": 1, "payment_exchange_rate": "9999",
    })
    assert response.status_code == 200, response.text
    order = response.json()
    assert quote_fields(order) == expected
    assert order["amount_fen"] == 49000
    assert order["credit_fen"] == 49000
    assert user.balance_fen == before
    # Later rate changes must not relabel or reprice the saved payment.
    assert (await client.patch(SETTINGS_URL, json={"stripe_currency": "cny", f"stripe_{currency}_cny_rate": "8"})).status_code == 200
    detail = (await client.get(f"/api/billing/orders/{order['out_trade_no']}")).json()
    listed = (await client.get("/api/billing/orders")).json()["orders"][0]
    assert quote_fields(detail) == expected
    assert quote_fields(listed) == expected


@pytest.mark.asyncio
async def test_checkout_uses_saved_quote_after_current_currency_and_rate_change(settings_client, monkeypatch):
    client, _ = settings_client
    await save_stripe(client)
    assert (await client.patch(SETTINGS_URL, json={"stripe_currency": "hkd", "stripe_hkd_cny_rate": "0.8", "stripe_usd_cny_rate": "8"})).status_code == 200
    order = Order(out_trade_no="PF_CURRENCY_SNAPSHOT", user_id=42, amount_fen=49000, credit_fen=52000, pay_type="stripe",
        payment_currency="usd", payment_amount_minor=6806, payment_exchange_rate="7.2")
    create = AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {
        "id": "cs_test_currency", "url": "https://checkout.stripe.com/c/pay/currency",
    }))
    sdk = MagicMock(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create))))
    sdk.__aenter__.return_value = sdk
    monkeypatch.setattr(stripe_payments, "_client", lambda: sdk)
    await stripe_payments.create_checkout_session(order=order, sku_name="test")
    price = create.await_args.args[0]["line_items"][0]["price_data"]
    assert price["currency"] == "usd"
    assert price["unit_amount"] == 6806


async def post_paid_session(client, session):
    payload = json.dumps({"id": "evt_currency_paid", "object": "event", "type": "checkout.session.completed", "data": {"object": session}}).encode()
    return await client.post("/api/billing/stripe/webhook", content=payload, headers={
        "content-type": "application/json",
        "stripe-signature": signature(config.get_settings().stripe_webhook_secret, payload),
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("currency,amount,rate", [("usd", 6806, "7.2"), ("hkd", 54444, "0.9")])
async def test_foreign_paid_callback_uses_snapshot_and_credits_cny_wallet_once(settings_client, db_session, currency, amount, rate):
    client, user = settings_client
    await save_stripe(client)
    before = user.balance_fen
    order = await make_order(db_session, user, payment_currency=currency, payment_amount_minor=amount, payment_exchange_rate=rate)
    # The currently selected currency/rate may change or become unconfigured.
    assert (await client.patch(SETTINGS_URL, json={"stripe_currency": "hkd", "stripe_hkd_cny_rate": "", "stripe_usd_cny_rate": "8"})).status_code == 200
    session = paid_session(order)
    session.update(currency=currency, amount_total=amount)
    for _ in range(2):
        response = await post_paid_session(client, session)
        assert response.status_code == 200, response.text
    await db_session.refresh(user)
    assert user.balance_fen == before + 52000
    assert order.status == "paid"
    ledger = (await db_session.execute(select(WalletLedger).where(WalletLedger.ref_id == order.out_trade_no))).scalars().all()
    assert len(ledger) == 1
    assert ledger[0].delta_fen == 52000


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("currency", "cny"), ("currency", "hkd"), ("amount_total", 49000), ("amount_total", 6805)])
async def test_callback_cannot_replace_saved_payment_currency_or_amount(settings_client, db_session, field, value):
    client, user = settings_client
    await save_stripe(client)
    before = user.balance_fen
    order = await make_order(db_session, user, payment_currency="usd", payment_amount_minor=6806, payment_exchange_rate="7.2")
    session = paid_session(order)
    session.update(currency="usd", amount_total=6806)
    session[field] = value
    response = await post_paid_session(client, session)
    assert response.status_code == 400
    await db_session.refresh(user)
    await db_session.refresh(order)
    assert user.balance_fen == before
    assert order.status == "pending"


@pytest.mark.asyncio
async def test_legacy_null_snapshot_remains_cny_after_current_currency_changes(settings_client, db_session):
    client, user = settings_client
    await save_stripe(client)
    order = await make_order(db_session, user)
    assert order.payment_currency is None
    assert (await client.patch(SETTINGS_URL, json={"stripe_currency": "usd", "stripe_usd_cny_rate": "7.2"})).status_code == 200
    expected = {"payment_currency": "cny", "payment_amount_minor": 49000, "payment_exchange_rate": "1"}
    detail = (await client.get(f"/api/billing/orders/{order.out_trade_no}")).json()
    assert quote_fields(detail) == expected
    before = user.balance_fen
    response = await post_paid_session(client, paid_session(order))
    assert response.status_code == 200, response.text
    await db_session.refresh(user)
    assert user.balance_fen == before + 52000
    assert order.status == "paid"
