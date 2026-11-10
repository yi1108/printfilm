"""Language selects a server quote, never a browser-supplied payment amount."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models import Order
from app.services import stripe_payments
from tests.test_stripe_settings import isolated_settings, settings_client, SETTINGS_URL, save_stripe
from tests.test_stripe_currency import quote_fields
from tests.test_stripe_payments import make_order


@pytest.mark.asyncio
async def test_language_mode_quotes_cny_and_usd_from_one_admin_rate(settings_client):
    client, _ = settings_client
    await save_stripe(client)
    response = await client.patch(SETTINGS_URL, json={"stripe_currency": "auto", "stripe_usd_cny_rate": "7.2"})
    assert response.status_code == 200
    assert response.json()["settings"]["stripe_ready"] is True
    for language, currency, amount, rate in [("zh", "cny", 49000, "1"), ("en", "usd", 6999, "7.2")]:
        data = (await client.get(f"/api/billing/skus?language={language}")).json()
        assert "stripe" in data["pay_types"]
        sku = next(s for s in data["skus"] if s["id"] == "topup_49")
        assert quote_fields(sku["stripe_quote"]) == {"payment_currency": currency, "payment_amount_minor": amount, "payment_exchange_rate": rate}


@pytest.mark.asyncio
async def test_missing_usd_rate_only_disables_english_stripe(settings_client, monkeypatch):
    client, _ = settings_client
    await save_stripe(client)
    saved = await client.patch(SETTINGS_URL, json={"stripe_currency": "auto", "stripe_usd_cny_rate": ""})
    assert saved.json()["settings"]["stripe_ready"] is False
    zh = (await client.get("/api/billing/skus?language=zh")).json()
    en = (await client.get("/api/billing/skus?language=en")).json()
    assert "stripe" in zh["pay_types"]
    assert "stripe" not in en["pay_types"]
    assert en["stripe_unavailable_reason"] == "usd_rate_missing"
    assert all("stripe_quote" not in s for s in en["skus"])
    create = AsyncMock()
    monkeypatch.setattr(stripe_payments, "create_checkout_session", create)
    response = await client.post("/api/billing/orders", json={"sku_id": "topup_49", "pay_type": "stripe", "language": "en"})
    assert response.status_code == 503
    create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("language,currency,amount", [("zh", "cny", 49000), ("en", "usd", 6999)])
async def test_order_uses_language_and_ignores_client_amount_then_remains_fixed(settings_client, db_session, monkeypatch, language, currency, amount):
    client, _ = settings_client
    await save_stripe(client)
    await client.patch(SETTINGS_URL, json={"stripe_currency": "auto", "stripe_usd_cny_rate": "7.2"})
    create = AsyncMock(return_value={"id": "cs_test_language", "url": "https://checkout.stripe.com/c/pay/language"})
    monkeypatch.setattr(stripe_payments, "create_checkout_session", create)
    response = await client.post("/api/billing/orders", json={"sku_id": "topup_49", "pay_type": "stripe", "language": language, "payment_currency": "hkd", "payment_amount_minor": 1})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["payment_currency"] == currency
    assert result["payment_amount_minor"] == amount
    assert result["credit_fen"] == 49000
    order = (await db_session.execute(select(Order).where(Order.out_trade_no == result["out_trade_no"]))).scalar_one()
    assert order.payment_currency == currency
    await client.patch(SETTINGS_URL, json={"stripe_usd_cny_rate": "8", "stripe_currency": "cny"})
    saved = (await client.get(f"/api/billing/orders/{order.out_trade_no}")).json()
    assert (saved["payment_currency"], saved["payment_amount_minor"]) == (currency, amount)


@pytest.mark.asyncio
async def test_language_default_is_chinese_and_invalid_languages_are_rejected(settings_client, monkeypatch):
    client, _ = settings_client
    await save_stripe(client)
    await client.patch(SETTINGS_URL, json={"stripe_currency": "auto", "stripe_usd_cny_rate": "7.2"})
    data = (await client.get("/api/billing/skus")).json()
    assert data["skus"][0]["stripe_quote"]["payment_currency"] == "cny"
    assert (await client.get("/api/billing/skus?language=usd")).status_code == 422
    assert (await client.post("/api/billing/orders", json={"sku_id": "topup_49", "pay_type": "stripe", "language": "usd"})).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("currency,locale", [("cny", "zh"), ("usd", "en")])
async def test_checkout_fixes_currency_and_matching_ui_language(settings_client, db_session, monkeypatch, currency, locale):
    client, user = settings_client
    await save_stripe(client)
    await client.patch(SETTINGS_URL, json={"stripe_currency": "auto", "stripe_usd_cny_rate": "7.2"})
    order = await make_order(db_session, user, payment_currency=currency, payment_amount_minor=49000, payment_exchange_rate="1")
    create = AsyncMock(return_value=SimpleNamespace(to_dict=lambda: {"id": "cs_test_lang", "url": "https://checkout.stripe.com/c/pay/lang"}))
    sdk = MagicMock()
    sdk.__aenter__ = AsyncMock(return_value=SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create)))))
    sdk.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(stripe_payments, "_client", lambda: sdk)
    await stripe_payments.create_checkout_session(order=order, sku_name="test")
    params = create.call_args.args[0]
    assert params["locale"] == locale
    assert params["adaptive_pricing"] == {"enabled": False}
    assert params["line_items"][0]["price_data"]["currency"] == currency
