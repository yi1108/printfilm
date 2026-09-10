# Admin unified task platform API
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_admin
from app.models import UsageEvent, User
from app.schemas import PageMeta
from app.schemas_tasks import AdminTaskListOut, AdminTaskRunOut, AdminTaskStatsOut, AdminUsageEventBriefOut, TaskRunOut
from app.services.billing.display import billing_basis_label, resolve_billing_basis
from app.services.tasks.runtime import runtime_summary
from app.services.tasks.service import cancel_task_admin, get_task_admin, get_task_stats_admin, list_tasks_admin

router = APIRouter()


def _task_to_admin_out(
    task,
    user_email: str | None,
    usage_lines: list[AdminUsageEventBriefOut] | None = None,
) -> AdminTaskRunOut:
    base = TaskRunOut.model_validate(task)
    return AdminTaskRunOut(**base.model_dump(), user_email=user_email, usage_lines=usage_lines or [])


async def _load_usage_lines(db: AsyncSession, task_id: int) -> list[AdminUsageEventBriefOut]:
    rows = (
        await db.execute(
            select(UsageEvent)
            .where(UsageEvent.task_run_id == task_id)
            .order_by(UsageEvent.id.asc())
        )
    ).scalars().all()
    items: list[AdminUsageEventBriefOut] = []
    for row in rows:
        basis = resolve_billing_basis(estimated=bool(row.estimated), raw_usage_json=row.raw_usage_json)
        items.append(
            AdminUsageEventBriefOut(
                id=row.id,
                billing_key=row.billing_key,
                capability=row.capability,
                model=row.model or "",
                total_tokens=int(row.total_tokens or 0),
                charge_fen=int(row.charge_fen or 0),
                cost_fen=int(row.cost_fen or 0),
                estimated=bool(row.estimated),
                billing_basis=basis,
                billing_basis_label=billing_basis_label(basis),
                created_at=row.created_at,
            )
        )
    return items


@router.get("/tasks/stats", response_model=AdminTaskStatsOut)
async def admin_task_stats(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminTaskStatsOut:
    # 任务平台聚合统计 + 运行时摘要
    stats = await get_task_stats_admin(db)
    runtime = runtime_summary()
    settings = get_settings()
    return AdminTaskStatsOut(
        **stats,
        scheduler_running_jobs=int(runtime.get("scheduler_running_jobs") or 0),
        max_concurrency=int(settings.task_runtime_max_concurrency),
        scheduler=str(runtime.get("scheduler") or "stopped"),
        poller=str(runtime.get("poller") or "stopped"),
        watchdog=str(runtime.get("watchdog") or "stopped"),
        runtime_healthy=bool(runtime.get("healthy")),
        fetched_at=datetime.now(UTC),
    )


@router.get("/tasks", response_model=AdminTaskListOut)
async def admin_list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    domain: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    user_id: int | None = None,
    q: str | None = None,
    active_only: bool = False,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminTaskListOut:
    # 分页列出全站 task_runs，支持领域/状态/用户筛选
    rows, total = await list_tasks_admin(
        db,
        page=page,
        page_size=page_size,
        domain=domain,
        status=status,
        task_type=task_type,
        user_id=user_id,
        q=q,
        active_only=active_only,
    )
    items = [_task_to_admin_out(task, email) for task, email in rows]
    return AdminTaskListOut(
        items=items,
        meta=PageMeta(page=page, page_size=page_size, total=total),
    )


@router.get("/tasks/{task_id}", response_model=AdminTaskRunOut)
async def admin_get_task(
    task_id: int,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminTaskRunOut:
    # 查看单条任务详情（含步骤与事件）
    try:
        task = await get_task_admin(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    email = (
        await db.execute(select(User.email).where(User.id == task.requested_by))
    ).scalar_one_or_none()
    usage_lines = await _load_usage_lines(db, task.id)
    return _task_to_admin_out(task, email, usage_lines)


@router.post("/tasks/{task_id}/cancel", response_model=AdminTaskRunOut)
async def admin_cancel_task(
    task_id: int,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminTaskRunOut:
    # 管理员取消任意进行中的任务
    try:
        task = await cancel_task_admin(db, task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    email = (
        await db.execute(select(User.email).where(User.id == task.requested_by))
    ).scalar_one_or_none()
    usage_lines = await _load_usage_lines(db, task.id)
    return _task_to_admin_out(task, email, usage_lines)
