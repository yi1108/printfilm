"""Two configured apps use independent, verified identities in one backend."""
import asyncio

import pytest
from fastapi import HTTPException

from app.marketplace import apple_client
from app.marketplace.app_settings import MarketplaceAppSettings
from app.schemas_settings import AdminModelSettingsOut


@pytest.fixture
def config(monkeypatch):
    cfg = MarketplaceAppSettings(_env_file=None, apple_bundle_id="com.example.global",
        apple_app_id=100, apple_domestic_bundle_id="com.example.cn", apple_domestic_app_id=200)
    monkeypatch.setattr(apple_client, "get_app_settings", lambda: cfg)
    return cfg


@pytest.mark.asyncio
async def test_verification_tries_only_configured_apps_and_pins_nested_calls(config, monkeypatch):
    seen = []
    async def official(signed):
        cfg = apple_client.application_settings()
        seen.append((cfg.apple_bundle_id, cfg.apple_app_id))
        if cfg.apple_bundle_id != signed:
            raise HTTPException(400, "wrong application")
        return {"bundle_id": cfg.apple_bundle_id}
    monkeypatch.setattr(apple_client, "_verify_transaction_one", official)
    result = await apple_client.verify_transaction("com.example.cn")
    assert result["bundle_id"] == "com.example.cn"
    assert ("com.example.cn", 200) in seen
    with pytest.raises(HTTPException):
        await apple_client.in_application("com.example.global", apple_client.verify_transaction, "com.example.cn")
    with pytest.raises(HTTPException):
        await apple_client.verify_transaction("com.attacker.app")
    assert apple_client.application_settings().apple_bundle_id == "com.example.global"


@pytest.mark.asyncio
async def test_parallel_app_contexts_never_leak(config):
    async def read():
        before = apple_client.application_settings().apple_bundle_id
        await asyncio.sleep(0)
        assert apple_client.application_settings().apple_bundle_id == before
        return before
    result = await asyncio.gather(
        apple_client.in_application("com.example.cn", read),
        apple_client.in_application("com.example.global", read))
    assert result == ["com.example.cn", "com.example.global"]
    assert apple_client.application_settings().apple_app_id == 100


def test_domestic_fields_are_part_of_admin_contract():
    assert "apple_domestic_bundle_id" in AdminModelSettingsOut.model_fields
    assert "apple_domestic_app_id" in AdminModelSettingsOut.model_fields

@pytest.mark.asyncio
async def test_sqlite_catalog_isolation_and_old_column_default():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from types import SimpleNamespace
    from app.marketplace.app_models import AppleProduct
    from app.marketplace.apple_recharge import list_recharge_products, find_product_for_sku
    engine = create_engine("sqlite:///:memory:")
    AppleProduct.__table__.create(engine)
    with Session(engine) as session:
        snapshot = {"id": "topup_10", "name": "test", "credit_fen": 10000, "amount_fen": 10000}
        session.add_all([
            AppleProduct(product_id="global.product", sku_id="topup_10", sku_snapshot=snapshot, coins=10000, price_fen=10000, enabled=True),
            AppleProduct(product_id="domestic.product", app_edition="domestic", sku_id="topup_10", sku_snapshot=snapshot, coins=10000, price_fen=10000, enabled=True)])
        session.commit()
        class DB:
            async def execute(self, stmt): return session.execute(stmt)
        db = DB()
        assert [p["product_id"] for p in await list_recharge_products(db)] == ["global.product"]
        assert [p["product_id"] for p in await list_recharge_products(db, "domestic")] == ["domestic.product"]
        assert (await find_product_for_sku(db, "topup_10", "domestic")).product_id == "domestic.product"
    engine.dispose()


@pytest.mark.parametrize("edition,bundle,valid", [
    ("international", "com.example.global", True),
    ("domestic", "com.example.cn", True),
    ("international", "com.example.cn", False),
    ("domestic", "com.example.global", False),
    ("domestic", None, False)])
def test_verified_product_application_boundary(config, edition, bundle, valid):
    from types import SimpleNamespace
    from app.marketplace.apple_recharge import validate_product_application
    product = SimpleNamespace(app_edition=edition)
    if valid:
        validate_product_application(product, {"bundle_id": bundle}, config)
    else:
        with pytest.raises(HTTPException):
            validate_product_application(product, {"bundle_id": bundle}, config)
