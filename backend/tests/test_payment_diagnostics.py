"""Financial diagnostics expose stable codes, never exception payloads."""
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.services.billing.diagnostics import failure_fields

@pytest.mark.parametrize("exc,expected",[
    (HTTPException(503,{"code":"WALLET_MIGRATION_REQUIRED","message":"secret-token"}),("HTTPException",503,"WALLET_MIGRATION_REQUIRED")),
    (HTTPException(503,{"code":"bad\nsecret-token","message":"secret-token"}),("HTTPException",503,"UNCLASSIFIED")),
    (HTTPException(503,"https://secret-token"),("HTTPException",503,"UNCLASSIFIED")),
    (RuntimeError("password=secret-token"),("RuntimeError","-","UNCLASSIFIED")),
])
def test_safe_fields(exc,expected):
    assert failure_fields(exc)==expected
    assert "secret-token" not in str(failure_fields(exc))

@pytest.mark.asyncio
async def test_wallet_logs_code_and_preserves_http_error(monkeypatch,caplog):
    from app.api.billing import wallet as endpoint
    from app.services.billing import wallet
    from app.config import get_settings
    monkeypatch.setattr(get_settings(),"wallet_environment","Production")
    monkeypatch.setattr(wallet,"enabled",lambda:True)
    monkeypatch.setattr(wallet,"snapshot",AsyncMock(side_effect=wallet.WalletError(
        "WALLET_MIGRATION_REQUIRED","secret-token",503)))
    with caplog.at_level(logging.WARNING,logger="app.api.billing"):
        with pytest.raises(HTTPException) as caught:
            await endpoint(user=SimpleNamespace(id=123),db=None,view="production")
    assert caught.value.status_code==503
    assert caught.value.detail["code"]=="WALLET_MIGRATION_REQUIRED"
    assert "user_id=123 view=production environment=Production" in caplog.text
    assert "code=WALLET_MIGRATION_REQUIRED" in caplog.text
    assert "secret-token" not in caplog.text
