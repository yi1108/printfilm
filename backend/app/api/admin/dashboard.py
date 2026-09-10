# Dashboard stats for admin console
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_admin
from app.models import User
from app.schemas import (
    AdminDailyUsageOut,
    AdminStatsOut,
    AdminTopUserOut,
    AdminUpstreamUsageOut,
    AdminUpstreamUsageSyncOut,
    AdminUsageBucketOut,
)
from app.services.admin.stats import build_admin_dashboard_stats
from app.services.admin.upstream_usage import build_upstream_usage_compare, sync_upstream_usage

router = APIRouter()

_ALLOWED_STATS_DAYS = frozenset({1, 7, 14, 30})
_ALLOWED_TOP_METRICS = frozenset({"charge", "cost", "calls"})


def _validate_stats_days(raw: int) -> int:
    """仅允许固定档位，非法值返回 422。"""
    if raw not in _ALLOWED_STATS_DAYS:
        allowed = ", ".join(str(v) for v in sorted(_ALLOWED_STATS_DAYS))
        raise HTTPException(status_code=422, detail=f"days must be one of: {allowed}")
    return raw


def _normalize_top_metric(raw: str) -> str:
    metric = (raw or "charge").strip().lower()
    if metric not in _ALLOWED_TOP_METRICS:
        allowed = ", ".join(sorted(_ALLOWED_TOP_METRICS))
        raise HTTPException(status_code=422, detail=f"top_metric must be one of: {allowed}")
    return metric


@router.get("/stats", response_model=AdminStatsOut)
async def admin_stats(
    days: int = Query(default=7, description="趋势与分布时间窗口（天），仅支持 1/7/14/30"),
    domain: str = Query(default="all", max_length=32, description="领域筛选，all 为全部"),
    capability: str = Query(default="all", max_length=32, description="能力筛选，all 为全部"),
    top_metric: str = Query(default="charge", description="用户排行排序指标：charge/cost/calls"),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminStatsOut:
    """用户/充值 + AI 调用量/费用/趋势/排行。"""
    window_days = _validate_stats_days(days)
    metric = _normalize_top_metric(top_metric)
    raw = await build_admin_dashboard_stats(
        db,
        days=window_days,
        domain=domain.strip() or "all",
        capability=capability.strip() or "all",
        top_metric=metric,
    )
    return AdminStatsOut(
        user_count=raw["user_count"],
        order_paid_total_fen=raw["order_paid_total_fen"],
        order_paid_today_fen=raw["order_paid_today_fen"],
        project_status_counts=raw["project_status_counts"],
        drama_project_count=raw["drama_project_count"],
        usage_calls_today=raw["usage_calls_today"],
        usage_calls_month=raw["usage_calls_month"],
        usage_calls_total=raw["usage_calls_total"],
        usage_charge_today_fen=raw["usage_charge_today_fen"],
        usage_charge_month_fen=raw["usage_charge_month_fen"],
        usage_charge_total_fen=raw["usage_charge_total_fen"],
        usage_cost_today_fen=raw["usage_cost_today_fen"],
        usage_cost_month_fen=raw["usage_cost_month_fen"],
        usage_cost_total_fen=raw["usage_cost_total_fen"],
        usage_by_capability=[AdminUsageBucketOut(**x) for x in raw["usage_by_capability"]],
        usage_by_domain=[AdminUsageBucketOut(**x) for x in raw["usage_by_domain"]],
        daily_usage=[AdminDailyUsageOut(**x) for x in raw["daily_usage"]],
        top_users_by_charge=[AdminTopUserOut(**x) for x in raw["top_users_by_charge"]],
    )


@router.get("/stats/upstream-usage", response_model=AdminUpstreamUsageOut)
async def admin_upstream_usage(
    days: int = Query(30, ge=1, le=90),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUpstreamUsageOut:
    """近 N 日官方用量与本地 seedance 成本对照。"""
    raw = await build_upstream_usage_compare(db, days=days)
    return AdminUpstreamUsageOut(**raw)


@router.post("/stats/upstream-usage/sync", response_model=AdminUpstreamUsageSyncOut)
async def admin_upstream_usage_sync(
    days: int = Query(30, ge=1, le=90),
    force: bool = Query(False),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUpstreamUsageSyncOut:
    """手动刷新官方用量快照。"""
    try:
        raw = await sync_upstream_usage(db, days=days, force=force)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminUpstreamUsageSyncOut(**raw)
