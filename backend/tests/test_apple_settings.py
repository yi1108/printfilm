"""Admin Apple configuration, isolated database and generated test credentials."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from test_stripe_settings import settings_client, isolated_settings, SETTINGS_URL
from app.models_settings import AppSettings
from app.marketplace.app_settings import get_app_settings
from app.marketplace.apple_configuration import validate_material


@pytest.fixture
def credentials():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test only CA")])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
    return {
        "apple_bundle_id": "test.printfilm.app", "apple_app_id": 123,
        "apple_issuer_id": "d38ad1bc-c7a4-45bf-a1f0-2b7ad3a87643", "apple_key_id": "ABCDE12345",
        "apple_private_key": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
        "apple_root_certificates": certificate.public_bytes(serialization.Encoding.PEM).decode(),
        "apple_iap_enabled": False,
    }


@pytest.fixture(autouse=True)
def no_runtime(monkeypatch):
    from app.marketplace import app_bootstrap
    async def noop():
        return None
    monkeypatch.setattr(app_bootstrap, "start_app_services", noop)


@pytest.mark.asyncio
async def test_saved_credentials_encrypted_redacted_and_live(settings_client, db_session, credentials):
    client, _ = settings_client
    response = await client.patch(SETTINGS_URL, json=credentials)
    assert response.status_code == 200
    assert response.json()["settings"]["apple_private_key"] == ""
    assert response.json()["settings"]["has_apple_private_key"]
    row = await db_session.get(AppSettings, "default")
    assert row.config_json["flat"]["apple_private_key"].startswith("enc:")
    assert credentials["apple_private_key"] not in json.dumps(row.config_json)
    assert get_app_settings().apple_private_key == credentials["apple_private_key"].strip()
    status = await client.get("/api/admin/settings/apple/status")
    assert status.status_code == 200
    assert status.json()["configured"]
    assert status.json()["live_payment_verified"] is False
    assert status.json()["notification_url"].endswith("/api/billing/apple/notifications")
    assert credentials["apple_private_key"] not in status.text
    # Blank retains the key, explicit clear survives cache reload and disables readiness.
    assert (await client.patch(SETTINGS_URL, json={"apple_private_key": ""})).status_code == 200
    assert get_app_settings().apple_private_key
    assert (await client.patch(SETTINGS_URL, json={"clear_apple_private_key": True})).status_code == 200
    assert get_app_settings().apple_private_key == ""
    assert not (await client.get("/api/admin/settings/apple/status")).json()["configured"]


@pytest.mark.asyncio
async def test_invalid_material_is_not_persisted(settings_client):
    client, _ = settings_client
    response = await client.patch(SETTINGS_URL, json={"apple_private_key": "invalid-secret-material"})
    assert response.status_code == 400
    assert "invalid-secret-material" not in response.text
    response = await client.patch(SETTINGS_URL, json={"apple_iap_enabled": True})
    assert response.status_code == 400
    assert not get_app_settings().apple_iap_enabled


@pytest.mark.asyncio
async def test_status_requires_admin(settings_client):
    client, user = settings_client
    user.role = "user"
    assert (await client.get("/api/admin/settings/apple/status")).status_code == 403


def test_certificate_and_key_validation(credentials):
    validate_material(credentials["apple_private_key"], credentials["apple_root_certificates"])
    with pytest.raises(ValueError):
        validate_material("", credentials["apple_private_key"])


@pytest.mark.asyncio
async def test_environment_can_be_saved_and_restored(settings_client):
    client, _ = settings_client
    for environment in ("Sandbox", "Production"):
        response = await client.patch(SETTINGS_URL, json={"apple_environment": environment})
        assert response.status_code == 200
        assert response.json()["settings"]["apple_environment"] == environment
        assert get_app_settings().apple_environment == environment
        assert (await client.get("/api/admin/settings/apple/status")).json()["environment"] == environment
    assert (await client.patch(SETTINGS_URL, json={"apple_environment": "invalid"})).status_code == 422


@pytest.mark.asyncio
async def test_enable_prepares_schema_and_starts_runtime(settings_client, credentials, monkeypatch):
    from app.marketplace import app_bootstrap
    calls = []
    async def ensure():
        calls.append("schema")
        return []
    async def start():
        calls.append("runtime")
    monkeypatch.setattr(app_bootstrap, "ensure_schema", ensure)
    monkeypatch.setattr(app_bootstrap, "start_app_services", start)
    client, _ = settings_client
    response = await client.patch(SETTINGS_URL, json={**credentials, "apple_iap_enabled": True})
    assert response.status_code == 200
    assert calls == ["schema", "runtime"]
    assert get_app_settings().apple_iap_enabled
    assert (await client.patch(SETTINGS_URL, json={"apple_iap_enabled": False})).status_code == 200
    assert not get_app_settings().apple_iap_enabled
    assert (await client.get("/api/admin/settings/apple/status")).json()["configured"]


def test_explicit_clear_does_not_revive_legacy_file(monkeypatch, tmp_path, credentials):
    from app import config
    from app.services import model_settings
    private = tmp_path / "private.p8"
    private.write_text(credentials["apple_private_key"])
    monkeypatch.setenv("MARKETPLACE_APPLE_PRIVATE_KEY_PATH", str(private))
    model_settings._refresh_overlay({"flat": {"apple_private_key": ""}})
    config.reload_settings()
    assert get_app_settings().apple_private_key == ""
    assert get_app_settings().apple_private_key_path == ""
