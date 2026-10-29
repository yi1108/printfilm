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
from app.models import Order, Project, UsageEvent, User
from app.models_tasks import TaskRun
from app.services import billing, epay, stripe_payments
from app.services.billing.http import http_exception_for_value_error
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
    pay_type: Literal["alipay", "wxpay", "stripe"]
    language: Literal["zh", "en"] = "zh"


@router.get(
    "/wallet",
    summary="获取个人钱包余额",
    description="需要登录，返回个人可用余额、冻结金额、套餐和计费开关。金额同时提供分和元两种单位。",
    response_description="个人钱包与计费配置",
)
async def wallet(user: User = Depends(get_current_user)) -> dict:
    return {
        "balance_fen": int(user.balance_fen or 0),
        "frozen_fen": int(user.frozen_fen or 0),
        "balance_yuan": round(int(user.balance_fen or 0) / 100, 2),
        "frozen_yuan": round(int(user.frozen_fen or 0) / 100, 2),
        "plan": user.plan or "free",
        "billing_enabled": settings.billing_enabled,
        "markup": settings.billing_markup,
    }


@router.get(
    "/skus",
    summary="获取充值套餐",
    description="无需登录，返回可购买的充值套餐、支持的支付方式及计费倍率。",
    response_description="充值套餐与支付方式",
)
async def list_skus(language: Literal["zh", "en"] = Query("zh")) -> dict:
    stripe_settings = get_settings()
    stripe_ready = stripe_payments.is_ready(stripe_settings, language=language)
    return {
        "skus": [
            {**sku, **({"stripe_quote": stripe_payments.quote_payment(int(sku["amount_fen"]), stripe_settings, language=language)} if stripe_ready else {})}
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
            payment = stripe_payments.quote_payment(int(sku["amount_fen"]), language=body.language)
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
) -> dict:
    """需要登录，按创建时间倒序返回当前用户的个人充值订单，并自动关闭已过期待支付订单；不包含历史团队订单。"""
    await billing.close_expired_pending_orders(db, user_id=user.id)
    result = await db.execute(
        select(Order)
        .where(Order.user_id == user.id, Order.team_id.is_(None))
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
                "status": o.status,
                "trade_no": o.trade_no,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                **stripe_payments.payment_snapshot(o),
            }
        )
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
    return {
        "out_trade_no": order.out_trade_no,
        "status": order.status,
        "amount_fen": order.amount_fen,
        "credit_fen": order.credit_fen,
        "pay_type": order.pay_type,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        **stripe_payments.payment_snapshot(order),
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
    if request.method == "POST":
        form = await request.form()
        params = {k: str(v) for k, v in form.items()}
    else:
        params = {k: str(v) for k, v in request.query_params.items()}

    if not epay.verify(params):
        logger.warning("epay notify bad sign: %s", params)
        return PlainTextResponse("fail", status_code=400)

    if not _notify_success(params):
        return PlainTextResponse("success")

    out_trade_no = str(params.get("out_trade_no") or "")
    trade_no = str(params.get("trade_no") or params.get("transaction_id") or "")
    money = str(params.get("money") or "")
    if not out_trade_no:
        return PlainTextResponse("fail", status_code=400)

    # 行锁串行化同一订单的并发回调：第二个回调在锁释放后读到 paid 即幂等返回，
    # 避免重复入账（易支付会对同一笔支付重发多次 notify）。
    result = await db.execute(
        select(Order).where(Order.out_trade_no == out_trade_no).with_for_update().execution_options(populate_existing=True)
    )
    order = result.scalar_one_or_none()
    if not order:
        logger.warning("epay notify unknown order %s", out_trade_no)
        return PlainTextResponse("fail", status_code=404)
    if order.pay_type not in {"alipay", "wxpay"}:
        return PlainTextResponse("fail", status_code=400)

    # amount check
    try:
        amount = Decimal(money)
        if not amount.is_finite() or amount <= 0 or amount * 100 != (amount * 100).to_integral_value():
            return PlainTextResponse("fail", status_code=400)
        paid_fen = int(amount * 100)
    except (InvalidOperation, ValueError):
        return PlainTextResponse("fail", status_code=400)
    if paid_fen != int(order.amount_fen):
        logger.error(
            "epay amount mismatch order=%s expect=%s got=%s",
            out_trade_no,
            order.amount_fen,
            paid_fen,
        )
        return PlainTextResponse("fail", status_code=400)

    if order.status == "paid":
        return PlainTextResponse("success")

    user = await db.get(User, order.user_id)
    if not user:
        return PlainTextResponse("fail", status_code=404)

    order.status = "paid"
    order.trade_no = trade_no or None
    order.paid_at = datetime.now(timezone.utc)
    # 历史团队订单回款到原下单人的个人账户，转让不改变收款归属。
    await billing.credit_topup(
        db, user, int(order.credit_fen), ref_type="order", ref_id=order.out_trade_no,
        note=f"epay:{order.pay_type}" + (f" legacy_team:{order.team_id}" if order.team_id else ""),
    )
    await db.commit()
    logger.info("epay paid order=%s user=%s credit=%s", out_trade_no, user.id, order.credit_fen)
    return PlainTextResponse("success")

