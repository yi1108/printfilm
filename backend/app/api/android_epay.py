"""Android payment read endpoints. No endpoint may manually mark a payment successful."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.deps import get_current_admin
from app.config import get_settings
from app.models import Order
from app.marketplace.android_epay_models import AndroidEpayCheckout
from app.services.billing.android_epay_config import readiness, validate, FIELDS
from app.services.billing.order_origin import ANDROID, payment_client

router = APIRouter()

@router.get("/api/billing/android-epay/return-config")
async def return_config():
    cfg = get_settings()
    from fastapi.responses import JSONResponse
    # Return enhancement is independent of purchasing readiness and merchant secrets.
    from app.marketplace.sharing_config import validate_share_origin
    try:
        origin = validate_share_origin(cfg.android_epay_return_base_url or cfg.public_base_url)
    except ValueError:
        origin = ""
    return JSONResponse({
        "android_epay_package_name": cfg.android_epay_package_name,
        "android_epay_app_scheme": cfg.android_epay_app_scheme,
        "android_epay_return_base_url": origin,
        "return_mode": "scheme" if cfg.android_epay_app_scheme else "manual",
    }, headers={"Cache-Control": "no-store"})

@router.get("/api/admin/billing/android-epay/status")
async def status(_admin=Depends(get_current_admin)):
    return readiness()

@router.get("/api/admin/billing/payment-orders")
async def orders(_admin=Depends(get_current_admin), db: AsyncSession=Depends(get_db),
                 source: str=Query("android_domestic", pattern="^(android_domestic|web|all)$"),
                 page: int=Query(1, ge=1), page_size: int=Query(20, ge=1, le=100)):
    query = select(Order).where(Order.pay_type.in_(("alipay", "wxpay", "stripe")))
    if source == ANDROID:
        query = query.where(Order.payment_client == ANDROID)
    elif source == "web":
        query = query.where(func.coalesce(Order.payment_client, "web") == "web")
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list((await db.scalars(query.order_by(Order.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
    ids = [o.id for o in rows]
    checkouts = {c.order_id:c for c in (await db.scalars(select(AndroidEpayCheckout).where(AndroidEpayCheckout.order_id.in_(ids)))).all()} if ids else {}
    return {"total": total, "page": page, "items": [{
        "out_trade_no": o.out_trade_no, "user_id": o.user_id, "payment_client": payment_client(o),
        "pay_type": o.pay_type, "status": o.status, "amount_fen": o.amount_fen,
        "payment_currency": o.payment_currency or "cny",
        "payment_amount_minor": o.payment_amount_minor if o.payment_amount_minor is not None else (o.amount_fen if not o.payment_currency or o.payment_currency.lower() == "cny" else None),
        "credit_fen": o.credit_fen, "environment": o.payment_environment or "Production",
        "checkout_status": checkouts[o.id].state if o.id in checkouts else None,
        "error_code": checkouts[o.id].error_code if o.id in checkouts else None,
        "created_at": o.created_at,
    } for o in rows]}
