"""真实互动与运营初始值分别记账，所有公开读取在此统一合计。"""
from datetime import datetime, timedelta, timezone
import secrets

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .app_access import current_content, error, series_query, work_query
from .app_engagement_models import (EngagementMaintenance, MetricsAudit, MetricsBaseline,
                                    MetricsInitializationJob, ShareEvent)
from .app_social_models import AppComment, AppContentStats, AppFavorite, AppLike
from .locale import localized
from .models import Series, SeriesEpisode, Work

COUNT_KEYS = ("like_count", "favorite_count", "share_count")


def stored_type(kind: str) -> str:
    return "episode" if kind in ("episode", "episodes", "series_episode") else "work" if kind == "works" else kind


def public_type(kind: str) -> str:
    return "series_episode" if stored_type(kind) == "episode" else stored_type(kind)


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


async def insert_once(db, model, values: dict, columns: list[str]) -> bool:
    """在唯一约束上原子去重，不用捕获错误回滚调用方的业务事务。"""
    statement = (sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert)(model).values(**values)
    result = await db.execute(statement.on_conflict_do_nothing(index_elements=columns))
    return result.rowcount == 1


async def lock_stats(db, kind: str, target_id: int):
    kind = stored_type(kind)
    await insert_once(db, AppContentStats, {"target_type": kind, "target_id": target_id,
        "like_count": 0, "favorite_count": 0, "comment_count": 0, "share_count": 0}, ["target_type", "target_id"])
    return await db.scalar(select(AppContentStats).where(AppContentStats.target_type == kind,
        AppContentStats.target_id == target_id).with_for_update().execution_options(populate_existing=True))


def generated_baseline() -> dict:
    """收藏最低2000且严格小于点赞，因此最小合法点赞数为2001。"""
    likes = secrets.randbelow(12000 - 2001 + 1) + 2001
    favorites = secrets.randbelow(min(5000, likes - 1) - 2000 + 1) + 2000
    shares = secrets.randbelow(min(3000, favorites - 1) - 500 + 1) + 500
    return dict(zip(COUNT_KEYS, (likes, favorites, shares)))


def counts(row) -> dict:
    return {key: int(getattr(row, key, 0) or 0) for key in COUNT_KEYS}


async def baseline_for(db, kind, target_id):
    return await db.scalar(select(MetricsBaseline).where(MetricsBaseline.target_type == stored_type(kind),
        MetricsBaseline.target_id == target_id))


async def totals(db, kind, target_id, real=None) -> dict:
    if real is None:
        real = await db.scalar(select(AppContentStats).where(AppContentStats.target_type == stored_type(kind),
            AppContentStats.target_id == target_id))
    baseline = await baseline_for(db, kind, target_id)
    return {key: counts(real)[key] + counts(baseline)[key] for key in COUNT_KEYS}


async def initialize_target(db, kind, target_id, *, operator_id=None, reason="首次上架自动初始化", automatic=False) -> bool:
    """调用方负责提交；目标校验与首次插入在同一事务，清零记录也永不重新抽取。"""
    kind = stored_type(kind)
    if kind not in ("work", "episode"):
        return False
    if automatic:
        from .app_access import app_open
        from .app_settings import get_app_settings
        if not app_open() or not getattr(get_app_settings(), "social_initialization_enabled", False):
            return False
    if await baseline_for(db, kind, target_id):
        return False
    try:
        await current_content(db, public_type(kind), target_id)
    except HTTPException as exc:
        if automatic and exc.status_code == 404:
            # Web also supports copyright-only works, which are intentionally
            # excluded from App discovery. Initialization must not block them.
            return False
        raise
    await lock_stats(db, kind, target_id)
    values = generated_baseline()
    created = await insert_once(db, MetricsBaseline, {"target_type": kind, "target_id": target_id,
        **values, "version": 1, "initialized_by": "automatic" if automatic else "operator"}, ["target_type", "target_id"])
    if created:
        db.add(MetricsAudit(target_type=kind, target_id=target_id, operator_id=operator_id,
            action="initialize", reason=reason, before={key: 0 for key in COUNT_KEYS}, after=values))
    return created


async def eligible_targets(db, kind=None) -> list[dict]:
    """只快照可见目标编号，Worker 每项执行前仍重新核验当前权属与审核状态。"""
    kind = stored_type(kind) if kind else None
    result = []
    if kind in (None, "work"):
        rows = list((await db.scalars(work_query().order_by(Work.id))).all())
        result.extend({"target_type": "work", "target_id": row.id} for row in rows)
    if kind in (None, "episode"):
        parents = list((await db.scalars(series_query().order_by(Series.id))).all())
        for parent in parents:
            rows = list((await db.scalars(select(SeriesEpisode).where(SeriesEpisode.series_id == parent.id).order_by(SeriesEpisode.id))).all())
            for row in rows:
                try:
                    await current_content(db, "series_episode", row.id)
                except HTTPException:
                    continue
                result.append({"target_type": "series_episode", "target_id": row.id})
    return result


async def metrics_record(db, kind, target_id, item=None):
    kind = stored_type(kind)
    if item is None:
        item = await db.get(Work if kind == "work" else Series if kind == "series" else SeriesEpisode, target_id)
    real = await db.scalar(select(AppContentStats).where(AppContentStats.target_type == kind, AppContentStats.target_id == target_id))
    baseline = await baseline_for(db, kind, target_id)
    return {"target_type": public_type(kind), "target_id": target_id, "title": item.title if item else "",
        "version": baseline.version if baseline else 0, "real": counts(real), "initial": counts(baseline),
        "display": {key: counts(real)[key] + counts(baseline)[key] for key in COUNT_KEYS},
        "updated_at": baseline.updated_at if baseline else None}


async def adjust_metrics(db, kind, target_id, *, version, reason, desired, clear, operator_id):
    kind = stored_type(kind)
    if kind not in ("work", "episode"):
        error("MARKETPLACE_METRICS_TARGET_INVALID", localized("系列整体仅展示真实互动数量，不能设置初始值。", "Series display real interactions only; initial counts cannot be set."), 422)
    model = Work if kind == "work" else Series if kind == "series" else SeriesEpisode
    if not await db.get(model, target_id):
        error("MARKETPLACE_CONTENT_UNAVAILABLE", localized("作品不存在。", "The content does not exist."), 404)
    real = await lock_stats(db, kind, target_id)
    baseline = await db.scalar(select(MetricsBaseline).where(MetricsBaseline.target_type == kind,
        MetricsBaseline.target_id == target_id).with_for_update().execution_options(populate_existing=True))
    if version != (baseline.version if baseline else 0):
        error("MARKETPLACE_TARGET_CHANGED", localized("互动数据已被修改，请刷新后重试。", "The metrics have changed. Refresh and try again."), 409)
    if not clear and any(desired[key] < counts(real)[key] for key in COUNT_KEYS):
        error("MARKETPLACE_METRICS_BELOW_REAL", localized("展示数量不能小于真实互动数量。", "Display counts cannot be lower than real interactions."), 422)
    previous = counts(baseline)
    values = {key: 0 if clear else desired[key] - counts(real)[key] for key in COUNT_KEYS}
    if baseline is None:
        baseline = MetricsBaseline(target_type=kind, target_id=target_id, version=1, initialized_by="operator", **values)
        db.add(baseline)
    else:
        for key, value in values.items():
            setattr(baseline, key, value)
        baseline.version += 1
        baseline.updated_at = utcnow()
    db.add(MetricsAudit(target_type=kind, target_id=target_id, operator_id=operator_id,
        action="clear" if clear else "adjust", reason=reason, before=previous, after=values))
    await db.flush()
    return await metrics_record(db, kind, target_id)


def job_record(job):
    return {name: getattr(job, name) for name in ("id", "status", "total", "processed", "initialized", "skipped", "failed", "errors")}


async def run_initialization_batch(db, batch_size=20):
    current = utcnow()
    job = await db.scalar(select(MetricsInitializationJob).where(
        MetricsInitializationJob.status.in_(("pending", "running")),
        or_(MetricsInitializationJob.lease_until.is_(None), MetricsInitializationJob.lease_until < current)
    ).order_by(MetricsInitializationJob.id).with_for_update(skip_locked=True).limit(1))
    if not job:
        return False
    job.status, job.lease_token, job.lease_until = "running", secrets.token_hex(24), current + timedelta(seconds=60)
    # 同事务锁住任务与每项目统计。崩溃整批回滚，重启后不会跳过半完成项。
    for target in job.targets[job.processed:job.processed + batch_size]:
        try:
            async with db.begin_nested():
                created = await initialize_target(db, target["target_type"], target["target_id"],
                    operator_id=job.operator_id, reason=job.reason)
            if created:
                job.initialized += 1
            else:
                job.skipped += 1
        except Exception as exc:
            job.failed += 1
            message = exc.detail.get("message", "内容状态已变化") if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else "初始化失败，可重试"
            job.errors = [*job.errors, {**target, "message": message}]
        job.processed += 1
    if job.processed >= job.total:
        job.status = "completed_with_errors" if job.failed else "done"
    job.lease_token = job.lease_until = None
    await db.commit()
    return True


async def reconcile_batch(db, limit=30):
    """周期性按事实重建真实统计，绝不读取或重写运营初始值。"""
    await insert_once(db, EngagementMaintenance, {"key": "reconcile", "cursor": 0,
        "updated_at": utcnow() - timedelta(minutes=1)}, ["key"])
    state = await db.scalar(select(EngagementMaintenance).where(EngagementMaintenance.key == "reconcile").with_for_update(skip_locked=True))
    if not state:
        return
    if aware(state.updated_at) > utcnow() - timedelta(seconds=60):
        return
    # Initialization jobs can already hold several target locks in another order.
    # Skip busy targets; the persisted cursor wraps to zero and revisits them.
    rows = list((await db.scalars(select(AppContentStats).where(AppContentStats.id > state.cursor).order_by(AppContentStats.id).limit(limit).with_for_update(skip_locked=True))).all())
    for row in rows:
        for model, attribute, extra in ((AppLike, "like_count", ()), (AppFavorite, "favorite_count", ()),
                                        (AppComment, "comment_count", (AppComment.status == "visible",)), (ShareEvent, "share_count", ())):
            value = await db.scalar(select(func.count()).select_from(model).where(model.target_type == row.target_type,
                model.target_id == row.target_id, *extra))
            setattr(row, attribute, int(value or 0))
    state.cursor = rows[-1].id if len(rows) == limit else 0
    state.updated_at = utcnow()
    await db.commit()


async def run_engagement_maintenance_once():
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await run_initialization_batch(db)
        await reconcile_batch(db)
