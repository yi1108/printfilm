
"""HTTP coverage for client identity hints; no real database or Apple calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from app.api import billing
from app.database import get_db
from app.deps import get_current_user
from app.marketplace import apple_api, apple_recharge, apple_service, app_bootstrap
from app.marketplace.app_settings import MarketplaceAppSettings


@pytest.fixture
def config(monkeypatch):
    cfg = MarketplaceAppSettings(_env_file=None, apple_bundle_id="com.example.global",
        apple_app_id=1, apple_domestic_bundle_id="com.qianzhi.deep.app01", apple_domestic_app_id=2)
    monkeypatch.setattr(apple_api, "get_app_settings", lambda: cfg)
    return cfg


@pytest.mark.asyncio
async def test_http_headers_select_catalog_and_order_without_query(config, monkeypatch):
    app = FastAPI()
    app.include_router(billing.router, prefix="/api")
    app.include_router(apple_api.router, prefix="/api/marketplace/app/v1")
    db = SimpleNamespace(commit=AsyncMock())
    async def database(): yield db
    async def actor(): return SimpleNamespace(id=10)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = actor
    monkeypatch.setattr(app_bootstrap, "require_schema", AsyncMock())
    monkeypatch.setattr(apple_api, "purchasing_enabled_for_app", AsyncMock(return_value=True))
    async def catalog(db, edition):
        return [{"id": "topup_10", "reference_price_fen": 10000, "product_id": edition + ".product"}]
    monkeypatch.setattr(apple_recharge, "list_recharge_products", catalog)
    async def find(db, sku, edition):
        return SimpleNamespace(product_id=edition + ".product")
    monkeypatch.setattr(apple_recharge, "find_product_for_sku", find)
    intent = AsyncMock(return_value={"order_id": 1})
    monkeypatch.setattr(apple_service, "purchase_intent", intent)
    headers = {"X-App-Edition": "domestic", "X-App-Bundle-ID": "com.qianzhi.deep.app01"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/api/billing/skus?channel=apple_iap", "/api/marketplace/app/v1/coin-products"):
            result = await client.get(path, headers=headers)
            assert result.status_code == 200, result.text
            assert result.headers["cache-control"] == "no-store"
            assert "X-App-Bundle-ID" in result.headers["vary"]
            assert result.json()["app_edition"] == "domestic"
            assert result.json()["items"][0]["product_id"] == "domestic.product"
        result = await client.get("/api/billing/skus?channel=apple_iap")
        assert result.json()["app_edition"] == "international"
        result = await client.get("/api/billing/skus?channel=apple_iap&app_edition=international", headers=headers)
        assert result.status_code == 409
        result = await client.get("/api/billing/skus?channel=apple_iap", headers={"X-App-Bundle-ID": "unknown.bundle"})
        assert result.status_code == 409
        result = await client.get("/api/billing/skus?channel=apple_iap", headers={"X-App-Edition": "unknown"})
        assert result.status_code == 422
        result = await client.post("/api/billing/orders", headers=headers,
            json={"sku_id": "topup_10", "pay_type": "apple_iap", "idempotency_key": "header-order-123"})
        assert result.status_code == 200, result.text
        assert intent.call_args.args[3] == "domestic.product"


@pytest.mark.parametrize("headers,expected", [
    ({}, "international"),
    ({"x-app-edition": "domestic"}, "domestic"),
    ({"x-app-bundle-id": "com.qianzhi.deep.app01"}, "domestic"),
    ({"x-app-edition": "international", "x-app-bundle-id": "com.example.global"}, "international")])
def test_resolver_legacy_and_single_hints(config, headers, expected):
    request = Request({"type": "http", "headers": [(k.encode(),v.encode()) for k,v in headers.items()]})
    assert apple_api.resolve_app_edition(request) == expected
