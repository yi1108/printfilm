"""Stripe hosted Checkout for the existing CNY wallet.

Card details stay on Stripe. Only a signed webhook can credit a saved order;
the browser return URL is informational and never changes a wallet balance.
"""
from __future__ import annotations

import hashlib
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode, urlsplit

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Order, User
from app.services.billing.settlement import credit_topup

logger = logging.getLogger(__name__)
CHECKOUT_EXPIRE_SECONDS = 1860  # 30-minute minimum plus network/clock margin.
PAYMENT_CURRENCIES = frozenset({"cny", "usd", "hkd"})
MAX_PAYMENT_AMOUNT_MINOR = 99_999_999


def _rate_text(value) -> str:
    """校验并规范化人工设置的结算汇率，金额运算不使用浮点数。"""
    raw = str(value or "").strip()
    try:
        if not raw or len(raw) > 32:
            raise ValueError
        rate = Decimal(raw)
        if not rate.is_finite() or rate <= 0 or rate > 1_000_000:
            raise ValueError
        normalized = rate.normalize()
        if normalized.as_tuple().exponent < -6:
            raise ValueError
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Stripe 汇率须为大于 0、不超过 1000000 且最多六位小数的数值") from exc
    return format(normalized, "f")


def quote_payment(amount_fen: int, settings: Settings | None = None, *, language: str = "zh") -> dict:
    """人民币套餐价自动换算为外币最小单位；汇率为人民币/单位外币。"""
    settings = settings or get_settings()
    currency = settings.stripe_currency.strip().lower()
    if currency == "auto":
        currency = "usd" if language == "en" else "cny"
    if currency not in PAYMENT_CURRENCIES:
        raise ValueError("Stripe 收款币种只支持 CNY、USD 或 HKD")
    rate = "1" if currency == "cny" else _rate_text(getattr(settings, f"stripe_{currency}_cny_rate"))
    minor = int((Decimal(int(amount_fen)) / Decimal(rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if amount_fen <= 0 or not 1 <= minor <= MAX_PAYMENT_AMOUNT_MINOR:
        raise ValueError("Stripe 换算后的付款金额超出支持范围，请检查汇率")
    return {"payment_currency": currency, "payment_amount_minor": minor, "payment_exchange_rate": rate}


def payment_snapshot(order: Order) -> dict:
    """读取订单固定报价；上线前的空字段订单仅回退为人民币，不使用当前汇率。"""
    if order.payment_currency is None and order.payment_amount_minor is None:
        return {"payment_currency": "cny", "payment_amount_minor": int(order.amount_fen), "payment_exchange_rate": "1"}
    if (order.payment_currency not in PAYMENT_CURRENCIES or order.payment_amount_minor is None
            or not 1 <= order.payment_amount_minor <= MAX_PAYMENT_AMOUNT_MINOR or not order.payment_exchange_rate):
        raise ValueError("Stripe 订单付款报价不完整")
    return {
        "payment_currency": order.payment_currency,
        "payment_amount_minor": int(order.payment_amount_minor),
        "payment_exchange_rate": order.payment_exchange_rate,
    }


def _frontend_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    base = (settings.stripe_frontend_url or settings.public_base_url).strip().rstrip("/")
    try:
        parsed = urlsplit(base)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Stripe 前端地址格式无效") from exc
    # Only trusted server configuration determines redirects, never a request header.
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (parsed.scheme != "https" and not (parsed.scheme == "http" and local)) or not parsed.hostname:
        raise ValueError("Stripe 前端地址必须为 HTTPS（本地开发可使用 HTTP）")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Stripe 前端地址不能包含凭据、查询参数或片段")
    if (parsed.path not in {"", "/"} or port == 0 or "\\" in base
            or any(char.isspace() for char in base)):
        raise ValueError("Stripe 前端地址须为有效的站点根地址，不包含页面路径")
    return base


def is_ready(settings: Settings | None = None, *, language: str = "zh") -> bool:
    settings = settings or get_settings()
    if not (settings.stripe_enabled and settings.stripe_secret_key.strip() and settings.stripe_webhook_secret.strip()):
        return False
    try:
        _frontend_url(settings)
        from app.services.billing.pricing import SKUS
        for sku in SKUS:
            quote_payment(int(sku["amount_fen"]), settings, language=language)
    except ValueError:
        return False
    return True


def validate_settings_patch(patch: dict) -> None:
    """Validate newly supplied admin values without returning secret contents."""
    if patch.get("stripe_currency") is not None:
        currency = patch["stripe_currency"].strip().lower()
        if currency not in PAYMENT_CURRENCIES | {"auto"}:
            raise ValueError("Stripe 收款币种须为按语言选择 auto，或 CNY、USD、HKD")
        patch["stripe_currency"] = currency
    for field in ("stripe_usd_cny_rate", "stripe_hkd_cny_rate"):
        if patch.get(field) is not None:
            raw = str(patch[field]).strip()
            patch[field] = _rate_text(raw) if raw else ""
    key = str(patch.get("stripe_secret_key") or "").strip()
    if key and (not key.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_"))
                or any(char.isspace() for char in key) or len(key) > 512):
        raise ValueError("Stripe API 密钥须为 sk_test_、sk_live_、rk_test_ 或 rk_live_ 开头的服务端密钥")
    webhook_secret = str(patch.get("stripe_webhook_secret") or "").strip()
    if webhook_secret and (not webhook_secret.startswith("whsec_")
                           or any(char.isspace() for char in webhook_secret) or len(webhook_secret) > 512):
        raise ValueError("Stripe Webhook 签名密钥须以 whsec_ 开头且不含空格")
    if patch.get("stripe_frontend_url") is not None:
        base = patch["stripe_frontend_url"].strip()
        if len(base) > 2048:
            raise ValueError("Stripe 前端地址过长")
        patch["stripe_frontend_url"] = base
        if base:
            _frontend_url(get_settings().model_copy(update={"stripe_frontend_url": base}))


@asynccontextmanager
async def _client():
    # Existing sessions can still be cancelled after disabling new checkouts.
    key = get_settings().stripe_secret_key.strip()
    if not key:
        raise ValueError("Stripe API 密钥未配置")
    transport = stripe.HTTPXClient(timeout=20)
    try:
        yield stripe.StripeClient(key, http_client=transport, max_network_retries=2)
    finally:
        await transport.close_async()


async def create_checkout_session(*, order: Order, sku_name: str) -> dict:
    if not is_ready():
        raise ValueError("Stripe 支付未启用或未完成配置")
    base = _frontend_url()
    success_query = urlencode({"payment": "success", "order": order.out_trade_no})
    cancel_query = urlencode({"payment": "cancelled", "order": order.out_trade_no})
    # The random order reference yields a stable alphabetic tag for idempotent retries.
    tag_suffix = "".join(chr(ord("a") + value % 26) for value in hashlib.sha256(order.out_trade_no.encode()).digest()[:8])
    payment = payment_snapshot(order)
    params = {
        "mode": "payment",
        "locale": "en" if payment["payment_currency"] == "usd" else "zh",
        "integration_identifier": f"printfilm-wallet-{tag_suffix}",
        "adaptive_pricing": {"enabled": False},
        "line_items": [{
            "price_data": {
                "currency": payment["payment_currency"],
                "unit_amount": payment["payment_amount_minor"],
                "product_data": {"name": f"PRINTFILM · {sku_name}"},
            },
            "quantity": 1,
        }],
        "client_reference_id": order.out_trade_no,
        "metadata": {"out_trade_no": order.out_trade_no, "user_id": str(order.user_id)},
        "success_url": f"{base}/pricing?{success_query}&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/pricing?{cancel_query}",
        "expires_at": int(time.time()) + CHECKOUT_EXPIRE_SECONDS,
    }
    async with _client() as client:
        session = await client.v1.checkout.sessions.create_async(
            params, options={"idempotency_key": f"wallet-checkout:{order.out_trade_no}"},
        )
    data = session.to_dict()
    parsed = urlsplit(str(data.get("url") or ""))
    if (not str(data.get("id") or "").startswith("cs_") or parsed.scheme != "https"
            or parsed.hostname != "checkout.stripe.com" or parsed.username or parsed.password
            or parsed.port not in {None, 443}):
        raise ValueError("Stripe 未返回有效的收银台地址")
    return data


async def expire_checkout_session(session_id: str) -> None:
    async with _client() as client:
        await client.v1.checkout.sessions.expire_async(session_id)


def construct_event(payload: bytes, signature: str) -> dict:
    # Keep processing signed payments if new checkout creation is disabled.
    secret = get_settings().stripe_webhook_secret.strip()
    if not secret:
        raise ValueError("Stripe Webhook 未配置")
    if not signature:
        raise ValueError("缺少 Stripe 签名")
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise ValueError("无效的 Stripe Webhook") from exc
    return event.to_dict()


async def _matching_order(db: AsyncSession, session: dict) -> Order:
    metadata = session.get("metadata") or {}
    reference = session.get("client_reference_id")
    if not reference or not isinstance(metadata, dict) or metadata.get("out_trade_no") != reference:
        raise ValueError("Stripe 订单标识不匹配")
    order = (await db.execute(
        select(Order).where(Order.out_trade_no == reference).with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if (order is None or order.pay_type != "stripe" or order.team_id is not None
            or not order.trade_no or order.trade_no != session.get("id")
            or metadata.get("user_id") != str(order.user_id)):
        raise ValueError("Stripe 订单不匹配")
    return order


async def fulfill_checkout(db: AsyncSession, session: dict) -> None:
    if session.get("payment_status") != "paid":
        return
    order = await _matching_order(db, session)
    payment = payment_snapshot(order)
    if (session.get("mode") != "payment" or session.get("status") != "complete"
            or session.get("currency") != payment["payment_currency"]
            or session.get("amount_total") != payment["payment_amount_minor"]):
        raise ValueError("Stripe 支付金额、币种或状态不匹配")
    if order.status == "paid":
        return
    user = await db.get(User, order.user_id)
    if user is None:
        raise ValueError("Stripe 订单用户不存在")
    # Order and wallet locks plus a single transaction serialize retries and
    # concurrent events, including a valid payment arriving after local closure.
    await credit_topup(
        db, user, int(order.credit_fen), ref_type="order", ref_id=order.out_trade_no,
        note="stripe:checkout",
    )
    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("stripe paid order=%s user=%s", order.out_trade_no, order.user_id)


async def handle_checkout_event(db: AsyncSession, event: dict) -> None:
    event_type = event.get("type")
    if event_type not in {
        "checkout.session.completed", "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed", "checkout.session.expired",
    }:
        return
    session = (event.get("data") or {}).get("object")
    if not isinstance(session, dict):
        raise ValueError("无效的 Stripe Session")
    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        await fulfill_checkout(db, session)
    else:
        order = await _matching_order(db, session)
        if order.status == "pending":
            order.status = "closed"
            await db.flush()
