"""App 苹果充值接口；通知、已付款验单不受市场展示开关控制。"""
from fastapi import APIRouter, Request, Response
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from . import apple_client
from .apple_service import account_token, apply_verified_transaction, persist_notification, purchase_intent, transaction_response
from .app_settings import get_app_settings
from .coin_service import app_fail, funds_call
from .config import is_marketplace_enabled
from .dependencies import Actor, DB, Visitor
from .service import now

from .app_response import AppJSONResponse

router = APIRouter(default_response_class=AppJSONResponse)
notifications_router = APIRouter()
billing_router = APIRouter(prefix="/api/billing/apple")


APP_IDENTITY_OPENAPI = {"parameters": [
    {"name": "X-App-Edition", "in": "header", "required": False,
     "description": "Catalog selection only; must match explicit app_edition and configured bundle.",
     "schema": {"type": "string", "enum": ["domestic", "international"]}},
    {"name": "X-App-Bundle-ID", "in": "header", "required": False,
     "description": "Configured iOS bundle identifier; never accepted as payment proof.",
     "schema": {"type": "string"}}
]}


class PurchaseIntentInput(BaseModel):
    """客户端只提交商品标识，不决定到账币数或付款金额。"""
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=128)


class VerifyInput(BaseModel):
    """回传 StoreKit 2 的原始 JWS，不能提交用户编号认领交易。"""
    model_config = ConfigDict(extra="forbid")
    signed_transaction_info: str = Field(min_length=16, max_length=65536)
    intent_id: int | None = Field(None, gt=0)


class NotificationInput(BaseModel):
    """Apple V2 服务器通知的标准字段。"""
    model_config = ConfigDict(extra="forbid")
    signed_payload: str = Field(alias="signedPayload", min_length=16, max_length=131072)


class ConsumptionConsentInput(BaseModel):
    """允许用户独立决定退款时是否提供消费信息，不能强制换取购买资格。"""
    model_config = ConfigDict(extra="forbid")
    consented: bool


def resolve_app_edition(request=None, explicit=None):
    """Client hints select a catalog; they never prove payment or select a wallet."""
    headers = request.headers if request is not None else {}
    hinted = headers.get("X-App-Edition", "").strip().lower()
    bundle = headers.get("X-App-Bundle-ID", "").strip()
    candidates = [value for value in (explicit, hinted) if value]
    if any(value not in ("domestic", "international") for value in candidates):
        app_fail("MARKETPLACE_IAP_APP_INVALID", "应用版本参数不正确。", 422)
    if bundle:
        cfg = get_app_settings()
        known = {value: edition for value, edition in (
            (cfg.apple_bundle_id, "international"), (cfg.apple_domestic_bundle_id, "domestic")) if value}
        if bundle not in known:
            app_fail("MARKETPLACE_IAP_APP_INVALID", "应用包名尚未配置，请联系管理员。", 409)
        candidates.append(known[bundle])
    if len(set(candidates)) > 1:
        app_fail("MARKETPLACE_IAP_APP_MISMATCH", "应用版本与包名不一致，请刷新充值页面。", 409)
    return candidates[0] if candidates else "international"


async def purchasing_enabled_for_app(user_id, edition):
    cfg = get_app_settings()
    bundle = cfg.apple_domestic_bundle_id if edition == "domestic" else cfg.apple_bundle_id
    if edition == "domestic" and not bundle:
        return False
    async def check():
        return purchasing_enabled(user_id)
    return await apple_client.in_application(bundle, check)


def purchasing_enabled(user_id=None) -> bool:
    """只约束新购买，不约束已经产生真实付款的履约。"""
    cfg = get_app_settings()
    from app.services.billing import wallet
    from .sandbox_wallet import tester, new_purchase_allowed
    if tester(user_id) and wallet.configured_environment() == "Production":
        return bool(new_purchase_allowed(user_id) and apple_client.apple_configured())
    return bool(wallet.enabled()
                and cfg.apple_environment == wallet.configured_environment()
                and cfg.apple_iap_enabled and apple_client.apple_configured())


@router.get("/coin-products", response_model=dict, openapi_extra=APP_IDENTITY_OPENAPI)
async def coin_products(db: DB, user: Visitor, app_edition: Literal["domestic", "international"] | None = None, request: Request = None, response: Response = None):
    """只列出真实后台登记商品，价格展示仍以 StoreKit 返回值为准。"""
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Accept-Language, Authorization, X-App-Edition, X-App-Bundle-ID"
    app_edition = resolve_app_edition(request, app_edition)
    enabled = await purchasing_enabled_for_app(user.id if user else None, app_edition)
    from .sandbox_wallet import environment
    from .apple_recharge import list_recharge_products
    if app_edition == "domestic":
        cfg = get_app_settings()
        enabled = enabled and bool(cfg.apple_domestic_bundle_id and
            (cfg.apple_environment == "Sandbox" or cfg.apple_domestic_app_id))
    products = await list_recharge_products(db, app_edition) if enabled else []
    return {"app_edition": app_edition, "purchasing_enabled": enabled, "environment": environment(user.id if user else None),
            "currency": "CNY", "credit_currency": "CNY", "supported_payment_currencies": ["CNY", "USD"], "coins_per_yuan": 100,
            "items": [{**row, "sku_id": row["id"], "price_fen": row["reference_price_fen"]} for row in products]}


@router.post("/iap/apple/purchase-intents", response_model=dict, openapi_extra=APP_IDENTITY_OPENAPI)
async def create_purchase_intent(body: PurchaseIntentInput, db: DB, user: Actor, request: Request):
    """只有新购开关、身份及真实苹果配置齐备时才允许发起 StoreKit 购买。"""
    from sqlalchemy import select
    from .app_models import AppleProduct
    product = await db.scalar(select(AppleProduct).where(AppleProduct.product_id == body.product_id))
    edition = product.app_edition if product else resolve_app_edition(request)
    if request.headers.get("X-App-Edition") or request.headers.get("X-App-Bundle-ID"):
        if resolve_app_edition(request) != edition:
            app_fail("MARKETPLACE_IAP_APP_MISMATCH", "应用版本与包名不一致，请刷新充值页面。", 409)
    if not await purchasing_enabled_for_app(user.id, edition):
        app_fail("MARKETPLACE_PAYMENT_UNAVAILABLE", "苹果充值暂不可用，请稍后重试。", 503)
    from .sandbox_wallet import environment
    result = await purchase_intent(db, user.id, environment(user.id), body.product_id, body.idempotency_key)
    await db.commit()
    return result


@billing_router.post("/transactions/verify", response_model=dict)
@router.post("/iap/apple/transactions/verify", response_model=dict)
async def verify_apple_transaction(body: VerifyInput, db: DB, user: Actor):
    """支付后断网、关入口或意向过期仍可验单；commit成功才允许App finish。"""
    supplied = await apple_client.verify_transaction(body.signed_transaction_info)
    current = await apple_client.in_application(supplied.get("bundle_id"), apple_client.in_environment,
        supplied["environment"], apple_client.query_transaction, supplied["transaction_id"])
    if current.get("bundle_id") != supplied.get("bundle_id"):
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "苹果交易查询结果与回执不一致，请联系客服。")
    if any(current[field] != supplied[field] for field in ("transaction_id", "product_id", "app_account_token", "environment")):
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "苹果交易查询结果与回执不一致，请联系客服。")
    item = await apply_verified_transaction(db, current, expected_user_id=user.id, intent_id=body.intent_id)
    from . import app_funds
    state = await funds_call(app_funds.snapshot(db, user.id, item.environment))
    result = {**transaction_response(item), **state, "balance_coins": state["balance_fen"]}
    await db.commit()
    return result


@router.patch("/iap/apple/consumption-consent", response_model=dict)
async def set_consumption_consent(body: ConsumptionConsentInput, db: DB, user: Actor):
    """明确授权或撤回仅影响消费信息分享，不影响买币及苹果退款结果。"""
    token = await account_token(db, user.id)
    token.consumption_data_consent = body.consented
    token.consented_at = now()
    await db.commit()
    return {"consented": token.consumption_data_consent,
            "message": "仅在退款处理中向苹果提供该笔充值的到账状态和使用比例。" if body.consented else "不会向苹果提供消费使用信息；仍会处理苹果退款结果。"}


@billing_router.post("/notifications", response_model=dict)
@notifications_router.post("/api/marketplace/payments/apple/notifications", response_model=dict)
async def apple_notifications(body: NotificationInput, db: DB):
    """只有验签并持久化后才返回2xx；后台任务可在关闭市场后继续处理。"""
    payload = await apple_client.verify_notification(body.signed_payload)
    created = await persist_notification(db, payload)
    await db.commit()
    return {"ok": True, "duplicate": not created}
