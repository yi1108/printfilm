"""只有平台管理员可查看真实/初始分解或修改对外数量。"""
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Integer, String, and_, cast, false, func, literal, or_, select, union_all

from app.models import User
from .app_access import error
from .app_engagement import (COUNT_KEYS, adjust_metrics, eligible_targets, job_record,
                             metrics_record, public_type, stored_type)
from .app_engagement_models import MetricsAudit, MetricsBaseline, MetricsInitializationJob
from .dependencies import Admin, DB
from .locale import localized
from .models import Series, SeriesEpisode, Work
from .curation import admin_fields, filter_curation

router = APIRouter()
MetricTarget = Literal["work", "series", "series_episode", "episode"]


class MetricsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1, max_length=300)
    like_count: int = Field(default=0, ge=0, le=1_000_000_000, strict=True)
    favorite_count: int = Field(default=0, ge=0, le=1_000_000_000, strict=True)
    share_count: int = Field(default=0, ge=0, le=1_000_000_000, strict=True)
    clear: bool = False

    @model_validator(mode="after")
    def meaningful_reason(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("请填写调整原因 / An adjustment reason is required")
        return self


class InitializationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview: bool = True
    target_type: Literal["work", "series_episode", "episode"] | None = None
    reason: str = Field(default="历史作品初始数量补齐", min_length=1, max_length=300)

    @model_validator(mode="after")
    def meaningful_reason(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("请填写初始化原因 / An initialization reason is required")
        return self


@router.get("/social/metrics", response_model=dict)
async def metrics(db: DB, user: Admin, target_type: MetricTarget | None = None,
                  q: str = Query("", max_length=100), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  curation: str = Query("", pattern="^(|featured|pinned|normal)$")):
    queries = []
    for kind, model in (("work", Work), ("series", Series), ("episode", SeriesEpisode)):
        if target_type and stored_type(target_type) != kind:
            continue
        episode = kind == "episode"
        query = select(model.id.label("target_id"), literal(kind).label("target_type"), model.title.label("title"),
            model.owner_id, func.coalesce(User.nickname, "创作者").label("author"),
            (func.coalesce(model.cover_asset_id, Series.cover_asset_id) if episode else model.cover_asset_id).label("cover_asset_id"),
            (Series.category if episode else model.category).label("category"),
            (model.asset_id if kind != "series" else cast(literal(None), Integer)).label("asset_id"),
            (model.series_id if episode else cast(literal(None), Integer)).label("series_id"),
            (Series.title if episode else cast(literal(None), String)).label("series_title"),
            (model.episode_no if episode else cast(literal(None), Integer)).label("episode_no"),
            model.audit_status, (and_(model.listed, Series.listed) if episode else model.listed).label("listed"),
            (or_(model.blocked, Series.blocked) if episode else model.blocked).label("blocked"),
            model.created_at)
        if episode:
            query = query.join(Series, Series.id == model.series_id).where(Series.deleted_at.is_(None))
        else:
            query = query.where(model.deleted_at.is_(None))
        query = query.outerjoin(User, User.id == model.owner_id)
        if q:
            query = query.where(or_(model.title.ilike(f"%{q}%"), Series.title.ilike(f"%{q}%")) if episode else model.title.ilike(f"%{q}%"))
        if episode:
            if curation in ("featured", "pinned"):
                query = query.where(false())
        else:
            query = filter_curation(query, model, kind, curation)
        queries.append(query)
    combined = union_all(*queries).subquery()
    total = int(await db.scalar(select(func.count()).select_from(combined)) or 0)
    rows = list((await db.execute(select(combined).order_by(combined.c.target_id.desc(), combined.c.target_type)
        .offset((page - 1) * page_size).limit(page_size))).all())
    items = []
    for row in rows:
        item = {**dict(row._mapping), **await metrics_record(db, row.target_type, row.target_id, item=row)}
        item.update(await admin_fields(db, row.target_type, row.target_id) if row.target_type != "episode" else {
            "is_featured": False, "is_pinned": False, "pin_priority": 100, "curation_version": 0})
        items.append(item)
    return {"items": items,
            "total": total, "page": page, "page_size": page_size}


@router.patch("/social/metrics/{target_type}/{target_id}", response_model=dict)
async def update_metrics(target_type: MetricTarget, target_id: int, body: MetricsInput, db: DB, user: Admin):
    result = await adjust_metrics(db, target_type, target_id, version=body.version, reason=body.reason,
        desired={key: getattr(body, key) for key in COUNT_KEYS}, clear=body.clear, operator_id=user.id)
    await db.commit()
    return result


@router.get("/social/metrics/events", response_model=dict)
async def metric_events(db: DB, user: Admin, target_type: MetricTarget | None = None, target_id: int | None = None,
                        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    query = select(MetricsAudit)
    if target_type:
        query = query.where(MetricsAudit.target_type == stored_type(target_type))
    if target_id:
        query = query.where(MetricsAudit.target_id == target_id)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = list((await db.scalars(query.order_by(MetricsAudit.id.desc()).offset((page - 1) * page_size).limit(page_size))).all())
    return {"items": [{"id": row.id, "target_type": public_type(row.target_type), "target_id": row.target_id,
        "operator_id": row.operator_id, "action": row.action, "reason": row.reason,
        "before": row.before, "after": row.after, "created_at": row.created_at} for row in rows], "total": total}


@router.post("/social/initialization-jobs", response_model=dict)
async def initialize_metrics(body: InitializationInput, db: DB, user: Admin):
    targets = await eligible_targets(db, body.target_type)
    existing = set((await db.execute(select(MetricsBaseline.target_type, MetricsBaseline.target_id))).all())
    pending = [item for item in targets if (stored_type(item["target_type"]), item["target_id"]) not in existing]
    if body.preview:
        return {"preview": True, "total": len(pending), "eligible_total": len(targets), "already_initialized": len(targets) - len(pending)}
    job = MetricsInitializationJob(operator_id=user.id, reason=body.reason, targets=pending,
        total=len(pending), status="pending" if pending else "done")
    db.add(job)
    await db.flush()
    await db.commit()
    return job_record(job)


@router.get("/social/initialization-jobs/{job_id}", response_model=dict)
async def get_job(job_id: int, db: DB, user: Admin):
    row = await db.get(MetricsInitializationJob, job_id)
    if not row:
        error("MARKETPLACE_JOB_NOT_FOUND", localized("初始化任务不存在。", "The initialization job does not exist."), 404)
    return job_record(row)


@router.post("/social/initialization-jobs/{job_id}/retry", response_model=dict)
async def retry_job(job_id: int, db: DB, user: Admin):
    row = await db.scalar(select(MetricsInitializationJob).where(MetricsInitializationJob.id == job_id).with_for_update())
    if not row:
        error("MARKETPLACE_JOB_NOT_FOUND", localized("初始化任务不存在。", "The initialization job does not exist."), 404)
    if row.status not in ("done", "completed_with_errors"):
        error("MARKETPLACE_JOB_RUNNING", localized("任务正在执行，请等待完成。", "The job is still running."), 409)
    if row.errors:
        row.targets = [{"target_type": item["target_type"], "target_id": item["target_id"]} for item in row.errors]
        row.total, row.processed, row.initialized, row.skipped, row.failed = len(row.targets), 0, 0, 0, 0
        row.errors, row.status, row.lease_token, row.lease_until = [], "pending", None, None
    await db.commit()
    return job_record(row)
