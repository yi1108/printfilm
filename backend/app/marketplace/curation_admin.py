"""Audited admin-only curation; never grants visibility to restricted content."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from .app_access import error
from .curation import configuration
from .curation_models import ContentCuration, CurationEvent, CurationRevision
from .dependencies import Admin, DB
from .models import Series, Work

router = APIRouter()
Kind = Literal["work", "series"]


class CurationFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0, strict=True)
    is_featured: bool
    is_pinned: bool
    pin_priority: int = Field(100, ge=0, le=9999, strict=True)


class CurationInput(CurationFields):
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value):
        if not value.strip():
            raise ValueError("请填写运营调整原因")
        return value.strip()


class BatchItem(CurationFields):
    target_type: Kind
    target_id: int = Field(gt=0, strict=True)


class BatchInput(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value):
        return CurationInput.reason_required(value)


async def target(db, kind, target_id):
    item = await db.get(Work if kind == "work" else Series, target_id)
    if not item or item.deleted_at:
        error("MARKETPLACE_CONTENT_UNAVAILABLE", "内容不存在或暂不可访问", 404)
    return item


async def lock_revision(db):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    factory = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    await db.execute(factory(CurationRevision).values(id=1, revision=0).on_conflict_do_nothing(index_elements=["id"]))
    return await db.scalar(select(CurationRevision).where(CurationRevision.id == 1).with_for_update())


async def save_curation(db, kind, target_id, body, operator_id, reason):
    # One global curation lock also serializes the first insert for each target.
    state = await lock_revision(db)
    await target(db, kind, target_id)
    row = await db.scalar(select(ContentCuration).where(ContentCuration.target_type == kind, ContentCuration.target_id == target_id).with_for_update())
    before = configuration(row, kind, target_id)
    if body.version != before["version"]:
        error("MARKETPLACE_CURATION_CHANGED", "运营配置已修改，请刷新后重试", 409)
    changed = any(before[key] != getattr(body, key) for key in ("is_featured", "is_pinned", "pin_priority"))
    if not changed:
        return before
    if row is None:
        row = ContentCuration(target_type=kind, target_id=target_id, operator_id=operator_id, version=0)
        db.add(row)
    row.is_featured, row.is_pinned, row.pin_priority = body.is_featured, body.is_pinned, body.pin_priority
    row.operator_id, row.version = operator_id, before["version"] + 1
    state.revision += 1
    after = configuration(row, kind, target_id)
    db.add(CurationEvent(target_type=kind, target_id=target_id, operator_id=operator_id, reason=reason, before=before, after=after))
    await db.flush()
    return after


@router.get("/curation/events", response_model=dict)
async def curation_events(db: DB, user: Admin, target_type: Kind | None = None, target_id: int | None = Query(None, gt=0), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    query = select(CurationEvent)
    if target_type:
        query = query.where(CurationEvent.target_type == target_type)
    if target_id:
        query = query.where(CurationEvent.target_id == target_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list((await db.scalars(query.order_by(CurationEvent.id.desc()).offset((page - 1) * page_size).limit(page_size))).all())
    return {"items": [{"id": row.id, "target_type": row.target_type, "target_id": row.target_id, "operator_id": row.operator_id,
                       "reason": row.reason, "before": row.before, "after": row.after, "created_at": row.created_at} for row in rows],
            "meta": {"page": page, "page_size": page_size, "total": total}}


@router.post("/curation/batch", response_model=dict)
async def batch_curation(body: BatchInput, db: DB, user: Admin):
    results = []
    for item in body.items:
        try:
            async with db.begin_nested():
                value = await save_curation(db, item.target_type, item.target_id, item, user.id, body.reason)
            results.append({"ok": True, **value})
        except HTTPException as exc:
            results.append({"target_type": item.target_type, "target_id": item.target_id, "ok": False, "status": exc.status_code, "error": exc.detail})
    await db.commit()
    return {"items": results}


@router.get("/curation/{target_type}/{target_id}", response_model=dict)
async def get_curation(target_type: Kind, target_id: int, db: DB, user: Admin):
    await target(db, target_type, target_id)
    row = await db.scalar(select(ContentCuration).where(ContentCuration.target_type == target_type, ContentCuration.target_id == target_id))
    return configuration(row, target_type, target_id)


@router.patch("/curation/{target_type}/{target_id}", response_model=dict)
async def update_curation(target_type: Kind, target_id: int, body: CurationInput, db: DB, user: Admin):
    value = await save_curation(db, target_type, target_id, body, user.id, body.reason)
    await db.commit()
    return value
