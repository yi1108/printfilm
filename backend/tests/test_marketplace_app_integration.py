"""主路由、开关、迁移保护和播放访问日志的集成边界。"""
import logging
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
import pytest

from app.marketplace import app_bootstrap
from app.marketplace.app_logging import PlaybackAccessFilter, safe_request_path
from app.marketplace.bootstrap import install


def test_app_routes_registered_without_overriding_web_contracts():
    """校验实际挂载而非仅测试孤立路由模块。"""
    app = FastAPI()
    install(app)
    paths = app.openapi()["paths"]
    prefix = "/api/marketplace/app/v1"
    for suffix in ("/capabilities", "/feed", "/works/{work_id}", "/series/{series_id}",
                   "/series/{series_id}/episodes", "/me/entitlements", "/me/wallet",
                   "/me/wallet/entries", "/unlocks", "/me/unlock-orders", "/coin-products",
                   "/iap/apple/purchase-intents", "/iap/apple/transactions/verify",
                   "/playback-sessions", "/playback-sessions/{token}/index.m3u8",
                   "/playback-sessions/{token}/segments/{segment_id}", "/reports"):
        assert prefix + suffix in paths
    assert "/api/marketplace/payments/apple/notifications" in paths
    assert "/api/marketplace/payments/epay/notify" in paths
    assert "/api/admin/marketplace/app/products" in paths
    assert "/api/marketplace/works" in paths
    manifest = paths[prefix + "/playback-sessions/{token}/index.m3u8"]["get"]["responses"]["200"]
    assert "application/vnd.apple.mpegurl" in manifest["content"]
    segment = paths[prefix + "/playback-sessions/{token}/segments/{segment_id}"]["get"]["responses"]
    assert "Location" in segment["302"]["headers"]
    pairs = [(route.path, method) for route in app.routes if hasattr(route, "methods") for method in route.methods]
    assert len(pairs) == len(set(pairs))


def test_main_application_exposes_app_feed_and_capabilities():
    """验证实际运行的主应用，避免离线文档和孤立测试有路由而线上没有。"""
    from app.main import app
    paths = app.openapi()["paths"]
    assert "/api/marketplace/app/v1/feed" in paths
    assert "/api/marketplace/app/v1/capabilities" in paths
    assert "/api/marketplace/works" in paths


@pytest.mark.asyncio
@pytest.mark.parametrize("opened", [False, True])
async def test_feed_returns_business_switch_error_or_empty_list_instead_of_missing_route(monkeypatch, opened):
    """用用户实际请求验证挂载；无可见内容应为空列表，关闭才返回稳定业务码。"""
    from app.database import get_db
    from app.marketplace import app_access
    from app.marketplace.dependencies import optional_user

    async def ready():
        return True

    class EmptyDatabase:
        """只模拟空查询结果，不连接或写入业务库。"""
        async def execute(self, statement):
            return SimpleNamespace(all=lambda: [])

    async def database():
        yield EmptyDatabase()

    async def visitor():
        return None

    monkeypatch.setattr(app_bootstrap, "schema_ready", ready)
    monkeypatch.setattr(app_access, "app_open", lambda: opened)
    app = FastAPI()
    install(app)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[optional_user] = visitor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/marketplace/app/v1/feed?q=&category=&content_type=all&limit=20&cursor=")
    if opened:
        assert response.status_code == 200, response.text
        assert response.json() == {"items": [], "has_more": False, "next_cursor": None}
    else:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "MARKETPLACE_APP_UNAVAILABLE"


@pytest.mark.asyncio
async def test_missing_schema_is_explicit_but_capabilities_still_available(monkeypatch):
    """能力发现无需建表；未迁移服务不能意外查询业务库。"""
    monkeypatch.setattr(app_bootstrap, "_schema_ready", False)
    monkeypatch.setattr(app_bootstrap, "_schema_checked_at", 0)
    calls = []

    async def missing():
        calls.append(True)
        return ["marketplace_coin_wallets"]

    monkeypatch.setattr(app_bootstrap, "verify_schema", missing)
    app = FastAPI()
    install(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        capability = await client.get("/api/marketplace/app/v1/capabilities")
        assert capability.status_code == 200
        assert not calls
        response = await client.get("/api/marketplace/app/v1/me/wallet")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "MARKETPLACE_APP_SCHEMA_REQUIRED"


@pytest.mark.asyncio
async def test_apple_financial_runtime_survives_disabled_entry(monkeypatch):
    """已有交易处理独立于App和新充值展示开关。"""
    from app.marketplace import app_settings, apple_client, apple_runtime
    monkeypatch.setattr(app_settings, "get_app_settings", lambda: SimpleNamespace(enabled=False, apple_iap_enabled=False))
    monkeypatch.setattr(apple_client, "apple_configured", lambda: True)
    called = []

    async def ready():
        called.append("schema")
        return []

    async def start():
        called.append("runtime")

    monkeypatch.setattr(app_bootstrap, "ensure_schema", ready)
    monkeypatch.setattr(apple_runtime, "start_apple_runtime", start)
    await app_bootstrap.start_app_services()
    assert called == ["schema", "runtime"]


def test_admin_setting_controls_app_switch(monkeypatch):
    """系统设置里的开关决定 App 是否开放，不读取容器里的市场总开关。"""
    from app.config import get_settings
    from app.marketplace.app_settings import is_app_enabled
    monkeypatch.setattr(get_settings(), "marketplace_app_enabled", False)
    assert is_app_enabled() is False
    monkeypatch.setattr(get_settings(), "marketplace_app_enabled", True)
    assert is_app_enabled() is True


@pytest.mark.asyncio
async def test_app_activation_fails_when_startup_migration_is_incomplete(monkeypatch):
    """启动自动迁移后仍缺结构时，不能伪造 App 已就绪。"""
    from app.config import get_settings
    from app.marketplace import app_settings, apple_client
    monkeypatch.setattr(get_settings(), "marketplace_app_enabled", True)
    monkeypatch.setattr(app_settings, "get_app_settings", lambda: SimpleNamespace(enabled=False, apple_iap_enabled=False))
    monkeypatch.setattr(apple_client, "apple_configured", lambda: False)

    async def missing():
        return ["marketplace_coin_wallets"]

    monkeypatch.setattr(app_bootstrap, "ensure_schema", missing)
    with pytest.raises(RuntimeError, match="自动迁移后仍不完整"):
        await app_bootstrap.start_app_services()


def test_playback_access_log_never_contains_token_or_query():
    """同时覆盖业务日志路径与Uvicorn访问日志五元组。"""
    secret = "sample-secret-playback-token"
    path = f"/api/marketplace/app/v1/playback-sessions/{secret}/segments/1?Signature=secret"
    assert safe_request_path(path).endswith("/[redacted]/segments/1")
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", path, "1.1", 302), None)
    assert PlaybackAccessFilter().filter(record)
    assert secret not in record.getMessage()
    assert "Signature" not in record.getMessage()
    assert safe_request_path("/api/projects/12") == "/api/projects/12"
