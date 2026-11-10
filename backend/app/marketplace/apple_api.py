"""App 苹果充值接口；通知、已付款验单不受市场展示开关控制。"""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from . import apple_client
from .apple_service import account_token, apply_verified_transaction, persist_notification, purchase_intent, transaction_response
from .app_settings import get_app_settings
from .coin_service import app_fail, funds_call
from .config import is_marketplace_enabled
from .dependencies import Actor, DB
from .service import now

from .app_response import AppJSONResponse

router = APIRouter(default_response_class=AppJSONResponse)
notifications_router = APIRouter()
billing_router = APIRouter(prefix="/api/billing/apple")


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


def purchasing_enabled() -> bool:
    """只约束新购买，不约束已经产生真实付款的履约。"""
    cfg = get_app_settings()
    from app.services.billing import wallet
    return bool(wallet.enabled()
                and cfg.apple_iap_enabled and apple_client.apple_configured())


@router.get("/coin-products", response_model=dict)
async def coin_products(db: DB):
    """只列出真实后台登记商品，价格展示仍以 StoreKit 返回值为准。"""
    enabled = purchasing_enabled()
    from .apple_recharge import list_recharge_products
    products = await list_recharge_products(db) if enabled else []
    return {"purchasing_enabled": enabled, "environment": get_app_settings().apple_environment,
            "currency": "CNY", "credit_currency": "CNY", "supported_payment_currencies": ["CNY", "USD"], "coins_per_yuan": 100,
            "items": [{**row, "sku_id": row["id"], "price_fen": row["reference_price_fen"]} for row in products]}


@router.post("/iap/apple/purchase-intents", response_model=dict)
async def create_purchase_intent(body: PurchaseIntentInput, db: DB, user: Actor):
    """只有新购开关、身份及真实苹果配置齐备时才允许发起 StoreKit 购买。"""
    if not purchasing_enabled():
        app_fail("MARKETPLACE_PAYMENT_UNAVAILABLE", "苹果充值暂不可用，请稍后重试。", 503)
    result = await purchase_intent(db, user.id, get_app_settings().apple_environment, body.product_id, body.idempotency_key)
    await db.commit()
    return result


@billing_router.post("/transactions/verify", response_model=dict)
@router.post("/iap/apple/transactions/verify", response_model=dict)
async def verify_apple_transaction(body: VerifyInput, db: DB, user: Actor):
    """支付后断网、关入口或意向过期仍可验单；commit成功才允许App finish。"""
    supplied = await apple_client.verify_transaction(body.signed_transaction_info)
    current = await apple_client.query_transaction(supplied["transaction_id"])
    if any(current[field] != supplied[field] for field in ("transaction_id", "product_id", "app_account_token", "environment")):
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "苹果交易查询结果与回执不一致，请联系客服。")
    item = await apply_verified_transaction(db, current, expected_user_id=user.id, intent_id=body.intent_id)
    from app.services.billing import wallet
    state = await funds_call(wallet.snapshot(db, user.id, item.environment))
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
