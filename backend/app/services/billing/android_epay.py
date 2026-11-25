"""Android checkout orchestration: commit intent before network, never infer payment from return."""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from sqlalchemy import select, func
from app.config import get_settings
from app.models import Order, User
from app.marketplace.android_epay_models import AndroidEpayCheckout
from app.marketplace.coin_service import app_fail
from app.services import epay
from app.services.model_settings import _encrypt_secret
from . import wallet
from .pricing import sku_by_id
from .order_origin import ANDROID
from .android_epay_config import readiness, checkout_url, payment_return_origin

log = logging.getLogger(__name__)

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def namespace(api, pid):
    return hashlib.sha256((api.rstrip("/") + "|" + str(pid)).encode()).hexdigest()

def check_identity(request, cfg):
    for name in ("X-App-Package-Name", "X-App-Bundle-ID"):
        if cfg.android_epay_package_name and request.headers.get(name) and request.headers[name] != cfg.android_epay_package_name:
            app_fail("ANDROID_EPAY_APP_MISMATCH", "安卓包名与国内支付配置不一致。", 409)
    if request.headers.get("X-App-Edition", "domestic") != "domestic":
        app_fail("ANDROID_EPAY_APP_MISMATCH", "国内安卓充值仅支持国内版应用。", 409)

def present(order, checkout):
    remaining = max(0, int((utc(checkout.expires_at) - datetime.now(timezone.utc)).total_seconds()))
    ready = checkout.state == "ready" and order.status == "pending" and remaining > 0
    return {"out_trade_no": order.out_trade_no, "sku_id": order.sku_id, "pay_type": order.pay_type,
        "amount_fen": order.amount_fen, "credit_fen": order.credit_fen, "payment_currency": "CNY",
        "payment_client": ANDROID, "app_edition": "domestic", "environment": "Production",
        "status": order.status, "checkout_status": checkout.state, "pay_mode": "redirect" if ready else "unavailable",
        "checkout_url": checkout.checkout_url if ready else None,
        "payurl": checkout.checkout_url if ready else "", "expire_seconds": remaining,
        "error_code": checkout.error_code or None}

async def create_checkout(db, user_id, body, request, client_ip):
    cfg = get_settings().model_copy(deep=True)
    # Only new intents need purchasing enabled; already-paid order reads remain available.
    check_identity(request, cfg)
    if body.pay_type not in ("alipay", "wxpay") or body.app_edition != "domestic":
        app_fail("ANDROID_EPAY_CHANNEL_INVALID", "国内安卓只支持支付宝和微信易支付充值。", 422)
    if not body.idempotency_key:
        app_fail("MARKETPLACE_IDEMPOTENCY_REQUIRED", "请提供充值操作编号。", 422)
    fingerprint = hashlib.sha256(json.dumps({"sku": body.sku_id, "pay_type": body.pay_type,
        "package": cfg.android_epay_package_name}, sort_keys=True).encode()).hexdigest()
    # Serialize initial key claims for this account; DB uniqueness also protects multi-process retries.
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user or user.closed_at:
        app_fail("ANDROID_EPAY_ACCOUNT_UNAVAILABLE", "账户不可用。", 403)
    previous = await db.scalar(select(AndroidEpayCheckout).where(AndroidEpayCheckout.user_id == user_id,
        AndroidEpayCheckout.idempotency_key == body.idempotency_key))
    if previous:
        prior_hash = hashlib.sha256(json.dumps({"sku": body.sku_id, "pay_type": body.pay_type,
            "package": previous.package_name}, sort_keys=True).encode()).hexdigest()
        if previous.request_hash != prior_hash:
            app_fail("MARKETPLACE_IDEMPOTENCY_CONFLICT", "本次操作编号已用于其他充值参数。", 409)
        order = await db.get(Order, previous.order_id)
        if not order or order.user_id != user_id or order.payment_client != ANDROID:
            app_fail("ANDROID_EPAY_ORDER_CONFLICT", "充值订单归属异常，请联系客服核对。", 409)
        result = present(order, previous)
        await db.commit()
        return result
    state = readiness(cfg)
    if not state["available"] or body.pay_type not in state["pay_types"]:
        app_fail("ANDROID_EPAY_UNAVAILABLE", "国内安卓支付暂不可用，请联系管理员检查移动收银台配置。", 503)
    # Validate funding readiness before sending the user to a real-money cashier.
    from app.marketplace.coin_service import funds_call
    await funds_call(wallet.snapshot(db, user_id))
    recent = await db.scalar(select(func.count()).select_from(AndroidEpayCheckout).where(
        AndroidEpayCheckout.user_id == user_id,
        AndroidEpayCheckout.created_at > datetime.now(timezone.utc) - timedelta(minutes=1)))
    if recent >= 5:
        app_fail("ANDROID_EPAY_RATE_LIMITED", "充值操作过于频繁，请稍后重试。", 429)
    sku = sku_by_id(body.sku_id)
    if not sku:
        app_fail("ANDROID_EPAY_SKU_INVALID", "未知充值套餐。", 422)
    order = Order(out_trade_no="PFA" + uuid.uuid4().hex, user_id=user_id, sku_id=sku["id"],
        amount_fen=int(sku["amount_fen"]), credit_fen=int(sku["credit_fen"]), pay_type=body.pay_type,
        payment_client=ANDROID, payment_environment="Production", payment_currency="cny",
        payment_amount_minor=int(sku["amount_fen"]), payment_exchange_rate="1", status="pending")
    db.add(order)
    await db.flush()
    record = AndroidEpayCheckout(user_id=user_id, order_id=order.id, idempotency_key=body.idempotency_key,
        request_hash=fingerprint, package_name=cfg.android_epay_package_name, merchant_pid=str(cfg.epay_pid),
        merchant_namespace=namespace(cfg.epay_api_url, cfg.epay_pid), signing_secret=_encrypt_secret(cfg.epay_key),
        state="creating", expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    db.add(record)
    await db.flush()
    order_id = order.id
    # Freeze primitives before committing; no DB locks/connections span supplier I/O.
    number, amount, name = order.out_trade_no, order.amount_fen, str(sku["name"])
    await db.commit()
    try:
        result = await epay.create_mapi_payment(out_trade_no=number, name=name,
            money_yuan=epay.money_yuan_from_fen(amount), pay_type=body.pay_type, clientip=client_ip,
            return_url=payment_return_origin(cfg.model_dump()) + "/payments/return?" + urlencode({"order": number}),
            device="jump", config=cfg)
        # QR-only, arbitrary URI schemes and HTTP do not constitute a mobile cashier.
        link = checkout_url(result.get("payurl"), cfg)
    except Exception as exc:
        # A timeout can hide a successful supplier create: never make a second supplier call on this key.
        log.warning("Android cashier creation uncertain order=%s error_type=%s", number, type(exc).__name__)
        record = await db.scalar(select(AndroidEpayCheckout).where(AndroidEpayCheckout.order_id == order_id).with_for_update()
            .execution_options(populate_existing=True))
        if record.state == "creating":
            record.state, record.error_code = "uncertain", "ANDROID_EPAY_CASHIER_UNCONFIRMED"
        await db.commit()
        app_fail("ANDROID_EPAY_CASHIER_UNCONFIRMED", "收银台结果尚未确认，请查询原订单，不要重复发起付款。", 503)
    # A signed notification can arrive before the cashier response.
    order = await db.scalar(select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True))
    record = await db.scalar(select(AndroidEpayCheckout).where(AndroidEpayCheckout.order_id == order_id).with_for_update()
        .execution_options(populate_existing=True))
    if record.state == "creating":
        record.checkout_url, record.state = link, "ready"
    result = present(order, record)
    await db.commit()
    return result
