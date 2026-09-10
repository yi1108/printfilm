"""管理端：按日财务对照（本地扣费/成本 vs 官方实际成本）。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UpstreamUsageDaily, UsageEvent
from app.services.ark_control_usage import volc_usage_configured


def _utc_today() -> date:
    return datetime.now(UTC).date()


async def _local_usage_daily(
    db: AsyncSession,
    *,
    since: date,
    until: date,
) -> dict[str, dict[str, int]]:
    """按日聚合全部 usage_events 的扣费、成本与 token。"""
    day_expr = cast(UsageEvent.created_at, Date)
    rows = (
        await db.execute(
            select(
                day_expr.label("day"),
                func.coalesce(func.sum(UsageEvent.charge_fen), 0).label("charge_fen"),
                func.coalesce(func.sum(UsageEvent.cost_fen), 0).label("cost_fen"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens"),
            )
            .where(day_expr >= since, day_expr <= until)
            .group_by(day_expr)
            .order_by(day_expr.asc())
        )
    ).all()
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        key = str(row.day)[:10]
        out[key] = {
            "charge_fen": int(row.charge_fen or 0),
            "cost_fen": int(row.cost_fen or 0),
            "tokens": int(row.tokens or 0),
        }
    return out


def _profit_fen(*, charge_fen: int, cost_fen: int, actual_cost_fen: int) -> int:
    """利润 = 本地扣费 - 实际成本；无官方数据时回退本地成本。"""
    basis = actual_cost_fen if actual_cost_fen > 0 else cost_fen
    return int(charge_fen - basis)


async def build_finance_daily_list(
    db: AsyncSession,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """返回近 N 日财务对照序列与汇总。"""
    window_days = max(1, min(90, int(days)))
    today = _utc_today()
    start = today - timedelta(days=window_days - 1)

    local_map = await _local_usage_daily(db, since=start, until=today)
    upstream_rows = (
        await db.execute(
            select(UpstreamUsageDaily)
            .where(UpstreamUsageDaily.usage_date >= start)
            .order_by(UpstreamUsageDaily.usage_date.asc())
        )
    ).scalars().all()
    upstream_map = {r.usage_date.isoformat(): r for r in upstream_rows}

    series: list[dict[str, Any]] = []
    totals = {
        "charge_fen": 0,
        "cost_fen": 0,
        "tokens": 0,
        "actual_cost_fen": 0,
        "profit_fen": 0,
    }
    last_sync_at: str | None = None

    cur = start
    while cur <= today:
        key = cur.isoformat()
        local_hit = local_map.get(key) or {"charge_fen": 0, "cost_fen": 0, "tokens": 0}
        snap = upstream_map.get(key)
        actual_cost_fen = int(snap.official_cost_fen if snap else 0)
        charge_fen = int(local_hit["charge_fen"])
        cost_fen = int(local_hit["cost_fen"])
        tokens = int(local_hit["tokens"])
        profit_fen = _profit_fen(
            charge_fen=charge_fen,
            cost_fen=cost_fen,
            actual_cost_fen=actual_cost_fen,
        )
        profit_pct: float | None = None
        if charge_fen > 0:
            profit_pct = round(profit_fen / charge_fen * 100.0, 2)

        series.append(
            {
                "date": key,
                "charge_fen": charge_fen,
                "cost_fen": cost_fen,
                "tokens": tokens,
                "actual_cost_fen": actual_cost_fen,
                "profit_fen": profit_fen,
                "profit_pct": profit_pct,
            }
        )
        totals["charge_fen"] += charge_fen
        totals["cost_fen"] += cost_fen
        totals["tokens"] += tokens
        totals["actual_cost_fen"] += actual_cost_fen
        totals["profit_fen"] += profit_fen
        if snap and snap.fetched_at:
            last_sync_at = snap.fetched_at.isoformat()
        cur += timedelta(days=1)

    if totals["charge_fen"] > 0:
        totals["profit_pct"] = round(totals["profit_fen"] / totals["charge_fen"] * 100.0, 2)

    return {
        "configured": volc_usage_configured(),
        "days": window_days,
        "last_sync_at": last_sync_at,
        "totals": totals,
        "series": series,
    }
