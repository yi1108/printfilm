# Admin user list and wallet/plan patch
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_admin
from app.models import User, WalletLedger
from app.schemas import AdminUserListOut, AdminUserOut, AdminUserPatch, PageMeta

router = APIRouter()


@router.get("/users", response_model=AdminUserListOut,
    summary="分页查询用户",
    description="管理员按邮箱、昵称或用户编号搜索用户，可按套餐和角色筛选；结果按用户编号倒序返回。",
    response_description="操作成功，返回结果详见响应结构",
)
async def list_users(
    q: str | None = None,
    plan: str | None = None,
    role: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserListOut:
    # Paginated user search by email / nickname / id
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if q and q.strip():
        raw = q.strip()
        like = f"%{raw}%"
        id_match = None
        if raw.isdigit():
            id_match = int(raw)
        filt = or_(User.email.ilike(like), User.nickname.ilike(like))
        if id_match is not None:
            filt = or_(filt, User.id == id_match)
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    if plan and plan.strip():
        stmt = stmt.where(User.plan == plan.strip())
        count_stmt = count_stmt.where(User.plan == plan.strip())
    if role and role.strip():
        stmt = stmt.where(User.role == role.strip())
        count_stmt = count_stmt.where(User.role == role.strip())

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    result = await db.execute(
        stmt.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = list(result.scalars().all())
    return AdminUserListOut(
        items=[AdminUserOut.model_validate(u) for u in items],
        meta=PageMeta(page=page, page_size=page_size, total=total),
    )


@router.patch("/users/{user_id}", response_model=AdminUserOut,
    summary="更新用户套餐、角色或余额",
    description="管理员局部更新用户套餐、角色或个人钱包余额。balance_delta_fen 为增减金额，balance_fen 为目标余额，两者不能同时传入，金额单位为分；余额变化会记录钱包流水。不能将余额减为负数，也不能降低自己的管理员权限。",
    response_description="操作成功，返回结果详见响应结构",
)
async def patch_user(
    user_id: int,
    body: AdminUserPatch,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    # Update plan / role; balance changes write WalletLedger
    user = (await db.execute(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if body.plan is not None:
        user.plan = body.plan.strip() or "free"

    if body.role is not None:
        role = body.role.strip()
        if role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="role 仅支持 user 或 admin")
        if user.id == admin.id and role != "admin":
            raise HTTPException(status_code=400, detail="不能降低自己的管理员权限")
        user.role = role

    if body.balance_delta_fen is not None and body.balance_fen is not None:
        raise HTTPException(status_code=400, detail="请只传 balance_delta_fen 或 balance_fen 之一")

    current = int(user.balance_fen or 0)
    delta: int | None = None
    if body.balance_delta_fen is not None:
        delta = int(body.balance_delta_fen)
    elif body.balance_fen is not None:
        target = int(body.balance_fen)
        if target < 0:
            raise HTTPException(status_code=400, detail="余额不能为负")
        delta = target - current

    if delta is not None and delta != 0:
        from app.services.billing import wallet
        if wallet.enabled():
            import uuid
            from app.marketplace.coin_service import funds_call
            ref = f"admin:{admin.id}:{uuid.uuid4().hex}"
            if delta > 0:
                await funds_call(wallet.credit(db, user.id, delta, source_type="admin_grant", source_ref=ref, note=body.balance_note or "admin_adjust"))
            else:
                await funds_call(wallet.consume(db, user.id, -delta, business_type="admin_adjustment", business_ref=ref))
            await db.commit()
            await db.refresh(user)
            return AdminUserOut.model_validate(user)
        target = current + delta
        if target < 0:
            raise HTTPException(status_code=400, detail="余额不能减为负数")
        user.balance_fen = target
        db.add(
            WalletLedger(
                user_id=user.id,
                delta_fen=delta,
                balance_after=target,
                kind="adjust" if delta < 0 else "grant",
                ref_type="admin",
                ref_id=str(admin.id),
                note=(body.balance_note or "").strip() or "admin_adjust",
            )
        )

    await db.commit()
    await db.refresh(user)
    return AdminUserOut.model_validate(user)
