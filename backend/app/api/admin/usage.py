# Admin usage events API
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.deps import get_current_admin
from app.models import UsageEvent, User
from app.models_tasks import TaskRun
from app.schemas import PageMeta
from app.schemas_tasks import AdminUsageEventListOut, AdminUsageEventOut
from app.services.billing.display import (
    billing_basis_label,
    billing_basis_sql_filter,
    resolve_billing_basis,
)

router = APIRouter()


def _usage_event_out(
    ev: UsageEvent,
    *,
    email: str | None,
    task_domain: str | None,
    task_type: str | None,
    task_status: str | None,
) -> AdminUsageEventOut:
    basis = resolve_billing_basis(estimated=bool(ev.estimated), raw_usage_json=ev.raw_usage_json)
    return AdminUsageEventOut(
        id=ev.id,
        user_id=ev.user_id,
        user_email=email,
        task_run_id=ev.task_run_id,
        project_id=ev.project_id,
        drama_project_id=ev.drama_project_id,
        domain=ev.domain,
        capability=ev.capability,
        billing_key=ev.billing_key,
        model=ev.model or "",
        provider=ev.provider,
        total_tokens=int(ev.total_tokens or 0),
        charge_fen=int(ev.charge_fen or 0),
        cost_fen=int(ev.cost_fen or 0),
        estimated=bool(ev.estimated),
        billing_basis=basis,
        billing_basis_label=billing_basis_label(basis),
        created_at=ev.created_at,
        task_domain=task_domain,
        task_type=task_type,
        task_status=task_status,
    )


@router.get("/usage-events", response_model=AdminUsageEventListOut)
async def list_usage_events(
    user_id: int | None = None,
    task_run_id: int | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    domain: str | None = None,
    billing_key: str | None = None,
    capability: str | None = None,
    estimated: bool | None = None,
    billing_basis: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUsageEventListOut:
    """分页列出用量明细，支持用户/任务/领域筛选。"""
    owner = aliased(User)
    task = aliased(TaskRun)
    filters = []
    if user_id is not None:
        filters.append(UsageEvent.user_id == user_id)
    if task_run_id is not None:
        filters.append(UsageEvent.task_run_id == task_run_id)
    if project_id is not None:
        filters.append(UsageEvent.project_id == project_id)
    if drama_project_id is not None:
        filters.append(UsageEvent.drama_project_id == drama_project_id)
    if domain and domain.strip():
        filters.append(UsageEvent.domain == domain.strip())
    if billing_key and billing_key.strip():
        filters.append(UsageEvent.billing_key == billing_key.strip())
    if capability and capability.strip():
        filters.append(UsageEvent.capability == capability.strip())
    if estimated is not None:
        filters.append(UsageEvent.estimated.is_(estimated))
    basis = (billing_basis or "").strip().lower()
    if basis and estimated is None:
        basis_filter = billing_basis_sql_filter(basis)
        if basis_filter is not None:
            filters.append(basis_filter)
    if created_from is not None:
        filters.append(UsageEvent.created_at >= created_from)
    if created_to is not None:
        filters.append(UsageEvent.created_at <= created_to)

    count_stmt = select(func.count()).select_from(UsageEvent)
    stmt = (
        select(UsageEvent, owner.email, task.domain, task.task_type, task.status)
        .outerjoin(owner, owner.id == UsageEvent.user_id)
        .outerjoin(task, task.id == UsageEvent.task_run_id)
    )
    for clause in filters:
        count_stmt = count_stmt.where(clause)
        stmt = stmt.where(clause)

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(UsageEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items: list[AdminUsageEventOut] = []
    for ev, email, task_domain, task_type, task_status in rows:
        items.append(
            _usage_event_out(
                ev,
                email=email,
                task_domain=task_domain,
                task_type=task_type,
                task_status=task_status,
            )
        )

    return AdminUsageEventListOut(
        items=items,
        meta=PageMeta(page=page, page_size=page_size, total=total),
    )
