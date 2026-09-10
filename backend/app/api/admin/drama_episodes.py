"""Admin drama episode list and detail with fragments."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.database import get_db
from app.deps import get_current_admin
from app.models import User
from app.models_drama import DramaEpisode, DramaEpisodeFragment, DramaProject
from app.schemas import PageMeta

router = APIRouter()


class AdminDramaFragmentBriefOut(BaseModel):
    id: int
    sort_order: int = 0
    content: str = ""
    cover: str = ""
    video: str = ""
    duration_sec: int | None = None
    generation_status: str | None = None
    asset_ref_count: int = 0


class AdminDramaEpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    project_title: str | None = None
    user_id: int | None = None
    user_email: str | None = None
    name: str
    fragment_count: int = 0
    fragment_plan_status: str | None = None
    created_at: object | None = None
    updated_at: object | None = None


class AdminDramaEpisodeDetailOut(AdminDramaEpisodeOut):
    fragments: list[AdminDramaFragmentBriefOut] = Field(default_factory=list)


class AdminDramaEpisodeListOut(BaseModel):
    items: list[AdminDramaEpisodeOut]
    meta: PageMeta


def _fragment_generation_status(fragment: DramaEpisodeFragment) -> str | None:
    params = fragment.params if isinstance(fragment.params, dict) else {}
    gen = params.get("generation")
    if isinstance(gen, dict) and gen.get("status"):
        return str(gen.get("status"))
    return None


def _episode_plan_status(episode: DramaEpisode) -> str | None:
    params = episode.params if isinstance(episode.params, dict) else {}
    raw = params.get("fragment_plan_status")
    return str(raw) if raw else None


@router.get("/drama-episodes", response_model=AdminDramaEpisodeListOut)
async def list_drama_episodes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDramaEpisodeListOut:
    owner = aliased(User)
    frag_count = (
        select(func.count(DramaEpisodeFragment.id))
        .where(DramaEpisodeFragment.episode_id == DramaEpisode.id)
        .correlate(DramaEpisode)
        .scalar_subquery()
    )
    stmt = (
        select(DramaEpisode, DramaProject, owner.email, frag_count)
        .join(DramaProject, DramaProject.id == DramaEpisode.project_id)
        .outerjoin(owner, owner.id == DramaProject.user_id)
    )
    count_stmt = (
        select(func.count())
        .select_from(DramaEpisode)
        .join(DramaProject, DramaProject.id == DramaEpisode.project_id)
    )

    if user_id is not None:
        stmt = stmt.where(DramaProject.user_id == user_id)
        count_stmt = count_stmt.where(DramaProject.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(DramaEpisode.project_id == project_id)
        count_stmt = count_stmt.where(DramaEpisode.project_id == project_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filt = or_(DramaEpisode.name.ilike(like), DramaProject.title.ilike(like))
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(DramaEpisode.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items = [
        AdminDramaEpisodeOut(
            id=ep.id,
            project_id=ep.project_id,
            project_title=project.title,
            user_id=project.user_id,
            user_email=email,
            name=ep.name or f"集 #{ep.id}",
            fragment_count=int(fcount or 0),
            fragment_plan_status=_episode_plan_status(ep),
            created_at=ep.created_at,
            updated_at=ep.updated_at,
        )
        for ep, project, email, fcount in rows
    ]
    return AdminDramaEpisodeListOut(items=items, meta=PageMeta(page=page, page_size=page_size, total=total))


@router.get("/drama-episodes/{episode_id}", response_model=AdminDramaEpisodeDetailOut)
async def get_drama_episode(
    episode_id: int,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDramaEpisodeDetailOut:
    owner = aliased(User)
    row = (
        await db.execute(
            select(DramaEpisode, DramaProject, owner.email)
            .join(DramaProject, DramaProject.id == DramaEpisode.project_id)
            .outerjoin(owner, owner.id == DramaProject.user_id)
            .where(DramaEpisode.id == episode_id)
            .options(
                selectinload(DramaEpisode.fragments).selectinload(DramaEpisodeFragment.asset_references)
            )
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="漫剧分集不存在")
    episode, project, email = row
    fragments = sorted(episode.fragments or [], key=lambda f: (f.sort_order, f.id))
    return AdminDramaEpisodeDetailOut(
        id=episode.id,
        project_id=episode.project_id,
        project_title=project.title,
        user_id=project.user_id,
        user_email=email,
        name=episode.name or f"集 #{episode.id}",
        fragment_count=len(fragments),
        fragment_plan_status=_episode_plan_status(episode),
        created_at=episode.created_at,
        updated_at=episode.updated_at,
        fragments=[
            AdminDramaFragmentBriefOut(
                id=f.id,
                sort_order=int(f.sort_order or 0),
                content=f.content or "",
                cover=f.cover or "",
                video=f.video or "",
                duration_sec=f.duration_sec,
                generation_status=_fragment_generation_status(f),
                asset_ref_count=len(f.asset_references or []),
            )
            for f in fragments
        ],
    )
