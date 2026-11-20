"""Separate Apple catalogs and receipt ownership in a real PostgreSQL test schema."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from test_marketplace_apple_iap import apple_ctx, apple_cfg, verified_transaction
from app.marketplace import apple_api, app_settings, app_admin
from app.marketplace.app_models import AppleProduct, AppleTransaction
from app.marketplace.apple_recharge import list_recharge_products, find_product_for_sku
from app.marketplace.apple_service import apply_verified_transaction


async def domestic_product(ctx, cfg, monkeypatch):
    cfg.apple_domestic_bundle_id = "com.qianzhi.deep.app01"
    cfg.apple_domestic_app_id = 456
    monkeypatch.setattr(app_settings, "get_app_settings", lambda: cfg)
    row = AppleProduct(product_id="com.qianzhi.deep.app01.credits.topup_10", app_edition="domestic",
        sku_id="test_600", sku_snapshot={"id": "test_600", "name": "Test", "amount_fen": 600, "credit_fen": 600},
        coins=600, price_fen=600, enabled=True)
    ctx.db.add(row)
    await ctx.db.flush()
    return row


@pytest.mark.asyncio
async def test_catalogs_select_separate_ids_and_legacy_defaults(apple_ctx, apple_cfg, monkeypatch):
    row = await domestic_product(apple_ctx, apple_cfg, monkeypatch)
    international = await list_recharge_products(apple_ctx.db)
    domestic = await list_recharge_products(apple_ctx.db, "domestic")
    assert [p["product_id"] for p in international] == ["coins.600"]
    assert [p["product_id"] for p in domestic] == [row.product_id]
    assert (await find_product_for_sku(apple_ctx.db, "test_600")).product_id == "coins.600"
    assert (await find_product_for_sku(apple_ctx.db, "test_600", "domestic")).product_id == row.product_id
    monkeypatch.setattr(apple_api, "purchasing_enabled", lambda *_: True)
    default = await apple_ctx.client.get("/api/marketplace/app/v1/coin-products")
    cn = await apple_ctx.client.get("/api/marketplace/app/v1/coin-products?app_edition=domestic")
    assert default.json()["items"][0]["product_id"] == "coins.600"
    assert cn.json()["items"][0]["product_id"] == row.product_id
    assert (await apple_ctx.client.get("/api/marketplace/app/v1/coin-products?app_edition=unknown")).status_code == 422


@pytest.mark.asyncio
async def test_domestic_receipt_cannot_use_international_product(apple_ctx, apple_cfg, monkeypatch):
    row = await domestic_product(apple_ctx, apple_cfg, monkeypatch)
    for product, bundle in (("coins.600", apple_cfg.apple_domestic_bundle_id), (row.product_id, apple_cfg.apple_bundle_id)):
        with pytest.raises(HTTPException) as error:
            await apply_verified_transaction(apple_ctx.db, verified_transaction(apple_ctx, product_id=product,
                bundle_id=bundle))
        assert error.value.detail["code"] == "MARKETPLACE_IAP_PRODUCT_APP_MISMATCH"
    assert await apple_ctx.db.scalar(select(func.count()).select_from(AppleTransaction)) == 0
    txn = verified_transaction(apple_ctx, product_id=row.product_id, bundle_id=apple_cfg.apple_domestic_bundle_id,
        raw_payload={"bundleId": apple_cfg.apple_domestic_bundle_id})
    first = await apply_verified_transaction(apple_ctx.db, txn)
    again = await apply_verified_transaction(apple_ctx.db, txn)
    assert first.id == again.id and apple_ctx.buyer.balance_fen == 600


@pytest.mark.asyncio
async def test_admin_allows_one_active_product_per_sku_per_app(apple_ctx):
    body = dict(sku_id="topup_10", coins=10000, price_fen=10000, enabled=True)
    for edition in ("international", "domestic"):
        await app_admin.save_product(app_admin.ProductInput(**body, product_id=f"product.{edition}", app_edition=edition),
            apple_ctx.db, apple_ctx.buyer)
    with pytest.raises(HTTPException) as error:
        await app_admin.save_product(app_admin.ProductInput(**body, product_id="product.duplicate", app_edition="domestic"),
            apple_ctx.db, apple_ctx.buyer)
    assert error.value.detail["code"] == "MARKETPLACE_IAP_PRODUCT_CONFLICT"
    with pytest.raises(HTTPException) as error:
        await app_admin.save_product(app_admin.ProductInput(**body, product_id="product.international", app_edition="domestic"),
            apple_ctx.db, apple_ctx.buyer)
    assert error.value.detail["code"] in ("MARKETPLACE_IAP_PRODUCT_IMMUTABLE", "MARKETPLACE_IAP_PRODUCT_CONFLICT")


@pytest.mark.asyncio
async def test_presets_match_domestic_ids():
    rows = (await app_admin.product_presets(None, "domestic"))["items"]
    assert [p["product_id"] for p in rows] == [
        f"com.qianzhi.deep.app01.credits.{sku}" for sku in ("topup_10", "topup_49", "topup_99", "topup_199")]
    assert [p["coins"] for p in rows] == [10000, 49000, 104000, 220000]
