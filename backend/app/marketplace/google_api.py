"""Android Google Play contract, admin settings, authenticated RTDN inbox."""
import base64
import json
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from .dependencies import Actor, Admin, DB
from .google_models import GoogleNotification, GooglePurchase, GoogleWork
from . import google_service as service, google_client
from .google_config import read, save, fail, SettingsInput
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from app.services.billing.wallet_base import WalletError
from .service import now

class GoogleRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                return await original(request)
            except HTTPException as exc:
                detail = exc.detail
                payload = detail if isinstance(detail, dict) else {"code": f"HTTP_{exc.status_code}", "detail": str(detail)}
                return JSONResponse(payload, status_code=exc.status_code, headers={"Cache-Control": "no-store"})
            except WalletError as exc:
                from .locale import localized
                return JSONResponse({"code": exc.code, "detail": localized(exc.message,
                    "The wallet is unavailable. Please contact support or retry later.")},
                    status_code=exc.status, headers={"Cache-Control": "no-store"})
            except RequestValidationError:
                # Validation errors must not echo purchase tokens or private JSON.
                from .locale import localized
                return JSONResponse({"code": "GOOGLE_REQUEST_INVALID", "detail": localized(
                    "请求参数不正确，请核对接口文档。", "Invalid request parameters; check the integration guide.")},
                    status_code=422, headers={"Cache-Control": "no-store"})
        return handler


router = APIRouter(prefix="/iap/google", route_class=GoogleRoute)
admin_router = APIRouter(prefix="/api/admin/settings/google-play", route_class=GoogleRoute)
public_router = APIRouter(prefix="/api/billing/google", route_class=GoogleRoute)


class IntentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_name: str = Field(min_length=1, max_length=200)
    sku_id: str = Field(min_length=1, max_length=64)
    product_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=128)


class VerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    package_name: str = Field(min_length=1, max_length=200)
    product_id: str = Field(min_length=1, max_length=200)
    purchase_token: str = Field(min_length=1, max_length=8192)
    quantity: int = Field(1, ge=1, le=1)
    intent_id: str | None = Field(None, max_length=64)
    obfuscated_account_id: str | None = Field(None, max_length=64)
    obfuscated_profile_id: str | None = Field(None, max_length=64)


class GoogleProductOut(BaseModel):
    sku_id: str
    product_id: str
    name: str
    credit_fen: int
    purchase_option_id: str
    offer_id: None = None
    enabled: bool


class GoogleCatalogOut(BaseModel):
    package_name: str
    purchasing_enabled: bool
    obfuscated_account_id: str
    skus: list[GoogleProductOut]


class GoogleIntentOut(BaseModel):
    package_name: str
    intent_id: str
    sku_id: str
    product_id: str
    credit_fen: int
    obfuscated_account_id: str
    obfuscated_profile_id: str
    expires_at: datetime


class GoogleVerificationOut(BaseModel):
    package_name: str
    product_id: str
    purchase_token_sha256: str
    order_id: str | None = None
    status: Literal["credited", "already_credited", "pending", "refunded", "cancelled"]
    credited: bool
    consume_purchase: bool
    credit_fen: int
    environment: Literal["Production", "Sandbox"]
    test_only: bool


@router.get("/skus", response_model=GoogleCatalogOut, summary="Google Play 充值商品及当前用户绑定标识")
async def skus(db: DB, user: Actor):
    row, config = await read(db)
    enabled = service.available(config, row.credentials if row else "")
    identity = await service.account(db, user.id, config["package_name"])
    products = [{k: p[k] for k in ("sku_id", "product_id", "name", "credit_fen", "purchase_option_id", "offer_id", "enabled")}
        for p in config["products"] if p["enabled"] and p.get("credit_fen")]
    await db.commit()
    return JSONResponse(dict(package_name=config["package_name"], purchasing_enabled=enabled,
        obfuscated_account_id=identity, skus=products), headers={"Cache-Control": "no-store"})


@router.post("/purchase-intents", response_model=GoogleIntentOut, summary="创建绑定原账号和冻结积分的 Google 购买意向")
async def purchase_intents(body: IntentInput, db: DB, user: Actor,
                           idempotency_key: str = Header(alias="Idempotency-Key")):
    if idempotency_key != body.idempotency_key:
        fail("GOOGLE_IDEMPOTENCY_CONFLICT", "请求头与正文的幂等键不一致。", "Header and body idempotency keys differ.")
    result = await service.create_intent(db, user.id, body)
    await db.commit()
    return JSONResponse(jsonable_encoder(result), headers={"Cache-Control": "no-store"})


@router.post("/transactions/verify", response_model=GoogleVerificationOut, summary="Google 服务端验单并原子履约；提交后才允许消耗")
async def verify(body: VerifyInput, db: DB, user: Actor,
                 idempotency_key: str = Header(alias="Idempotency-Key")):
    if idempotency_key != "google-" + service.digest(body.purchase_token):
        fail("GOOGLE_IDEMPOTENCY_CONFLICT", "验单幂等键与交易不一致。", "Verification idempotency key does not match the token.")
    result = await service.verify(db, user.id, body)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@admin_router.get("", summary="Google Play 服务端配置和待处理数量（不返回密钥）")
async def settings(db: DB, admin: Admin):
    row, config = await read(db)
    from app.config import get_settings
    return {**config, "version": row.version if row else 0, "has_credentials": bool(row and row.credentials),
        "notification_url": get_settings().public_base_url.rstrip("/") + "/api/billing/google/notifications",
        "retry_count": await db.scalar(select(func.count()).select_from(GoogleWork).where(GoogleWork.last_error != "")),
        "unconsumed_count": await db.scalar(select(func.count()).select_from(GooglePurchase).where(
            GooglePurchase.status == "credited", GooglePurchase.consumed.is_(False)))}


@admin_router.patch("", summary="保存 Google 凭证、商品映射及测试账号；私钥加密存储")
async def update_settings(body: SettingsInput, db: DB, admin: Admin):
    row = await save(db, body, admin.id)
    await db.commit()
    return {"saved": True, "version": row.version}


@admin_router.get("/transactions", summary="Google 交易、原币待同步与消耗状态")
async def transactions(db: DB, admin: Admin, limit: int = 50):
    rows = (await db.scalars(select(GooglePurchase).order_by(GooglePurchase.id.desc()).limit(max(1, min(100, limit))))).all()
    return {"items": [dict(id=t.id, user_id=t.user_id, order_id=t.order_id, google_order_id=t.google_order_id,
        product_id=t.product_id, environment=t.environment, status=t.status, credit_fen=t.credit_fen,
        consumed=t.consumed, currency=t.currency, amount_micros=t.amount_micros,
        valuation_status="test_only" if t.environment == "Sandbox" else "pending",
        last_verified_at=t.last_verified_at) for t in rows]}


@admin_router.get("/queue", summary="Google 持久补单队列；只返回脱敏错误码")
async def work_queue(db: DB, admin: Admin, limit: int = 50):
    rows = (await db.scalars(select(GoogleWork).order_by(GoogleWork.attempts.desc(), GoogleWork.id.desc())
        .limit(max(1, min(100, limit))))).all()
    return {"items": [dict(id=w.id, product_id=w.product_id, attempts=w.attempts,
        last_error=w.last_error, next_attempt_at=w.next_attempt_at) for w in rows]}


@public_router.post("/notifications", summary="Google Pub/Sub RTDN；验证 OIDC，持久化后应答")
async def notifications(request: Request, db: DB, authorization: str = Header(default="")):
    settings, config = await read(db)
    if not authorization.startswith("Bearer "):
        fail("GOOGLE_RTDN_UNAUTHORIZED", "缺少通知身份凭证。", "Missing notification identity.", 401)
    await db.rollback()
    await google_client.verify_push(authorization[7:], config)
    raw = await request.body()
    if len(raw) > 65536:
        fail("GOOGLE_RTDN_INVALID", "通知过大。", "Notification too large.", 413)
    try:
        envelope = json.loads(raw)
        message = envelope["message"]
        message_id = message["messageId"]
        data = json.loads(base64.b64decode(message["data"], validate=True))
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 200 or data["packageName"] != config["package_name"]:
            raise ValueError()
        note = data.get("oneTimeProductNotification") or data.get("voidedPurchaseNotification")
        kind = "one_time" if data.get("oneTimeProductNotification") else "voided" if note else "test" if "testNotification" in data else "ignored"
        token = note.get("purchaseToken", "") if note else ""
        product_id = note.get("sku", "") if note else ""
        if note and (not isinstance(token, str) or not 1 <= len(token) <= 8192 or len(product_id) > 200):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        fail("GOOGLE_RTDN_INVALID", "通知格式不正确。", "Invalid notification envelope.", 400)
    inserted = await db.scalar(insert(GoogleNotification).values(message_id=message_id,
        token_hash=service.digest(token) if token else "", notification_type=kind, status="queued" if token else "ignored")
        .on_conflict_do_nothing(index_elements=["message_id"]).returning(GoogleNotification.id))
    if inserted and token:
        if not product_id:
            txn = await db.scalar(select(GooglePurchase).where(GooglePurchase.package_name == config["package_name"],
                GooglePurchase.token_hash == service.digest(token)))
            product_id = txn.product_id if txn else ""
        if product_id:
            await service.queue(db, config["package_name"], product_id, token)
            work = await db.scalar(select(GoogleWork).where(GoogleWork.package_name == config["package_name"],
                GoogleWork.token_hash == service.digest(token)))
            work.next_attempt_at = now()
        # Unknown voids are picked up by the paged Publisher voided API. RTDN is
        # never itself treated as proof of cancellation or a financial instruction.
    await db.commit()
    return {"ok": True}
