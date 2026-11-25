# -*- coding: utf-8 -*-
"""Billing wallet + Epay / Stripe top-up APIs."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from typing import Literal

import stripe

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.marketplace.dependencies import Visitor
from app.marketplace.apple_api import APP_IDENTITY_OPENAPI
from fastapi import Response
from app.models import Order, Project, UsageEvent, User
from app.models_tasks import TaskRun
from app.services import billing, epay, stripe_payments
from app.services.billing.http import http_exception_for_value_error
from app.services.billing.order_origin import payment_client
from app.services.billing.settlement import (
    billing_active,
    ensure_balance_for_task_batch,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])
settings = get_settings()


class MediaQuoteItem(BaseModel):
    model_id: str = Field(min_length=1, max_length=128)
    params: dict = Field(default_factory=dict)


class MediaQuoteBody(BaseModel):
    items: list[MediaQuoteItem] = Field(min_length=1, max_length=200)
    price_version: int | None = Field(default=None, ge=1)


@router.post(
    "/media/quote",
    summary="估算媒体生成价格",
    description="需要登录，按当前已发布的媒体固定价格对请求项报价。未发布价格或传入的价格版本与当前版本不一致时返回 409；本接口仅报价。",
    response_description="媒体生成报价",
)
async def quote_media(body: MediaQuoteBody, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.media_models.prices import active_book, quote_items
    book = await active_book(db)
    if not book:
        raise HTTPException(409, detail="媒体固定价格尚未发布")
    if body.price_version is not None and body.price_version != book["version"]:
        raise HTTPException(409, detail="价格已更新，请刷新后重试")
    return quote_items([item.model_dump() for item in body.items], book)


class CreateOrderBody(BaseModel):
    sku_id: str
    client: Literal["web", "android"] = "web"
    pay_type: Literal["alipay", "wxpay", "stripe", "apple_iap"]
    language: Literal["zh", "en"] = "zh"
    idempotency_key: str | None = Field(None, min_length=8, max_length=128)
    app_edition: Literal["domestic", "international"] = "international"


@router.get(
    "/wallet",
    summary="获取个人钱包余额",
    description="需要登录，返回个人可用余额、冻结金额、套餐和计费开关。默认按账号选择钱包：沙箱白名单读取隔离测试余额，其他账号读取正式余额。Web使用view=production明确读取正式钱包；此参数仅影响查询，不改变AI扣费环境。金额同时提供分和元两种单位。",
    response_description="个人钱包与计费配置",
)
async def wallet(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
                 view: Literal["app", "production"] = "app") -> dict:
    from app.services.billing import wallet as funds
    from app.marketplace.coin_service import funds_call
    from app.marketplace import app_funds
    account_environment = "unresolved"
    try:
        account_environment = (await app_funds.wallet_view_environment(db, user.id)
                               if view == "app" else funds.configured_environment())
        if app_funds.isolated(account_environment):
            state = await funds_call(app_funds.snapshot(db, user.id, account_environment))
        else:
            state = await funds_call(funds.snapshot(db, user.id)) if funds.enabled() else {}
    except Exception as exc:
        from app.services.billing.diagnostics import failure_fields
        error_type, status, code = failure_fields(exc)
        logger.warning(
            "Wallet query failed user_id=%s view=%s environment=%s unified_enabled=%s type=%s status=%s code=%s",
            user.id, view, account_environment, funds.enabled(), error_type, status, code,
        )
        raise
    balance = int(state.get("balance_fen", user.balance_fen or 0))
    frozen = int(state.get("frozen_fen", user.frozen_fen or 0))
    return {
        "balance_fen": balance,
        "frozen_fen": frozen,
        "balance_yuan": round(balance / 100, 2),
        "frozen_yuan": round(frozen / 100, 2),
        "plan": user.plan or "free",
        "billing_enabled": settings.billing_enabled,
        "markup": settings.billing_markup,
        "unified_wallet_enabled": funds.enabled(),
        "environment": account_environment,
        "wallet_type": "platform_balance",
        "test_only": False,
        **state,
    }


@router.get(
    "/skus",
    openapi_extra=APP_IDENTITY_OPENAPI,
    summary="获取充值套餐",
    description="无需登录，返回可购买的充值套餐、支持的支付方式及计费倍率。",
    response_description="充值套餐与支付方式",
)
async def list_skus(request: Request, user: Visitor = None, language: Literal["zh", "en"] = Query("zh"), channel: Literal["web", "apple_iap", "android_epay"] = "web", app_edition: Literal["domestic", "international"] | None = None, db: AsyncSession = Depends(get_db), response: Response = None) -> dict:
    if channel == "apple_iap":
        from app.marketplace.apple_api import coin_products
        from app.marketplace.app_bootstrap import require_schema
        await require_schema(request)
        result = await coin_products(db, user, app_edition, request, response)
        return {**result, "skus": result["items"], "pay_types": ["apple_iap"] if result["purchasing_enabled"] else []}
    if channel == "android_epay":
        from app.services.billing.android_epay import check_identity
        from app.services.billing.android_epay_config import readiness
        from app.marketplace.app_bootstrap import require_schema
        await require_schema(request)
        check_identity(request, get_settings())
        if app_edition not in (None, "domestic"):
            raise HTTPException(409, detail="ANDROID_EPAY_APP_MISMATCH")
        state = readiness()
        items = [dict(sku) for sku in billing.SKUS] if state["available"] else []
        return {**state, "purchasing_enabled": state["available"], "items": items, "skus": items,
                "app_edition": "domestic"}
    stripe_settings = get_settings()
    stripe_ready = stripe_payments.is_ready(stripe_settings, language=language)
    return {
        "skus": [
            {**sku, **({"stripe_quote": stripe_payments.quote_payment(int(sku["amount_fen"]), stripe_settings, language=language, sku_id=sku["id"])} if stripe_ready else {})}
            for sku in billing.SKUS
        ],
        "pay_types": ["alipay", "wxpay"] + (["stripe"] if stripe_ready else []),
        "stripe_unavailable_reason": (
            "usd_rate_missing" if stripe_settings.stripe_enabled and stripe_settings.stripe_currency == "auto"
            and language == "en" and not stripe_settings.stripe_usd_cny_rate.strip() else None
        ),
        "markup": settings.billing_markup,
    }


@router.get(
    "/preflight",
    summary="预检任务批次余额",
    description=(
        "需要登录，在任务入队前计算单项估算、在途承诺金额和本批次总需求。"
        "指定团队时校验成员资格，并按团队计费规则检查；非所有者不返回付款账户余额。"
        "本接口不会创建生成任务。"
    ),
    response_description="余额预检及费用估算结果",
)
async def billing_preflight(
    domain: str = Query(..., min_length=1, description="任务所属业务域，例如 kepu、drama 或 studio"),
    task_type: str = Query(..., min_length=1, description="任务类型标识"),
    count: int = Query(1, ge=1, le=500, description="本次计划提交的任务数量"),
    team_id: int | None = Query(None, ge=1, description="团队空间编号；不传时使用个人空间"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """需要登录，在任务入队前计算单项估算、在途承诺金额和本批次总需求。指定团队时校验成员资格，并按团队计费规则检查；非所有者不返回付款账户余额。本接口不会创建生成任务。"""
    member = None
    team = None
    if team_id is not None:
        from app.services.teams.access import get_team
        team, member = await get_team(db, team_id, user.id)
    if not billing_active(user):
        result = {
            "ok": True,
            "billing_enabled": False,
            "balance_fen": int(user.balance_fen or 0),
            "unit_estimate_fen": 0,
            "pending_commitment_fen": 0,
            "requested_total_fen": 0,
            "required_total_fen": 0,
        }
        if team_id is not None:
            if team.owner_user_id == user.id:
                result["balance_fen"] = int(user.balance_fen or 0)
            else:
                result.pop("balance_fen", None)
        return result
    probe = TaskRun(
        domain=domain.strip(),
        task_type=task_type.strip(),
        requested_by=user.id,
        team_id=team_id,
        payload={},
    )
    try:
        summary = await ensure_balance_for_task_batch(db, user, probe, count)
    except ValueError as exc:
        raise http_exception_for_value_error(exc) from exc
    result = {
        "ok": True,
        "billing_enabled": True,
        "balance_fen": summary["balance_fen"],
        "balance_yuan": round(summary["balance_fen"] / 100, 2),
        "unit_estimate_fen": summary["unit_estimate_fen"],
        "unit_estimate_yuan": round(summary["unit_estimate_fen"] / 100, 2),
        "pending_commitment_fen": summary["pending_commitment_fen"],
        "pending_commitment_yuan": round(summary["pending_commitment_fen"] / 100, 2),
        "requested_total_fen": summary["requested_total_fen"],
        "requested_total_yuan": round(summary["requested_total_fen"] / 100, 2),
        "required_total_fen": summary["required_total_fen"],
        "required_total_yuan": round(summary["required_total_fen"] / 100, 2),
        "count": int(count),
        "domain": domain.strip(),
        "task_type": task_type.strip(),
    }
    if team is not None and team.owner_user_id != user.id:
        result.pop("balance_fen", None)
        result.pop("balance_yuan", None)
    return result


def _client_ip(request: Request) -> str:
    """Prefer proxy headers, fall back to direct peer address."""
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


@router.post(
    "/orders",
    openapi_extra=APP_IDENTITY_OPENAPI,
    summary="创建个人充值订单",
    description=(
        "需要登录，选择充值套餐及支付宝、微信或已启用的 Stripe 支付方式，返回二维码或收银台链接和订单有效期。"
        "创建订单不会立即增加余额，实际到账由支付回调确认。"
    ),
    response_description="充值订单与支付信息",
)
async def create_order(
    body: CreateOrderBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if body.client == "web" and request.headers.get("X-App-Package-Name"):
        raise HTTPException(422, detail="ANDROID_EPAY_CLIENT_REQUIRED")
    if body.client == "android":
        from app.services.billing.android_epay import create_checkout
        from app.marketplace.app_bootstrap import require_schema
        await require_schema(request)
        return await create_checkout(db, user.id, body, request, _client_ip(request))
    if body.pay_type == "apple_iap":
        from app.marketplace.apple_api import purchasing_enabled_for_app, resolve_app_edition
        from app.marketplace.app_bootstrap import require_schema
        from app.marketplace.apple_recharge import find_product_for_sku
        from app.marketplace.apple_service import purchase_intent
        from app.marketplace.coin_service import app_fail
        await require_schema(request)
        edition = resolve_app_edition(request, body.app_edition if "app_edition" in body.model_fields_set else None)
        if not await purchasing_enabled_for_app(user.id, edition):
            app_fail("MARKETPLACE_PAYMENT_UNAVAILABLE", "苹果充值暂不可用，请稍后重试。", 503)
        if not body.idempotency_key:
            app_fail("MARKETPLACE_IDEMPOTENCY_REQUIRED", "请提供充值操作编号。", 422)
        product = await find_product_for_sku(db, body.sku_id, edition)
        from app.marketplace.sandbox_wallet import environment
        result = await purchase_intent(db, user.id, environment(user.id), product.product_id, body.idempotency_key)
        await db.commit()
        return result
    if body.pay_type == "stripe" and not stripe_payments.is_ready(language=body.language):
        raise HTTPException(status_code=503, detail="Stripe 支付未启用或未完成配置")
    # 下单前先清理该用户已过期的待支付单
    await billing.close_expired_pending_orders(db, user_id=user.id)
    sku = billing.sku_by_id(body.sku_id)
    if not sku:
        raise HTTPException(status_code=400, detail="未知充值包")
    payment = {}
    if body.pay_type == "stripe":
        try:
            payment = stripe_payments.quote_payment(int(sku["amount_fen"]), language=body.language, sku_id=sku["id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    out_trade_no = f"PF{int(time.time())}{user.id:04d}{uuid.uuid4().hex[:8]}"
    order = Order(
        out_trade_no=out_trade_no,
        user_id=user.id,
        sku_id=sku["id"],
        amount_fen=int(sku["amount_fen"]),
        credit_fen=int(sku["credit_fen"]),
        pay_type=body.pay_type,
        payment_client="web",
        status="pending",
        **payment,
    )
    db.add(order)
    await db.commit()
    if body.pay_type == "stripe":
        try:
            session = await stripe_payments.create_checkout_session(order=order, sku_name=str(sku["name"]))
        except (ValueError, stripe.StripeError) as exc:
            order.status = "closed"
            await db.commit()
            logger.warning("stripe checkout unavailable order=%s error=%s", out_trade_no, type(exc).__name__)
            raise HTTPException(status_code=503, detail="Stripe 收银台暂不可用，请稍后重试") from exc
        order.trade_no = str(session["id"])
        await db.commit()
        return {
            "out_trade_no": out_trade_no,
            "sku_id": sku["id"], "sku_name": str(sku["name"]),
            "pay_type": "stripe", "amount_fen": order.amount_fen, "credit_fen": order.credit_fen,
            "trade_no": order.trade_no, "payurl": session["url"], "pay_mode": "redirect",
            "qrcode": "", "img": "", "qr_payload": "", "submit_url": "",
            "expire_seconds": stripe_payments.CHECKOUT_EXPIRE_SECONDS,
            **stripe_payments.payment_snapshot(order),
        }
    money_yuan = epay.money_yuan_from_fen(int(sku["amount_fen"]))
    try:
        mapi = await epay.create_mapi_payment(
            out_trade_no=out_trade_no,
            name=str(sku["name"]),
            money_yuan=money_yuan,
            pay_type=body.pay_type,
            clientip=_client_ip(request),
        )
        fields = epay.build_submit_fields(
            out_trade_no=out_trade_no,
            name=str(sku["name"]),
            money_yuan=money_yuan,
            pay_type=body.pay_type,
            clientip=_client_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "out_trade_no": out_trade_no,
        "sku_id": sku["id"],
        "sku_name": str(sku["name"]),
        "pay_type": body.pay_type,
        "amount_fen": order.amount_fen,
        "credit_fen": order.credit_fen,
        "trade_no": mapi.get("trade_no") or "",
        "qrcode": mapi.get("qrcode") or "",
        "payurl": mapi.get("payurl") or "",
        "img": mapi.get("img") or "",
        "qr_payload": mapi.get("qr_payload") or "",
        "pay_mode": mapi.get("pay_mode") or ("qr" if mapi.get("qr_payload") else "redirect"),
        "expire_seconds": billing.ORDER_EXPIRE_SECONDS,
        "submit_url": epay.submit_url(fields),
        **stripe_payments.payment_snapshot(order),
    }


@router.get(
    "/usage/summary",
    summary="获取本月个人用量汇总",
    description=(
        "需要登录，按 UTC 月初汇总个人空间消费及由本人付款的消费，返回调用次数、Token 数量、扣费金额和当前余额。"
        "金额提供分和元两种单位。"
    ),
    response_description="本月用量与钱包汇总",
)
async def usage_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """需要登录，按 UTC 月初汇总个人空间消费及由本人付款的消费，返回调用次数、Token 数量、扣费金额和当前余额。金额提供分和元两种单位。"""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
            func.coalesce(func.sum(UsageEvent.charge_fen), 0),
            func.count(UsageEvent.id),
        ).where(
            or_((UsageEvent.user_id == user.id) & UsageEvent.team_id.is_(None), UsageEvent.billing_payer_user_id == user.id),
            UsageEvent.created_at >= month_start,
        )
    )
    tokens, charge_fen, calls = result.one()
    return {
        "period": month_start.strftime("%Y-%m"),
        "tokens": int(tokens or 0),
        "charge_fen": int(charge_fen or 0),
        "charge_yuan": round(int(charge_fen or 0) / 100, 2),
        "calls": int(calls or 0),
        "balance_fen": int(user.balance_fen or 0),
        "balance_yuan": round(int(user.balance_fen or 0) / 100, 2),
        "frozen_fen": int(user.frozen_fen or 0),
        "frozen_yuan": round(int(user.frozen_fen or 0) / 100, 2),
    }


@router.get(
    "/alerts/pending",
    summary="获取待确认额度告警",
    description="需要登录，返回当前用户尚待展示或确认的额度告警，包含标题、内容、额度阈值和创建时间。",
    response_description="待确认的额度告警列表",
)
async def billing_alerts_pending(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """需要登录，返回当前用户尚待展示或确认的额度告警，包含标题、内容、额度阈值和创建时间。"""
    from app.services.billing.alerts import list_pending_user_alerts

    rows = await list_pending_user_alerts(db, user.id)
    await db.commit()
    return {
        "items": [
            {
                "id": row.id,
                "kind": row.kind,
                "title": row.title,
                "message": row.message,
                "milestone_fen": int(row.milestone_fen or 0),
                "milestone_yuan": round(int(row.milestone_fen or 0) / 100, 2),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.post(
    "/alerts/{alert_id}/ack",
    summary="确认额度告警",
    description="需要登录，确认当前用户的指定额度告警；告警不存在或不属于当前用户时返回 404。",
    response_description="告警确认结果",
)
async def billing_alert_ack(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from app.services.billing.alerts import acknowledge_user_alert

    ok = await acknowledge_user_alert(db, user.id, alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="告警不存在")
    await db.commit()
    return {"ok": True}


@router.get(
    "/usage/events",
    summary="分页查询个人扣费记录",
    description="需要登录，按记录编号倒序查询个人空间消费及由本人付款的消费明细，包含项目、计费项、模型、Token 和扣费金额。",
    response_description="扣费明细及分页信息",
)
async def usage_events(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页返回的记录数"),
) -> dict:
    """需要登录，按记录编号倒序查询个人空间消费及由本人付款的消费明细，包含项目、计费项、模型、Token 和扣费金额。"""
    from app.models_drama import DramaProject

    count_stmt = select(func.count()).select_from(UsageEvent).where(or_((UsageEvent.user_id == user.id) & UsageEvent.team_id.is_(None), UsageEvent.billing_payer_user_id == user.id))
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    stmt = (
        select(UsageEvent, Project.title, DramaProject.title)
        .outerjoin(Project, UsageEvent.project_id == Project.id)
        .outerjoin(DramaProject, UsageEvent.drama_project_id == DramaProject.id)
        .where(or_((UsageEvent.user_id == user.id) & UsageEvent.team_id.is_(None), UsageEvent.billing_payer_user_id == user.id))
        .order_by(UsageEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).all()

    items = []
    for ev, kepu_title, drama_title in rows:
        if drama_title:
            context = f"漫剧 · {drama_title}"
        elif kepu_title:
            context = f"科普 · {kepu_title}"
        elif ev.project_id:
            context = f"科普 · 项目 #{ev.project_id}"
        elif ev.drama_project_id:
            context = f"漫剧 · 项目 #{ev.drama_project_id}"
        else:
            context = "工具创作"
        charge_fen = int(ev.charge_fen or 0)
        items.append(
            {
                "id": ev.id,
                "billing_key": ev.billing_key,
                "billing_label": billing.billing_key_label(ev.billing_key),
                "model": ev.model or "",
                "context": context,
                "total_tokens": int(ev.total_tokens or 0),
                "charge_fen": charge_fen,
                "charge_yuan": round(charge_fen / 100, 2),
                "estimated": bool(ev.estimated),
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
        )
    return {
        "items": items,
        "meta": {"page": page, "page_size": page_size, "total": total},
    }


@router.get(
    "/orders",
    summary="查询个人充值订单",
    description="需要登录，按创建时间倒序返回当前用户的个人充值订单，并自动关闭已过期待支付订单；不包含历史团队订单。",
    response_description="个人充值订单列表",
)
async def list_orders(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100, description="最多返回的记录数"),
    view: Literal["app", "production"] = Query("app", description="App 可查看本人的 Google 测试订单；Web 使用 production。"),
) -> dict:
    """需要登录，按创建时间倒序返回当前用户的个人充值订单，并自动关闭已过期待支付订单；不包含历史团队订单。"""
    await billing.close_expired_pending_orders(db, user_id=user.id)
    environment = get_settings().wallet_environment
    environment_filter = func.coalesce(Order.payment_environment, "Production") == environment
    if view == "app" and environment == "Production":
        environment_filter = or_(
            environment_filter,
            (Order.payment_environment == "Sandbox") & (Order.pay_type == "google_play"),
        )
    result = await db.execute(
        select(Order)
        .where(Order.user_id == user.id, Order.team_id.is_(None), environment_filter)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    items = []
    for o in rows:
        sku = billing.sku_by_id(o.sku_id) or {}
        items.append(
            {
                "out_trade_no": o.out_trade_no,
                "sku_id": o.sku_id,
                "sku_name": str(sku.get("name") or o.sku_id),
                "amount_fen": o.amount_fen,
                "credit_fen": o.credit_fen,
                "pay_type": o.pay_type,
                "payment_client": payment_client(o),
                "environment": o.payment_environment,
                "test_only": o.payment_environment == "Sandbox",
                "status": o.status,
                "trade_no": o.trade_no,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                **stripe_payments.payment_snapshot(o),
            }
        )
    google_orders = [o.id for o in rows if o.pay_type == "google_play"]
    if google_orders:
        from app.marketplace.google_models import GooglePurchase
        purchases = {p.order_id: p for p in (await db.scalars(select(GooglePurchase).where(GooglePurchase.order_id.in_(google_orders)))).all()}
        for order, item in zip(rows, items):
            if order.pay_type != "google_play":
                continue
            purchase = purchases.get(order.id)
            micros = purchase.amount_micros if purchase else None
            item.update(currency=purchase.currency if purchase else None, amount_micros=micros,
                amount_fen=(micros // 10000 if micros is not None else None))
    return {"orders": items}


@router.get(
    "/orders/{out_trade_no}",
    summary="获取个人充值订单状态",
    description="需要登录，仅可读取本人个人充值订单；查询前关闭该订单的过期待支付状态，返回支付状态、金额和到账时间。",
    response_description="个人充值订单状态",
)
async def get_order(
    out_trade_no: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    await billing.close_expired_pending_orders(db, user_id=user.id, out_trade_no=out_trade_no)
    result = await db.execute(select(Order).where(Order.out_trade_no == out_trade_no))
    order = result.scalar_one_or_none()
    if not order or order.user_id != user.id or order.team_id is not None:
        raise HTTPException(status_code=404, detail="订单不存在")
    snapshot = stripe_payments.payment_snapshot(order)
    if order.pay_type == "google_play":
        from app.marketplace.google_models import GooglePurchase
        purchase = await db.scalar(select(GooglePurchase).where(GooglePurchase.order_id == order.id))
        micros = purchase.amount_micros if purchase else None
        snapshot.update(currency=purchase.currency if purchase else None, amount_micros=micros,
            amount_fen=micros // 10000 if micros is not None else None)
    return {
        "out_trade_no": order.out_trade_no,
        "status": order.status,
        "payment_client": payment_client(order),
        "environment": order.payment_environment,
        "test_only": order.payment_environment == "Sandbox" if order.payment_environment else None,
        "amount_fen": order.amount_fen,
        "credit_fen": order.credit_fen,
        "pay_type": order.pay_type,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        **snapshot,
    }


@router.post(
    "/orders/{out_trade_no}/close",
    summary="关闭个人充值订单",
    description="需要登录，仅可关闭本人的待支付个人订单。已关闭订单可重复请求，已支付订单不能关闭。",
    response_description="关闭后的订单状态",
)
async def close_order(
    out_trade_no: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """需要登录，仅可关闭本人的待支付个人订单。已关闭订单可重复请求，已支付订单不能关闭。"""
    result = await db.execute(
        select(Order).where(Order.out_trade_no == out_trade_no).with_for_update()
        .execution_options(populate_existing=True)
    )
    order = result.scalar_one_or_none()
    if not order or order.user_id != user.id or order.team_id is not None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == "paid":
        raise HTTPException(status_code=400, detail="已支付订单无法关闭")
    if order.status == "closed":
        return {"out_trade_no": order.out_trade_no, "status": "closed"}
    if order.status != "pending":
        raise HTTPException(status_code=400, detail="当前状态不可关闭")
    if order.pay_type == "google_play":
        raise HTTPException(status_code=409, detail="Google Play 付款状态由商店确认，不能在本站关闭；请在 App 中取消或等待付款结果。")
    if order.pay_type == "stripe":
        if not order.trade_no:
            raise HTTPException(status_code=409, detail="Stripe 收银台正在创建，请稍后重试")
        try:
            await stripe_payments.expire_checkout_session(order.trade_no)
        except (ValueError, stripe.StripeError) as exc:
            # A completed Checkout may be waiting for its paid webhook. Leave
            # it pending rather than locally cancelling a successful payment.
            raise HTTPException(status_code=409, detail="Stripe 订单暂不能关闭，请刷新支付状态后重试") from exc
    order.status = "closed"
    await db.commit()
    return {"out_trade_no": order.out_trade_no, "status": "closed"}


@router.post(
    "/stripe/webhook",
    summary="接收 Stripe 支付通知",
    description="无需登录，使用原始请求体验证 Stripe-Signature；严格校验已绑定订单、金额及币种后幂等入账。",
)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    if not get_settings().stripe_webhook_secret.strip():
        raise HTTPException(status_code=503, detail="Stripe Webhook 未配置")
    # Signature verification requires the exact bytes, never request.json().
    payload = await request.body()
    try:
        event = stripe_payments.construct_event(payload, request.headers.get("stripe-signature", ""))
        await stripe_payments.handle_checkout_event(db, event)
    except ValueError as exc:
        await db.rollback()
        logger.warning("stripe webhook rejected error=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="无效的 Stripe 支付通知") from exc
    await db.commit()
    return {"received": True}


def _notify_success(params: dict) -> bool:
    """判断易支付回调是否支付成功（兼容 trade_status/status 两种字段）。"""
    status = str(params.get("trade_status") or params.get("status") or "").strip().upper()
    return status in {"TRADE_SUCCESS", "SUCCESS", "1"}


@router.get(
    "/epay/notify",
    summary="接收易支付支付通知",
    description=(
        "支付网关通过 GET 查询参数或 POST 表单提交通知，无需登录令牌，但必须通过签名及金额校验。"
        "成功支付后幂等入账；历史团队订单回款到原下单人的个人账户。"
    ),
    response_description="纯文本 success 或 fail",
    response_class=PlainTextResponse,
)
@router.post(
    "/epay/notify",
    summary="接收易支付支付通知",
    description=(
        "支付网关通过 GET 查询参数或 POST 表单提交通知，无需登录令牌，但必须通过签名及金额校验。"
        "成功支付后幂等入账；历史团队订单回款到原下单人的个人账户。"
    ),
    response_description="纯文本 success 或 fail",
    response_class=PlainTextResponse,
)
async def epay_notify(request: Request, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    from app.marketplace.app_bootstrap import require_schema
    await require_schema(request)
    from app.services.billing.epay_fulfillment import fulfill
    if request.method == "POST":
        raw = await request.body()
        if len(raw) > 16384:
            return PlainTextResponse("fail", status_code=413)
        pairs = list((await request.form()).multi_items())
    else:
        if len(request.url.query) > 16384:
            return PlainTextResponse("fail", status_code=413)
        pairs = list(request.query_params.multi_items())
    if len(pairs) > 40 or len({k for k, _ in pairs}) != len(pairs):
        return PlainTextResponse("fail", status_code=400)
    return await fulfill(db, {k: str(v) for k, v in pairs})
