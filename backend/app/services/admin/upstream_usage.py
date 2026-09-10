"""管理端：官方上游用量快照与本地成本对照。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import UpstreamUsageDaily, UsageEvent
from app.services.ark_control_usage import get_inference_usage, volc_usage_configured
from app.services.billing.pricing import charge_fen_for_tokens


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _tokens_to_official_cost_fen(tokens: int, settings: Settings | None = None) -> int:
    """按 seedance video0 单价估算官方 token 成本（对照图仅供参考）。"""
    s = settings or get_settings()
    cost, _charge = charge_fen_for_tokens(int(tokens), "seedance2:video0", settings=s)
    return int(cost or 0)


async def _local_seedance_daily(
    db: AsyncSession,
    *,
    since: date,
    until: date,
) -> dict[str, dict[str, int]]:
    day_expr = cast(UsageEvent.created_at, Date)
    rows = (
        await db.execute(
            select(
                day_expr.label("day"),
                func.coalesce(func.sum(UsageEvent.cost_fen), 0).label("cost_fen"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens"),
            )
            .where(
                UsageEvent.billing_key.like("seedance%"),
                day_expr >= since,
                day_expr <= until,
            )
            .group_by(day_expr)
            .order_by(day_expr.asc())
        )
    ).all()
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        key = str(row.day)[:10]
        out[key] = {
            "local_cost_fen": int(row.cost_fen or 0),
            "local_tokens": int(row.tokens or 0),
        }
    return out


async def sync_upstream_usage(
    db: AsyncSession,
    *,
    days: int = 30,
    force: bool = False,
) -> dict[str, Any]:
    """拉取官方日用量并写入 upstream_usage_daily。"""
    if not volc_usage_configured():
        return {"configured": False, "synced": 0, "skipped": 0}

    s = get_settings()
    today = _utc_today()
    start = today - timedelta(days=max(1, int(days)) - 1)
    local_map = await _local_seedance_daily(db, since=start, until=today)

    synced = 0
    skipped = 0
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)

    # 按 7 日窗口批量请求，减少管控面调用次数
    window_start = start
    official_daily: dict[str, int] = {}
    while window_start <= today:
        window_end = min(window_start + timedelta(days=6), today)
        payload = await get_inference_usage(
            window_start.isoformat(),
            window_end.isoformat(),
            settings=s,
        )
        for day_key, tokens in (payload.get("daily_tokens") or {}).items():
            official_daily[str(day_key)[:10]] = int(tokens or 0)
        window_start = window_end + timedelta(days=1)

    cur = start
    while cur <= today:
        day_key = cur.isoformat()
        existing = (
            await db.execute(select(UpstreamUsageDaily).where(UpstreamUsageDaily.usage_date == cur))
        ).scalar_one_or_none()
        if (
            existing
            and not force
            and existing.fetched_at
            and existing.fetched_at.replace(tzinfo=UTC) >= one_hour_ago
        ):
            skipped += 1
            cur += timedelta(days=1)
            continue

        tokens = int(official_daily.get(day_key, 0))
        local_hit = local_map.get(day_key) or {"local_cost_fen": 0, "local_tokens": 0}
        row = existing or UpstreamUsageDaily(usage_date=cur)
        row.official_tokens = tokens
        row.official_cost_fen = _tokens_to_official_cost_fen(tokens, s)
        row.local_cost_fen = int(local_hit["local_cost_fen"])
        row.local_tokens = int(local_hit["local_tokens"])
        row.raw_json = json.dumps({"day": day_key, "official_tokens": tokens}, ensure_ascii=False)[:4000]
        row.fetched_at = now
        if existing is None:
            db.add(row)
        synced += 1
        cur += timedelta(days=1)

    await db.commit()
    return {"configured": True, "synced": synced, "skipped": skipped, "last_sync_at": now.isoformat()}


async def build_upstream_usage_compare(
    db: AsyncSession,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """返回近 N 日官方/本地成本对照序列。"""
    today = _utc_today()
    start = today - timedelta(days=max(1, int(days)) - 1)
    rows = (
        await db.execute(
            select(UpstreamUsageDaily)
            .where(UpstreamUsageDaily.usage_date >= start)
            .order_by(UpstreamUsageDaily.usage_date.asc())
        )
    ).scalars().all()
    row_map = {r.usage_date.isoformat(): r for r in rows}
    local_map = await _local_seedance_daily(db, since=start, until=today)

    series: list[dict[str, Any]] = []
    cur = start
    last_sync_at: str | None = None
    while cur <= today:
        key = cur.isoformat()
        snap = row_map.get(key)
        local_hit = local_map.get(key) or {"local_cost_fen": 0, "local_tokens": 0}
        official_tokens = int(snap.official_tokens if snap else 0)
        official_cost = int(snap.official_cost_fen if snap else 0)
        local_cost = int(snap.local_cost_fen if snap else local_hit["local_cost_fen"])
        local_tokens = int(snap.local_tokens if snap else local_hit["local_tokens"])
        delta_fen = local_cost - official_cost
        delta_pct: float | None = None
        if official_cost > 0:
            delta_pct = round(delta_fen / official_cost * 100.0, 2)
        elif local_cost > 0:
            delta_pct = None
        series.append(
            {
                "date": key,
                "local_cost_fen": local_cost,
                "local_tokens": local_tokens,
                "official_tokens": official_tokens,
                "official_cost_fen": official_cost,
                "delta_fen": delta_fen,
                "delta_pct": delta_pct,
            }
        )
        if snap and snap.fetched_at:
            last_sync_at = snap.fetched_at.isoformat()
        cur += timedelta(days=1)

    return {
        "configured": volc_usage_configured(),
        "days": int(days),
        "last_sync_at": last_sync_at,
        "series": series,
    }
