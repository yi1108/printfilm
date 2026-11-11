# Admin order list
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.deps import get_current_admin
from app.models import Order, User
from app.schemas import AdminOrderListOut, AdminOrderOut, PageMeta
from app.services.stripe_payments import payment_snapshot

router = APIRouter()


@router.get("/orders", response_model=AdminOrderListOut,
    summary="分页查询充值订单",
    description="管理员按订单状态、所属用户或商户订单号精确筛选充值订单，返回订单及用户邮箱，按订单编号倒序排列。",
    response_description="操作成功，返回结果详见响应结构",
)
async def list_orders(
    status: str | None = None,
    user_id: int | None = None,
    out_trade_no: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminOrderListOut:
    # Paginated recharge orders with owner email
    owner = aliased(User)
    production = func.coalesce(Order.payment_environment, "Production") == "Production"
    stmt = select(Order, owner.email).outerjoin(owner, owner.id == Order.user_id).where(production)
    count_stmt = select(func.count()).select_from(Order).where(production)

    if status and status.strip():
        stmt = stmt.where(Order.status == status.strip())
        count_stmt = count_stmt.where(Order.status == status.strip())
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
        count_stmt = count_stmt.where(Order.user_id == user_id)
    if out_trade_no and out_trade_no.strip():
        trade = out_trade_no.strip()
        stmt = stmt.where(Order.out_trade_no == trade)
        count_stmt = count_stmt.where(Order.out_trade_no == trade)

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(Order.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items: list[AdminOrderOut] = []
    for order, email in rows:
        data = AdminOrderOut.model_validate(order)
        data = data.model_copy(update=payment_snapshot(order))
        data.user_email = email
        items.append(data)

    return AdminOrderListOut(items=items, meta=PageMeta(page=page, page_size=page_size, total=total))
