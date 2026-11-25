from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from starlette.requests import Request
from starlette.responses import Response

@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,expected",[
    ("GET","/api/admin/settings/models",200),
    ("PATCH","/api/admin/settings/models",503),
    ("POST","/api/billing/orders",503),
    ("GET","/epay/notify",503),
    ("POST","/api/admin/settings/wallet-migration/cancel",200),
])
async def test_maintenance_settings_access(monkeypatch,method,path,expected):
    from app import wallet_cutover_middleware as m
    db=SimpleNamespace(execute=AsyncMock(),rollback=AsyncMock())
    @asynccontextmanager
    async def session(): yield db
    monkeypatch.setattr(m,"BarrierSession",session)
    monkeypatch.setattr(m,"AsyncSessionLocal",session)
    monkeypatch.setattr(m.cutover,"runtime_state",AsyncMock(return_value={"paused":True}))
    monkeypatch.setattr(m.cutover,"sync_runtime",AsyncMock())
    next_call=AsyncMock(return_value=Response(status_code=200))
    result=await m.middleware(Request({"type":"http","method":method,"path":path,"headers":[]}),next_call)
    assert result.status_code==expected
    assert next_call.await_count==(1 if expected==200 else 0)

@pytest.mark.asyncio
async def test_settings_maintenance_read_never_bootstraps(monkeypatch):
    from app.services import model_settings as m
    from app.services.billing import wallet_cutover
    monkeypatch.setattr(wallet_cutover,"runtime_state",AsyncMock(return_value={"paused":True}))
    compose=AsyncMock(side_effect=AssertionError("write-capable compose invoked"))
    monkeypatch.setattr(m,"_compose_runtime_state",compose)
    monkeypatch.setattr(m,"_load_channels",AsyncMock(return_value=[]))
    db=SimpleNamespace(get=AsyncMock(return_value=None))
    result=await m.get_admin_model_settings(db)
    assert result.source=="env"
    compose.assert_not_awaited()
