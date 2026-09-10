"""Admin drama asset library: cross-project list and detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.deps import get_current_admin
from app.models import User
from app.models_drama import DramaAsset, DramaProject
from app.schemas import PageMeta

router = APIRouter()


class AdminDramaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    project_title: str | None = None
    user_id: int | None = None
    user_email: str | None = None
    type: str
    asset_type: str
    name: str | None = None
    cover: str | None = None
    url: str | None = None
    has_cover: bool = False
    generation_status: str | None = None
    derive_id: str | None = None
    created_at: object | None = None
    updated_at: object | None = None


class AdminDramaAssetDetailOut(AdminDramaAssetOut):
    params: dict | None = None


class AdminDramaAssetListOut(BaseModel):
    items: list[AdminDramaAssetOut]
    meta: PageMeta


def _asset_generation_status(asset: DramaAsset) -> str | None:
    params = asset.params if isinstance(asset.params, dict) else {}
    gen = params.get("generation")
    if isinstance(gen, dict) and gen.get("status"):
        return str(gen.get("status"))
    return None


def _asset_to_out(
    asset: DramaAsset,
    *,
    project_title: str | None = None,
    user_id: int | None = None,
    user_email: str | None = None,
) -> AdminDramaAssetOut:
    return AdminDramaAssetOut(
        id=asset.id,
        project_id=asset.project_id,
        project_title=project_title,
        user_id=user_id,
        user_email=user_email,
        type=str(asset.type or "none"),
        asset_type=str(asset.asset_type or "image"),
        name=asset.name,
        cover=asset.cover,
        url=asset.url,
        has_cover=bool(asset.cover or asset.url),
        generation_status=_asset_generation_status(asset),
        derive_id=asset.derive_id,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


@router.get("/drama-assets", response_model=AdminDramaAssetListOut)
async def list_drama_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
    asset_kind: str | None = Query(None, alias="type"),
    asset_type: str | None = None,
    generation_status: str | None = None,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDramaAssetListOut:
    owner = aliased(User)
    stmt = (
        select(DramaAsset, DramaProject, owner.email)
        .join(DramaProject, DramaProject.id == DramaAsset.project_id)
        .outerjoin(owner, owner.id == DramaProject.user_id)
    )
    count_stmt = (
        select(func.count())
        .select_from(DramaAsset)
        .join(DramaProject, DramaProject.id == DramaAsset.project_id)
    )

    if user_id is not None:
        stmt = stmt.where(DramaProject.user_id == user_id)
        count_stmt = count_stmt.where(DramaProject.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(DramaAsset.project_id == project_id)
        count_stmt = count_stmt.where(DramaAsset.project_id == project_id)
    if asset_kind and asset_kind.strip():
        type_val = asset_kind.strip()
        stmt = stmt.where(DramaAsset.type == type_val)
        count_stmt = count_stmt.where(DramaAsset.type == type_val)
    if asset_type and asset_type.strip():
        at_val = asset_type.strip()
        stmt = stmt.where(DramaAsset.asset_type == at_val)
        count_stmt = count_stmt.where(DramaAsset.asset_type == at_val)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filt = or_(DramaAsset.name.ilike(like), DramaAsset.derive_id.ilike(like))
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    if generation_status and generation_status.strip():
        status_val = generation_status.strip()
        stmt = stmt.where(DramaAsset.params["generation"]["status"].as_string() == status_val)
        count_stmt = count_stmt.where(DramaAsset.params["generation"]["status"].as_string() == status_val)

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(DramaAsset.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items = [
        _asset_to_out(
            asset,
            project_title=project.title,
            user_id=project.user_id,
            user_email=email,
        )
        for asset, project, email in rows
    ]
    return AdminDramaAssetListOut(items=items, meta=PageMeta(page=page, page_size=page_size, total=total))


@router.get("/drama-assets/{asset_id}", response_model=AdminDramaAssetDetailOut)
async def get_drama_asset(
    asset_id: int,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDramaAssetDetailOut:
    owner = aliased(User)
    row = (
        await db.execute(
            select(DramaAsset, DramaProject, owner.email)
            .join(DramaProject, DramaProject.id == DramaAsset.project_id)
            .outerjoin(owner, owner.id == DramaProject.user_id)
            .where(DramaAsset.id == asset_id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="漫剧资产不存在")
    asset, project, email = row
    base = _asset_to_out(
        asset,
        project_title=project.title,
        user_id=project.user_id,
        user_email=email,
    )
    return AdminDramaAssetDetailOut(**base.model_dump(), params=asset.params if isinstance(asset.params, dict) else None)
