"""DB managed settings and frozen Google product mappings (no .env setup)."""
import json
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from app.services.model_settings import _encrypt_secret, _decrypt_secret
from .google_models import GoogleSettings, GoogleIntent, GoogleAudit
from .locale import localized

DEFAULT_PRODUCTS = [
    dict(sku_id=sku, product_id=product, name=name, purchase_option_id="buy", offer_id=None, enabled=True)
    for sku, product, name in (
        ("topup_10", "printfilm_credits_trial", "PrintFilm Trial Credits"),
        ("topup_49", "printfilm_credits_basic", "PrintFilm Basic Credits"),
        ("topup_99", "printfilm_credits_plus", "PrintFilm Plus Credits"),
        ("topup_199", "printfilm_credits_pro", "PrintFilm Pro Credits"))]


def fail(code, zh, en, status=409):
    raise HTTPException(status, {"code": code, "detail": localized(zh, en)})


class ProductConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku_id: str = Field(min_length=1, max_length=64)
    product_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9_.]*$")
    name: str = Field(min_length=1, max_length=200)
    purchase_option_id: str = "buy"
    offer_id: None = None
    enabled: bool = True
    # Set by the server from the shared SKU; immutable once registered.
    credit_fen: int | None = Field(None, gt=0)
    reference_amount_fen: int | None = Field(None, gt=0)


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)
    purchasing_enabled: bool = False
    package_name: str = Field("com.deep.printfilm", pattern=r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$", max_length=200)
    rtdn_audience: str = Field("", max_length=1000)
    rtdn_service_account: str = Field("", max_length=300)
    test_user_ids: list[int] = Field(default_factory=list, max_length=500)
    products: list[ProductConfig] = Field(default_factory=list, max_length=30)
    service_account_json: str | None = Field(None, max_length=30000)
    clear_credentials: bool = False

    @model_validator(mode="after")
    def distinct(self):
        if len({p.product_id for p in self.products}) != len(self.products):
            raise ValueError("Google product IDs must be unique")
        active = [p.sku_id for p in self.products if p.enabled]
        if len(active) != len(set(active)) or any(i <= 0 for i in self.test_user_ids):
            raise ValueError("Enabled SKU IDs must be unique; test user IDs must be positive")
        if any(p.purchase_option_id != "buy" for p in self.products):
            raise ValueError("Only the standard buy option is supported")
        return self


def credentials(secret):
    try:
        data = json.loads(_decrypt_secret(secret))
        if (data.get("type") != "service_account" or not data.get("client_email")
                or not data.get("private_key") or data.get("token_uri") != "https://oauth2.googleapis.com/token"):
            raise ValueError()
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
        if not isinstance(load_pem_private_key(data["private_key"].encode(), None), RSAPrivateKey):
            raise ValueError()
        return data
    except Exception:
        fail("GOOGLE_CONFIG_UNAVAILABLE", "Google 服务账号凭证不可用，请检查后台配置。", "Google service credentials are unavailable.", 503)


async def read(db):
    row = await db.scalar(select(GoogleSettings).where(GoogleSettings.key == "billing"))
    return row, (row.config if row else dict(purchasing_enabled=False, package_name="com.deep.printfilm",
        rtdn_audience="", rtdn_service_account="", test_user_ids=[], products=DEFAULT_PRODUCTS))


def test_user(config, user_id):
    return user_id in config.get("test_user_ids", ())


async def save(db, body, admin_id):
    # Settings writes serialize even before the singleton row exists.
    from app.models import User
    await db.scalar(select(User.id).where(User.id == admin_id).with_for_update())
    from .app_schema import acquire_schema_lock
    await db.run_sync(lambda session: acquire_schema_lock(session.connection()))
    row, old = await read(db)
    if body.version != (row.version if row else 0):
        fail("GOOGLE_CONFIG_CONFLICT", "配置已变化，请刷新。", "Settings changed; refresh first.")
    config = body.model_dump(exclude={"version", "reason", "service_account_json", "clear_credentials"})
    from app.services.billing import sku_by_id
    old_products = {p["product_id"]: p for p in old["products"] if p.get("credit_fen")}
    for product in config["products"]:
        previous = old_products.get(product["product_id"])
        sku = sku_by_id(product["sku_id"])
        if not sku:
            fail("GOOGLE_SKU_INVALID", "未找到共同充值套餐。", "Shared recharge SKU does not exist.")
        if previous:
            if product["sku_id"] != previous["sku_id"]:
                fail("GOOGLE_PRODUCT_IMMUTABLE", "已登记商品不可改绑套餐，请新建商品。", "Register a new product to change its SKU.")
            for key in ("credit_fen", "reference_amount_fen"):
                if product[key] not in (None, previous[key]):
                    fail("GOOGLE_PRODUCT_IMMUTABLE", "商品额度快照不可修改。", "Product credit snapshots are immutable.")
                product[key] = previous[key]
        else:
            product["credit_fen"], product["reference_amount_fen"] = int(sku["credit_fen"]), int(sku["amount_fen"])
    # Retain sold/registered mappings, including disabled products for recovery.
    if set(old_products) - {p["product_id"] for p in config["products"]}:
        fail("GOOGLE_PRODUCT_IMMUTABLE", "已登记商品不能删除，请停用。", "Disable registered products instead of deleting them.")
    secret = "" if body.clear_credentials else row.credentials if row else ""
    if body.service_account_json:
        secret = _encrypt_secret(body.service_account_json)
        credentials(secret)
    if config["purchasing_enabled"]:
        credentials(secret)
        if not any(p["enabled"] for p in config["products"]):
            fail("GOOGLE_CONFIG_UNAVAILABLE", "请先登记可售商品。", "Register enabled products first.")
    if row and old["package_name"] != config["package_name"] and await db.scalar(select(GoogleIntent.id).limit(1)):
        fail("GOOGLE_PACKAGE_IMMUTABLE", "已有购买意向，不能修改包名。", "Package name is immutable after checkout starts.")
    if not row:
        row = GoogleSettings(key="billing", version=0)
        db.add(row)
    row.config, row.credentials, row.version = config, secret, body.version + 1
    db.add(GoogleAudit(operator_id=admin_id, reason=body.reason,
        details={"before": old, "after": config, "credentials_changed": bool(body.service_account_json or body.clear_credentials)}))
    await db.flush()
    return row
