"""Admin-managed Stripe configuration: persistence, redaction, and live use."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest
import pytest_asyncio

from fastapi import FastAPI

from app import config
from app.api import billing as billing_api
from app.api.admin import settings as settings_api
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_settings import AppSettings
from app.services import model_settings, stripe_payments
from tests.conftest import make_user


SETTINGS_URL = "/api/admin/settings/models"
SAVED = {
    "stripe_enabled": True,
    "stripe_secret_key": "sk_test_saved_alpha",
    "stripe_webhook_secret": "whsec_saved_alpha",
    "stripe_frontend_url": "https://frontend.example.test",
}


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """All mutations stay in this test process and are restored afterward."""
    previous_overlay = model_settings.get_overlay_dict()
    previous_snapshot = model_settings.get_routing_snapshot()
    try:
        with monkeypatch.context() as changes:
            changes.setenv("STRIPE_ENABLED", "false")
            changes.setenv("STRIPE_SECRET_KEY", "sk_test_env_fallback")
            changes.setenv("STRIPE_WEBHOOK_SECRET", "whsec_env_fallback")
            changes.setenv("STRIPE_FRONTEND_URL", "https://env.example.test")
            changes.setenv("PUBLIC_BASE_URL", "https://backend.example.test")
            model_settings._refresh_overlay({"flat": {}})
            config.reload_settings()
            yield
    finally:
        model_settings._routing_snapshot = previous_snapshot
        model_settings._refresh_overlay({"flat": previous_overlay})
        config.reload_settings()


@pytest_asyncio.fixture
async def settings_client(db_session, isolated_settings):
    user = await make_user(db_session)
    user.role = "admin"
    await db_session.commit()
    user_id = user.id
    app = FastAPI()
    app.include_router(settings_api.router, prefix="/api/admin")
    app.include_router(billing_api.router, prefix="/api")

    async def override_db():
        yield db_session

    async def override_user():
        return await db_session.get(User, user_id, populate_existing=True)

    app.dependency_overrides[get_db] = override_db
    # Keep the real admin dependency, including its role check.
    app.dependency_overrides[get_current_user] = override_user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://backend.example.test"
    ) as client:
        yield client, user


async def save_stripe(client):
    # Initialize the existing model-channel configuration as the admin page does.
    initial = await client.get(SETTINGS_URL)
    assert initial.status_code == 200, initial.text
    response = await client.patch(SETTINGS_URL, json=SAVED)
    assert response.status_code == 200, response.text
    return response


def assert_redacted(data):
    assert data["stripe_secret_key"] == ""
    assert data["stripe_webhook_secret"] == ""
    serialized = json.dumps(data)
    for secret in ("sk_test_saved_alpha", "whsec_saved_alpha", "sk_test_env_fallback", "whsec_env_fallback"):
        assert secret not in serialized


@pytest.mark.asyncio
async def test_admin_get_reports_env_configuration_without_exposing_keys(settings_client, db_session):
    client, _ = settings_client
    response = await client.get(SETTINGS_URL)
    assert response.status_code == 200
    data = response.json()
    assert_redacted(data)
    assert data["stripe_enabled"] is False
    assert data["has_stripe_secret_key"] is True
    assert data["has_stripe_webhook_secret"] is True
    assert data["stripe_ready"] is False
    assert data["stripe_frontend_url"] == "https://env.example.test"
    assert data["stripe_webhook_url"] == "https://backend.example.test/api/billing/stripe/webhook"
    row = await db_session.get(AppSettings, "default")
    for field in ("stripe_secret_key", "stripe_webhook_secret"):
        assert row.config_json["flat"][field].startswith("enc:")
    assert "sk_test_env_fallback" not in json.dumps(row.config_json)
    assert "whsec_env_fallback" not in json.dumps(row.config_json)


@pytest.mark.asyncio
async def test_saved_stripe_settings_are_encrypted_redacted_and_effective(settings_client, db_session):
    client, _ = settings_client
    response = await save_stripe(client)
    data = response.json()
    assert set(SAVED).issubset(data["applied_fields"])
    assert_redacted(data["settings"])
    assert data["settings"]["stripe_ready"] is True
    assert data["settings"]["has_stripe_secret_key"] is True
    assert data["settings"]["has_stripe_webhook_secret"] is True
    out = (await client.get(SETTINGS_URL)).json()
    assert_redacted(out)
    assert out["stripe_frontend_url"] == SAVED["stripe_frontend_url"]
    row = await db_session.get(AppSettings, "default")
    stored = row.config_json["flat"]
    for field in ("stripe_secret_key", "stripe_webhook_secret"):
        assert stored[field].startswith("enc:")
        assert SAVED[field] not in json.dumps(row.config_json)
        assert getattr(config.get_settings(), field) == SAVED[field]
    assert stripe_payments.is_ready() is True
    assert "stripe" in (await client.get("/api/billing/skus")).json()["pay_types"]


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", None])
async def test_blank_secrets_preserve_existing_encrypted_values(settings_client, db_session, blank):
    client, _ = settings_client
    await save_stripe(client)
    response = await client.patch(SETTINGS_URL, json={"stripe_secret_key": blank, "stripe_webhook_secret": blank})
    assert response.status_code == 200
    assert "stripe_secret_key" not in response.json()["applied_fields"]
    assert "stripe_webhook_secret" not in response.json()["applied_fields"]
    assert config.get_settings().stripe_secret_key == SAVED["stripe_secret_key"]
    assert config.get_settings().stripe_webhook_secret == SAVED["stripe_webhook_secret"]
    row = await db_session.get(AppSettings, "default")
    assert row.config_json["flat"]["stripe_secret_key"].startswith("enc:")
    assert_redacted(response.json()["settings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["stripe_secret_key", "stripe_webhook_secret"])
async def test_explicit_clear_stays_empty_after_reload_and_overrides_environment(settings_client, db_session, field):
    client, _ = settings_client
    await save_stripe(client)
    response = await client.patch(SETTINGS_URL, json={f"clear_{field}": True})
    assert response.status_code == 200
    assert response.json()["settings"][f"has_{field}"] is False
    assert response.json()["settings"]["stripe_ready"] is False
    assert getattr(config.get_settings(), field) == ""
    row = await db_session.get(AppSettings, "default")
    assert row.config_json["flat"][field] == ""
    model_settings._refresh_overlay({"flat": {}})
    config.reload_settings()
    assert getattr(config.get_settings(), field)
    await model_settings.load_model_settings_cache(db_session)
    assert getattr(config.get_settings(), field) == ""
    assert (await client.get(SETTINGS_URL)).json()[f"has_{field}"] is False
    assert "stripe" not in (await client.get("/api/billing/skus")).json()["pay_types"]


@pytest.mark.asyncio
async def test_nonempty_new_keys_win_over_clear_flags(settings_client, db_session):
    client, _ = settings_client
    await save_stripe(client)
    response = await client.patch(SETTINGS_URL, json={
        "stripe_secret_key": "  sk_test_replacement  ", "clear_stripe_secret_key": True,
        "stripe_webhook_secret": "  whsec_replacement  ", "clear_stripe_webhook_secret": True,
    })
    assert response.status_code == 200
    assert config.get_settings().stripe_secret_key == "sk_test_replacement"
    assert config.get_settings().stripe_webhook_secret == "whsec_replacement"
    row = await db_session.get(AppSettings, "default")
    for field in ("stripe_secret_key", "stripe_webhook_secret"):
        assert row.config_json["flat"][field].startswith("enc:")
    assert response.json()["settings"]["stripe_ready"] is True
    assert_redacted(response.json()["settings"])


@pytest.mark.asyncio
async def test_saved_configuration_survives_runtime_cache_reload(settings_client, db_session):
    client, _ = settings_client
    await save_stripe(client)
    model_settings._refresh_overlay({"flat": {}})
    config.reload_settings()
    assert config.get_settings().stripe_secret_key == "sk_test_env_fallback"
    await model_settings.load_model_settings_cache(db_session)
    for field, expected in SAVED.items():
        assert getattr(config.get_settings(), field) == expected
    out = (await client.get(SETTINGS_URL)).json()
    assert out["stripe_ready"] is True
    assert_redacted(out)


@pytest.mark.asyncio
async def test_first_patch_on_empty_settings_database_is_not_lost_or_stored_plaintext(settings_client, db_session):
    client, _ = settings_client
    assert await db_session.get(AppSettings, "default") is None
    response = await client.patch(SETTINGS_URL, json=SAVED)
    assert response.status_code == 200
    for field, expected in SAVED.items():
        assert getattr(config.get_settings(), field) == expected
    row = await db_session.get(AppSettings, "default")
    for field in ("stripe_secret_key", "stripe_webhook_secret"):
        assert row.config_json["flat"][field].startswith("enc:")
    assert_redacted(response.json()["settings"])


def signature(secret, payload):
    timestamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


@pytest.mark.asyncio
async def test_saves_immediately_change_checkout_availability_and_webhook_verification(settings_client):
    client, _ = settings_client
    await save_stripe(client)
    assert "stripe" in (await client.get("/api/billing/skus")).json()["pay_types"]
    assert (await client.patch(SETTINGS_URL, json={"stripe_enabled": False})).status_code == 200
    assert "stripe" not in (await client.get("/api/billing/skus")).json()["pay_types"]
    assert (await client.patch(SETTINGS_URL, json={"stripe_enabled": True, "stripe_webhook_secret": "whsec_rotated"})).status_code == 200
    payload = json.dumps({"id": "evt_settings_test", "object": "event", "type": "customer.created", "data": {"object": {"id": "cus_test"}}}).encode()
    for secret, expected in ((SAVED["stripe_webhook_secret"], 400), ("whsec_rotated", 200)):
        response = await client.post("/api/billing/stripe/webhook", content=payload,
            headers={"stripe-signature": signature(secret, payload), "content-type": "application/json"})
        assert response.status_code == expected
    assert (await client.patch(SETTINGS_URL, json={"clear_stripe_webhook_secret": True})).status_code == 200
    response = await client.post("/api/billing/stripe/webhook", content=payload,
        headers={"stripe-signature": signature("whsec_rotated", payload)})
    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "patch"])
async def test_regular_user_cannot_read_or_modify_stripe_configuration(settings_client, db_session, method):
    client, user = settings_client
    user.role = "user"
    await db_session.commit()
    if method == "get":
        response = await client.get(SETTINGS_URL)
    else:
        response = await client.patch(SETTINGS_URL, json=SAVED)
    assert response.status_code == 403
    assert await db_session.get(AppSettings, "default") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [
    {"stripe_secret_key": "pk_test_not_a_secret"},
    {"stripe_secret_key": "sk_test_with embedded whitespace"},
    {"stripe_webhook_secret": "invalid_webhook_secret"},
    {"stripe_frontend_url": "http://public.example.test"},
    {"stripe_frontend_url": "https://user:password@frontend.example.test"},
    {"stripe_frontend_url": "https://frontend.example.test?next=evil"},
    {"stripe_frontend_url": "https://:443"},
    {"stripe_frontend_url": "https://app.example:99999"},
    {"stripe_frontend_url": "https://app.example/pricing"},
    {"stripe_frontend_url": "http://localhost:0"},
])
async def test_invalid_configuration_is_rejected_without_changing_saved_settings(settings_client, patch):
    client, _ = settings_client
    await save_stripe(client)
    response = await client.patch(SETTINGS_URL, json=patch)
    assert response.status_code == 400
    for value in patch.values():
        assert value not in response.text
    assert config.get_settings().stripe_secret_key == SAVED["stripe_secret_key"]
    assert config.get_settings().stripe_webhook_secret == SAVED["stripe_webhook_secret"]
    assert config.get_settings().stripe_frontend_url == SAVED["stripe_frontend_url"]
