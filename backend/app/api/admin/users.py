# Admin user list and wallet/plan patch
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_admin
from app.models import User, WalletLedger
from app.schemas import AdminUserListOut, AdminUserOut, AdminUserPatch, PageMeta

router = APIRouter()


@router.get("/users", response_model=AdminUserListOut)
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


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def patch_user(
    user_id: int,
    body: AdminUserPatch,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    # Update plan / role; balance changes write WalletLedger
    user = await db.get(User, user_id)
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

    if body.balance_fen is not None:
        target = int(body.balance_fen)
        if target < 0:
            raise HTTPException(status_code=400, detail="余额不能为负")
        current = int(user.balance_fen or 0)
        delta = target - current
        if delta != 0:
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
