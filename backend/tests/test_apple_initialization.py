"""Real SDK construction and redacted diagnostics, with no Apple network calls."""
import logging

import pytest
from fastapi import HTTPException

from app.marketplace import apple_client, apple_configuration
from app.marketplace.app_settings import MarketplaceAppSettings
from test_apple_settings import credentials


@pytest.fixture
def cfg(credentials, monkeypatch):
    config = MarketplaceAppSettings(_env_file=None, **credentials, apple_environment="Sandbox")
    monkeypatch.setattr(apple_client, "get_app_settings", lambda: config)
    monkeypatch.setattr(apple_client, "require_apple_configured", lambda: None)
    apple_client._official_objects.cache_clear()
    yield config
    apple_client._official_objects.cache_clear()


@pytest.mark.parametrize("environment", ["Sandbox", "Production"])
def test_real_sdk_accepts_admin_uploaded_private_key(cfg, environment):
    cfg.apple_environment = environment
    verifier, client = apple_client._objects()
    from appstoreserverlibrary.api_client import AppStoreServerAPIClient
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
    assert isinstance(verifier, SignedDataVerifier)
    assert isinstance(client, AppStoreServerAPIClient)
    assert apple_client._objects() == (verifier, client)


@pytest.mark.parametrize("stage,error_type,reason", [
    ("credential_material", PermissionError, "file_access_denied"),
    ("verifier", ValueError, "invalid_argument_value"),
    ("api_client", TypeError, "invalid_argument_type"),
])
def test_initialization_failure_logs_stage_without_sdk_message(cfg, monkeypatch, caplog, stage, error_type, reason):
    from appstoreserverlibrary import api_client, signed_data_verifier
    secret_message = "private-key-secret token-secret https://secret.example/path?signature=secret"

    def fail(*args, **kwargs):
        raise error_type(secret_message + cfg.apple_private_key)

    if stage == "credential_material":
        monkeypatch.setattr(apple_configuration, "material", fail)
    elif stage == "verifier":
        monkeypatch.setattr(signed_data_verifier, "SignedDataVerifier", fail)
    else:
        monkeypatch.setattr(api_client, "AppStoreServerAPIClient", fail)
    with caplog.at_level(logging.ERROR, logger=apple_client.__name__):
        with pytest.raises(HTTPException) as error:
            apple_client._objects()
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "MARKETPLACE_PAYMENT_UNAVAILABLE"
    records = [record for record in caplog.records if record.name == apple_client.__name__]
    assert len(records) == 1
    assert f"stage={stage}" in caplog.text
    assert "environment=Sandbox" in caplog.text
    assert f"error_type={error_type.__name__}" in caplog.text
    assert f"reason={reason}" in caplog.text
    assert records[0].exc_info is None
    for forbidden in (secret_message, cfg.apple_private_key, cfg.apple_key_id, cfg.apple_issuer_id):
        assert forbidden not in caplog.text
        assert forbidden not in str(error.value.detail)


def test_environment_failure_is_reported_without_echoing_bad_value(cfg, caplog):
    cfg.apple_environment = "sensitive-invalid-environment"
    with caplog.at_level(logging.ERROR, logger=apple_client.__name__):
        with pytest.raises(HTTPException):
            apple_client._objects()
    assert "stage=environment" in caplog.text
    assert "environment=invalid" in caplog.text
    assert "sensitive-invalid-environment" not in caplog.text
