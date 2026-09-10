# Admin wallet ledger list
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.deps import get_current_admin
from app.models import User, WalletLedger
from app.schemas import AdminLedgerListOut, AdminLedgerOut, PageMeta

router = APIRouter()


@router.get("/ledger", response_model=AdminLedgerListOut)
async def list_ledger(
    user_id: int | None = None,
    kind: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLedgerListOut:
    # Paginated wallet ledger with owner email
    owner = aliased(User)
    stmt = select(WalletLedger, owner.email).outerjoin(owner, owner.id == WalletLedger.user_id)
    count_stmt = select(func.count()).select_from(WalletLedger)

    if user_id is not None:
        stmt = stmt.where(WalletLedger.user_id == user_id)
        count_stmt = count_stmt.where(WalletLedger.user_id == user_id)
    if kind and kind.strip():
        stmt = stmt.where(WalletLedger.kind == kind.strip())
        count_stmt = count_stmt.where(WalletLedger.kind == kind.strip())

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(WalletLedger.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items: list[AdminLedgerOut] = []
    for entry, email in rows:
        data = AdminLedgerOut.model_validate(entry)
        data.user_email = email
        items.append(data)

    return AdminLedgerListOut(
        items=items, meta=PageMeta(page=page, page_size=page_size, total=total)
    )
