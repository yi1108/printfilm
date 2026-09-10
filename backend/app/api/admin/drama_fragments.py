"""Admin drama fragment (storyboard) list and detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.database import get_db
from app.deps import get_current_admin
from app.models import User
from app.models_drama import DramaEpisode, DramaEpisodeFragment, DramaFragmentAssetRef, DramaProject
from app.schemas import PageMeta

router = APIRouter()


class AdminDramaFragmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int
    episode_name: str | None = None
    project_id: int
    project_title: str | None = None
    user_id: int | None = None
    user_email: str | None = None
    sort_order: int = 0
    content: str = ""
    cover: str = ""
    video: str = ""
    duration_sec: int | None = None
    generation_status: str | None = None
    asset_ref_count: int = 0
    created_at: object | None = None
    updated_at: object | None = None


class AdminDramaFragmentDetailOut(AdminDramaFragmentOut):
    params: dict | None = None
    asset_ids: list[int] = []


class AdminDramaFragmentListOut(BaseModel):
    items: list[AdminDramaFragmentOut]
    meta: PageMeta


def _fragment_generation_status(fragment: DramaEpisodeFragment) -> str | None:
    params = fragment.params if isinstance(fragment.params, dict) else {}
    gen = params.get("generation")
    if isinstance(gen, dict) and gen.get("status"):
        return str(gen.get("status"))
    return None


@router.get("/drama-fragments", response_model=AdminDramaFragmentListOut)
async def list_drama_fragments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
    episode_id: int | None = None,
    generation_status: str | None = None,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDramaFragmentListOut:
    owner = aliased(User)
    asset_ref_count = (
        select(func.count(DramaFragmentAssetRef.id))
        .where(DramaFragmentAssetRef.fragment_id == DramaEpisodeFragment.id)
        .correlate(DramaEpisodeFragment)
        .scalar_subquery()
    )

    stmt = (
        select(DramaEpisodeFragment, DramaEpisode, DramaProject, owner.email, asset_ref_count)
        .join(DramaEpisode, DramaEpisode.id == DramaEpisodeFragment.episode_id)
        .join(DramaProject, DramaProject.id == DramaEpisode.project_id)
        .outerjoin(owner, owner.id == DramaProject.user_id)
    )
    count_stmt = (
        select(func.count())
        .select_from(DramaEpisodeFragment)
        .join(DramaEpisode, DramaEpisode.id == DramaEpisodeFragment.episode_id)
        .join(DramaProject, DramaProject.id == DramaEpisode.project_id)
    )

    if user_id is not None:
        stmt = stmt.where(DramaProject.user_id == user_id)
        count_stmt = count_stmt.where(DramaProject.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(DramaProject.id == project_id)
        count_stmt = count_stmt.where(DramaProject.id == project_id)
    if episode_id is not None:
        stmt = stmt.where(DramaEpisodeFragment.episode_id == episode_id)
        count_stmt = count_stmt.where(DramaEpisodeFragment.episode_id == episode_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filt = or_(
            DramaEpisodeFragment.content.ilike(like),
            DramaEpisode.name.ilike(like),
            DramaProject.title.ilike(like),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    if generation_status and generation_status.strip():
        status_val = generation_status.strip()
        stmt = stmt.where(DramaEpisodeFragment.params["generation"]["status"].as_string() == status_val)
        count_stmt = count_stmt.where(
            DramaEpisodeFragment.params["generation"]["status"].as_string() == status_val
        )

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(DramaEpisodeFragment.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    items = [
        AdminDramaFragmentOut(
            id=frag.id,
            episode_id=frag.episode_id,
            episode_name=episode.name,
            project_id=project.id,
            project_title=project.title,
            user_id=project.user_id,
            user_email=email,
            sort_order=int(frag.sort_order or 0),
            content=frag.content or "",
            cover=frag.cover or "",
            video=frag.video or "",
            duration_sec=frag.duration_sec,
            generation_status=_fragment_generation_status(frag),
            asset_ref_count=int(refs or 0),
            created_at=frag.created_at,
            updated_at=frag.updated_at,
        )
        for frag, episode, project, email, refs in rows
    ]
    return AdminDramaFragmentListOut(items=items, meta=PageMeta(page=page, page_size=page_size, total=total))


@router.get("/drama-fragments/{fragment_id}", response_model=AdminDramaFragmentDetailOut)
async def get_drama_fragment(
    fragment_id: int,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDramaFragmentDetailOut:
    owner = aliased(User)
    row = (
        await db.execute(
            select(DramaEpisodeFragment, DramaEpisode, DramaProject, owner.email)
            .join(DramaEpisode, DramaEpisode.id == DramaEpisodeFragment.episode_id)
            .join(DramaProject, DramaProject.id == DramaEpisode.project_id)
            .outerjoin(owner, owner.id == DramaProject.user_id)
            .where(DramaEpisodeFragment.id == fragment_id)
            .options(selectinload(DramaEpisodeFragment.asset_references))
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="漫剧分镜不存在")
    frag, episode, project, email = row
    asset_ids = [int(ref.asset_id) for ref in (frag.asset_references or [])]
    return AdminDramaFragmentDetailOut(
        id=frag.id,
        episode_id=frag.episode_id,
        episode_name=episode.name,
        project_id=project.id,
        project_title=project.title,
        user_id=project.user_id,
        user_email=email,
        sort_order=int(frag.sort_order or 0),
        content=frag.content or "",
        cover=frag.cover or "",
        video=frag.video or "",
        duration_sec=frag.duration_sec,
        generation_status=_fragment_generation_status(frag),
        asset_ref_count=len(asset_ids),
        created_at=frag.created_at,
        updated_at=frag.updated_at,
        params=frag.params if isinstance(frag.params, dict) else None,
        asset_ids=asset_ids,
    )
