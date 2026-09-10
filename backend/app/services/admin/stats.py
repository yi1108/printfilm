"""管理端统计聚合：仪表盘调用量/费用/排行。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Date, case, cast, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Order, Project, UsageEvent, User
from app.models_drama import DramaProject

# 同一 task 内只应有一行的计费 key（并发双记时需折叠）；llm/tts 等同 key 多行合法保留
_SINGLE_SHOT_BILLING_KEY_PREFIXES = ("seedance",)
_SINGLE_SHOT_BILLING_KEYS = frozenset({"seedream"})


def _utc_today_start() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _utc_month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_key(value: Any) -> str:
    """把 DB 返回的 date/datetime/str 统一成 YYYY-MM-DD。"""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


async def _usage_day_expr(db: AsyncSession):
    """按日历日分桶（PostgreSQL CAST AS DATE）。"""
    _ = db
    return cast(UsageEvent.created_at, Date)


def _derived_capability_expr():
    """能力分桶：优先 billing_key 推导，与 billing_key_to_capability 语义一致。"""
    return case(
        (UsageEvent.billing_key == "llm_chat", "llm"),
        (UsageEvent.billing_key == "seedream", "image"),
        (UsageEvent.billing_key.like("seedance%"), "video"),
        (UsageEvent.billing_key == "tts", "tts"),
        (UsageEvent.billing_key.is_not(None), "other"),
        (UsageEvent.capability.is_not(None), UsageEvent.capability),
        else_="other",
    )


def _capability_scope_clause(capability: str) -> Any:
    """能力筛选：与分桶共用推导表达式。"""
    cap = (capability or "").strip().lower()
    if not cap or cap == "all":
        return True
    return _derived_capability_expr() == cap


def _usage_scope_filters(
    *,
    domain: str = "all",
    capability: str = "all",
) -> list[Any]:
    """领域 / 能力筛选条件（不含时间）。"""
    filters: list[Any] = []
    if domain and domain != "all":
        filters.append(UsageEvent.domain == domain)
    if capability and capability != "all":
        filters.append(_capability_scope_clause(capability))
    return filters


async def _usage_window_totals(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    scope_filters: list[Any] | None = None,
) -> dict[str, int]:
    """聚合 usage_events：calls / charge / cost。"""
    filters: list[Any] = list(scope_filters or [])
    if since is not None:
        filters.append(UsageEvent.created_at >= since)
    stmt = select(
        func.count(UsageEvent.id),
        func.coalesce(func.sum(UsageEvent.charge_fen), 0),
        func.coalesce(func.sum(UsageEvent.cost_fen), 0),
    )
    for clause in filters:
        stmt = stmt.where(clause)
    row = (await db.execute(stmt)).one()
    return {
        "calls": int(row[0] or 0),
        "charge_fen": int(row[1] or 0),
        "cost_fen": int(row[2] or 0),
    }


async def _group_usage(
    db: AsyncSession,
    *,
    group_col,
    since: datetime | None = None,
    scope_filters: list[Any] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """按某一列分组聚合 usage。"""
    key = func.coalesce(group_col, "unknown")
    stmt = (
        select(
            key.label("key"),
            func.count(UsageEvent.id).label("calls"),
            func.coalesce(func.sum(UsageEvent.charge_fen), 0).label("charge_fen"),
            func.coalesce(func.sum(UsageEvent.cost_fen), 0).label("cost_fen"),
        )
        .group_by(key)
        .order_by(func.coalesce(func.sum(UsageEvent.charge_fen), 0).desc())
    )
    filters: list[Any] = list(scope_filters or [])
    if since is not None:
        filters.append(UsageEvent.created_at >= since)
    for clause in filters:
        stmt = stmt.where(clause)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "key": str(r.key or "unknown"),
            "calls": int(r.calls or 0),
            "charge_fen": int(r.charge_fen or 0),
            "cost_fen": int(r.cost_fen or 0),
        }
        for r in rows
    ]


async def build_admin_dashboard_stats(
    db: AsyncSession,
    *,
    days: int = 7,
    domain: str = "all",
    capability: str = "all",
    top_metric: str = "charge",
) -> dict[str, Any]:
    """组装管理端仪表盘全部统计字段。"""
    today = _utc_today_start()
    month = _utc_month_start()
    window_days = max(1, min(30, int(days)))
    range_start = today - timedelta(days=window_days - 1)
    scope = _usage_scope_filters(domain=domain, capability=capability)

    user_count = int((await db.execute(select(func.count()).select_from(User))).scalar_one() or 0)
    drama_project_count = int(
        (await db.execute(select(func.count()).select_from(DramaProject))).scalar_one() or 0
    )

    paid_total = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(Order.amount_fen), 0)).where(Order.status == "paid")
            )
        ).scalar_one()
        or 0
    )
    paid_today = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(Order.amount_fen), 0)).where(
                    Order.status == "paid",
                    Order.paid_at.is_not(None),
                    Order.paid_at >= today,
                )
            )
        ).scalar_one()
        or 0
    )

    status_rows = (
        await db.execute(select(Project.status, func.count()).group_by(Project.status))
    ).all()
    project_status_counts = {str(status): int(cnt) for status, cnt in status_rows}

    total_u = await _usage_window_totals(db)
    today_u = await _usage_window_totals(db, since=today)
    month_u = await _usage_window_totals(db, since=month)

    by_capability = await _group_usage(
        db, group_col=_derived_capability_expr(), since=range_start, scope_filters=scope
    )
    by_domain = await _group_usage(
        db, group_col=UsageEvent.domain, since=range_start, scope_filters=scope
    )

    # 按日趋势（筛选窗口内补零）
    day_expr = await _usage_day_expr(db)
    daily_stmt = (
        select(
            day_expr.label("day"),
            func.count(UsageEvent.id).label("calls"),
            func.coalesce(func.sum(UsageEvent.charge_fen), 0).label("charge_fen"),
            func.coalesce(func.sum(UsageEvent.cost_fen), 0).label("cost_fen"),
        )
        .where(UsageEvent.created_at >= range_start)
        .group_by(day_expr)
        .order_by(day_expr.asc())
    )
    for clause in scope:
        daily_stmt = daily_stmt.where(clause)
    daily_rows = (await db.execute(daily_stmt)).all()
    daily_map: dict[str, dict[str, int]] = {}
    for r in daily_rows:
        daily_map[_day_key(r.day)] = {
            "calls": int(r.calls or 0),
            "charge_fen": int(r.charge_fen or 0),
            "cost_fen": int(r.cost_fen or 0),
        }
    daily_usage: list[dict[str, Any]] = []
    for i in range(window_days):
        key = (range_start + timedelta(days=i)).date().isoformat()
        hit = daily_map.get(key) or {"calls": 0, "charge_fen": 0, "cost_fen": 0}
        daily_usage.append(
            {
                "date": key,
                "calls": hit["calls"],
                "charge_fen": hit["charge_fen"],
                "cost_fen": hit["cost_fen"],
            }
        )

    # 筛选窗口内用户 Top10（按指标排序）
    owner = aliased(User)
    metric_key = (top_metric or "charge").strip().lower()
    order_col = func.coalesce(func.sum(UsageEvent.charge_fen), 0)
    if metric_key == "cost":
        order_col = func.coalesce(func.sum(UsageEvent.cost_fen), 0)
    elif metric_key == "calls":
        order_col = func.count(UsageEvent.id)
    top_stmt = (
        select(
            UsageEvent.user_id,
            owner.email,
            func.count(UsageEvent.id).label("calls"),
            func.coalesce(func.sum(UsageEvent.charge_fen), 0).label("charge_fen"),
            func.coalesce(func.sum(UsageEvent.cost_fen), 0).label("cost_fen"),
        )
        .outerjoin(owner, owner.id == UsageEvent.user_id)
        .where(UsageEvent.created_at >= range_start)
        .group_by(UsageEvent.user_id, owner.email)
        .order_by(order_col.desc())
        .limit(10)
    )
    for clause in scope:
        top_stmt = top_stmt.where(clause)
    top_rows = (await db.execute(top_stmt)).all()
    top_users_by_charge = [
        {
            "user_id": int(r.user_id),
            "email": r.email,
            "calls": int(r.calls or 0),
            "charge_fen": int(r.charge_fen or 0),
            "cost_fen": int(r.cost_fen or 0),
        }
        for r in top_rows
    ]

    return {
        "user_count": user_count,
        "order_paid_total_fen": paid_total,
        "order_paid_today_fen": paid_today,
        "project_status_counts": project_status_counts,
        "drama_project_count": drama_project_count,
        "usage_calls_today": today_u["calls"],
        "usage_calls_month": month_u["calls"],
        "usage_calls_total": total_u["calls"],
        "usage_charge_today_fen": today_u["charge_fen"],
        "usage_charge_month_fen": month_u["charge_fen"],
        "usage_charge_total_fen": total_u["charge_fen"],
        "usage_cost_today_fen": today_u["cost_fen"],
        "usage_cost_month_fen": month_u["cost_fen"],
        "usage_cost_total_fen": total_u["cost_fen"],
        "usage_by_capability": by_capability,
        "usage_by_domain": by_domain,
        "daily_usage": daily_usage,
        "top_users_by_charge": top_users_by_charge,
    }


def _usage_billing_cases():
    """按 billing_key 拆分图/视/LLM/TTS 调用次数。"""
    return (
        case((UsageEvent.billing_key == "seedream", 1), else_=0),
        case((UsageEvent.billing_key.like("seedance%"), 1), else_=0),
        case((UsageEvent.billing_key == "llm_chat", 1), else_=0),
        case((UsageEvent.billing_key == "tts", 1), else_=0),
    )


def _empty_usage_summary() -> dict[str, int]:
    return {
        "charge_fen": 0,
        "cost_fen": 0,
        "tokens": 0,
        "calls": 0,
        "image_gens": 0,
        "video_gens": 0,
        "llm_calls": 0,
        "tts_gens": 0,
    }


def _row_to_usage_summary(row: Any) -> dict[str, int]:
    return {
        "charge_fen": int(row[0] or 0),
        "cost_fen": int(row[1] or 0),
        "tokens": int(row[2] or 0),
        "calls": int(row[3] or 0),
        "image_gens": int(row[4] or 0),
        "video_gens": int(row[5] or 0),
        "llm_calls": int(row[6] or 0),
        "tts_gens": int(row[7] or 0),
    }


def _single_shot_billing_key_filter():
    """单次调用类 billing_key：seedance* / seedream。"""
    clauses = [UsageEvent.billing_key.like(f"{p}%") for p in _SINGLE_SHOT_BILLING_KEY_PREFIXES]
    if _SINGLE_SHOT_BILLING_KEYS:
        clauses.append(UsageEvent.billing_key.in_(tuple(_SINGLE_SHOT_BILLING_KEYS)))
    return or_(*clauses)


def _deduped_usage_event_ids_subq():
    """
    仅对单次调用类 key 按 task_run+billing_key 保留最早一行，避免并发双记抬高汇总。
    llm_chat / tts 等同 key 多行全部保留；无 task_run_id 的孤儿行全部保留。
    """
    single_shot = _single_shot_billing_key_filter()
    ranked = (
        select(
            UsageEvent.id.label("id"),
            func.row_number()
            .over(
                partition_by=(UsageEvent.task_run_id, UsageEvent.billing_key),
                order_by=UsageEvent.id.asc(),
            )
            .label("rn"),
        )
        .where(UsageEvent.task_run_id.is_not(None), single_shot)
        .subquery()
    )
    deduped_single = select(ranked.c.id).where(ranked.c.rn == 1)
    keep_multi = select(UsageEvent.id).where(
        UsageEvent.task_run_id.is_not(None),
        ~single_shot,
    )
    orphans = select(UsageEvent.id).where(UsageEvent.task_run_id.is_(None))
    return union_all(deduped_single, keep_multi, orphans).subquery()


async def _sum_task_charged_fen(
    db: AsyncSession,
    *,
    project_ids: list[int] | None = None,
    drama_project_ids: list[int] | None = None,
) -> dict[int, int]:
    """按任务实扣汇总（钱包结算口径）。"""
    from app.models_tasks import TaskRun

    if project_ids is not None:
        if not project_ids:
            return {}
        rows = (
            await db.execute(
                select(
                    TaskRun.project_id,
                    func.coalesce(func.sum(TaskRun.billing_charged_fen), 0),
                )
                .where(TaskRun.project_id.in_(project_ids))
                .group_by(TaskRun.project_id)
            )
        ).all()
        return {int(r[0]): int(r[1] or 0) for r in rows if r[0] is not None}

    if drama_project_ids is not None:
        if not drama_project_ids:
            return {}
        rows = (
            await db.execute(
                select(
                    TaskRun.drama_project_id,
                    func.coalesce(func.sum(TaskRun.billing_charged_fen), 0),
                )
                .where(TaskRun.drama_project_id.in_(drama_project_ids))
                .group_by(TaskRun.drama_project_id)
            )
        ).all()
        return {int(r[0]): int(r[1] or 0) for r in rows if r[0] is not None}
    return {}


async def _sum_orphan_usage_charge_fen(
    db: AsyncSession,
    *,
    scope_col,
    scope_ids: list[int],
) -> dict[int, int]:
    """无 task_run_id 的用量扣费（未走 TaskRun 结算的历史/旁路行）。"""
    if not scope_ids:
        return {}
    rows = (
        await db.execute(
            select(
                scope_col,
                func.coalesce(func.sum(UsageEvent.charge_fen), 0),
            )
            .where(scope_col.in_(scope_ids), UsageEvent.task_run_id.is_(None))
            .group_by(scope_col)
        )
    ).all()
    return {int(r[0]): int(r[1] or 0) for r in rows if r[0] is not None}


async def _aggregate_usage_by_scope(
    db: AsyncSession,
    *,
    scope_col,
    scope_ids: list[int],
    project_ids: list[int] | None = None,
    drama_project_ids: list[int] | None = None,
) -> dict[int, dict[str, Any]]:
    """按项目/漫剧项目聚合去重后的用量行；扣费用任务实扣+孤儿用量。"""
    image_case, video_case, llm_case, tts_case = _usage_billing_cases()
    empty = _empty_usage_summary()
    if not scope_ids:
        return {}
    deduped = _deduped_usage_event_ids_subq()
    result = await db.execute(
        select(
            scope_col,
            func.coalesce(func.sum(UsageEvent.charge_fen), 0),
            func.coalesce(func.sum(UsageEvent.cost_fen), 0),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
            func.count(UsageEvent.id),
            func.coalesce(func.sum(image_case), 0),
            func.coalesce(func.sum(video_case), 0),
            func.coalesce(func.sum(llm_case), 0),
            func.coalesce(func.sum(tts_case), 0),
        )
        .where(scope_col.in_(scope_ids), UsageEvent.id.in_(select(deduped.c.id)))
        .group_by(scope_col)
    )
    out: dict[int, dict[str, Any]] = {pid: dict(empty) for pid in scope_ids}
    for row in result.all():
        out[int(row[0])] = _row_to_usage_summary(row[1:])

    charged_map = await _sum_task_charged_fen(
        db, project_ids=project_ids, drama_project_ids=drama_project_ids
    )
    orphan_map = await _sum_orphan_usage_charge_fen(db, scope_col=scope_col, scope_ids=scope_ids)
    for pid in scope_ids:
        if pid in charged_map or pid in orphan_map:
            out[pid]["charge_fen"] = int(charged_map.get(pid, 0)) + int(orphan_map.get(pid, 0))
    return out


async def aggregate_usage_summary(
    db: AsyncSession,
    *,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    project_ids: list[int] | None = None,
    drama_project_ids: list[int] | None = None,
) -> dict[str, Any] | dict[int, dict[str, Any]]:
    """
    项目级用量汇总。
    - 单项目：传 project_id 或 drama_project_id，返回一条 dict
    - 批量：传 project_ids 或 drama_project_ids，返回 {id: dict}
    扣费 = TaskRun 实扣 + 无任务孤儿用量；调用/成本按去重后的 usage 行统计。
    """
    empty = _empty_usage_summary()

    if project_ids is not None:
        return await _aggregate_usage_by_scope(
            db,
            scope_col=UsageEvent.project_id,
            scope_ids=project_ids,
            project_ids=project_ids,
        )

    if drama_project_ids is not None:
        return await _aggregate_usage_by_scope(
            db,
            scope_col=UsageEvent.drama_project_id,
            scope_ids=drama_project_ids,
            drama_project_ids=drama_project_ids,
        )

    if project_id is not None:
        batch = await aggregate_usage_summary(db, project_ids=[project_id])
        return batch.get(project_id, dict(empty))
    if drama_project_id is not None:
        batch = await aggregate_usage_summary(db, drama_project_ids=[drama_project_id])
        return batch.get(drama_project_id, dict(empty))
    return dict(empty)
