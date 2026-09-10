"""漫剧项目用量聚合：按 usage_events.drama_project_id 汇总费用与生图/生视频次数。"""

from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent
from app.schemas_drama import DramaProjectUsageStats


def empty_usage_stats() -> DramaProjectUsageStats:
    """返回全零用量统计。"""
    return DramaProjectUsageStats()


async def aggregate_drama_usage_by_project_ids(
    db: AsyncSession,
    *,
    user_id: int,
    project_ids: list[int],
) -> dict[int, DramaProjectUsageStats]:
    """
    批量聚合漫剧项目用量。
    生图：billing_key == seedream；生视频：billing_key 以 seedance 开头。
    """
    if not project_ids:
        return {}

    image_case = case((UsageEvent.billing_key == "seedream", 1), else_=0)
    video_case = case((UsageEvent.billing_key.like("seedance%"), 1), else_=0)

    result = await db.execute(
        select(
            UsageEvent.drama_project_id,
            func.coalesce(func.sum(UsageEvent.charge_fen), 0),
            func.coalesce(func.sum(UsageEvent.cost_fen), 0),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
            func.count(UsageEvent.id),
            func.coalesce(func.sum(image_case), 0),
            func.coalesce(func.sum(video_case), 0),
        )
        .where(
            UsageEvent.user_id == user_id,
            UsageEvent.drama_project_id.in_(project_ids),
        )
        .group_by(UsageEvent.drama_project_id)
    )

    out: dict[int, DramaProjectUsageStats] = {}
    for row in result.all():
        pid = int(row[0])
        charge_fen = int(row[1] or 0)
        cost_fen = int(row[2] or 0)
        out[pid] = DramaProjectUsageStats(
            charge_fen=charge_fen,
            charge_yuan=round(charge_fen / 100.0, 2),
            cost_fen=cost_fen,
            cost_yuan=round(cost_fen / 100.0, 2),
            tokens=int(row[3] or 0),
            calls=int(row[4] or 0),
            image_gens=int(row[5] or 0),
            video_gens=int(row[6] or 0),
        )
    return out


async def get_drama_project_usage(
    db: AsyncSession,
    *,
    user_id: int,
    project_id: int,
) -> DramaProjectUsageStats:
    """单部漫剧用量汇总。"""
    mapped = await aggregate_drama_usage_by_project_ids(
        db, user_id=user_id, project_ids=[project_id]
    )
    return mapped.get(project_id) or empty_usage_stats()
