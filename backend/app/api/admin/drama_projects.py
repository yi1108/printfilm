"""Admin drama project list/detail with usage and production status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.database import get_db
from app.deps import get_current_admin
from app.models import User
from app.models_drama import DramaAsset, DramaEpisode, DramaProject, DramaScript
from app.models_tasks import TaskRun
from app.schemas import AdminProjectUsageOut, AdminTaskBriefOut, PageMeta
from app.services.admin.stats import aggregate_usage_summary

router = APIRouter()


class AdminDramaEpisodeBriefOut(BaseModel):
    id: int
    name: str
    fragment_count: int = 0
    fragment_plan_status: str | None = None


class AdminDramaAssetBriefOut(BaseModel):
    id: int
    type: str
    name: str | None = None
    has_cover: bool = False
    generation_status: str | None = None


class AdminDramaProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    user_email: str | None = None
    title: str
    description: str | None = None
    created_at: object | None = None
    updated_at: object | None = None
    episode_count: int = 0
    asset_count: int = 0
    charge_fen: int = 0
    summary_status: str | None = None
    assets_seed_status: str | None = None


class AdminDramaProjectListOut(BaseModel):
    items: list[AdminDramaProjectOut]
    meta: PageMeta


class AdminDramaProjectDetailOut(AdminDramaProjectOut):
    fragment_count: int = 0
    episode_content_status: str | None = None
    usage: AdminProjectUsageOut = Field(default_factory=AdminProjectUsageOut)
    episodes: list[AdminDramaEpisodeBriefOut] = Field(default_factory=list)
    assets: list[AdminDramaAssetBriefOut] = Field(default_factory=list)
    recent_tasks: list[AdminTaskBriefOut] = Field(default_factory=list)


def _script_status(project: DramaProject, key: str) -> str | None:
    script = project.script
    if not script or not isinstance(script.params, dict):
        return None
    raw = script.params.get(key)
    return str(raw) if raw else None


def _project_param_status(project: DramaProject, key: str) -> str | None:
    params = project.params if isinstance(project.params, dict) else {}
    raw = params.get(key)
    return str(raw) if raw else None


def _asset_generation_status(asset: DramaAsset) -> str | None:
    params = asset.params if isinstance(asset.params, dict) else {}
    gen = params.get("generation")
    if isinstance(gen, dict) and gen.get("status"):
        return str(gen.get("status"))
    return None


@router.get("/drama-projects", response_model=AdminDramaProjectListOut)
async def list_drama_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = None,
    user_id: int | None = None,
    summary_status: str | None = None,
    assets_seed_status: str | None = None,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDramaProjectListOut:
    # Paginated drama projects joined with user email
    owner = aliased(User)
    ep_count = (
        select(func.count(DramaEpisode.id))
        .where(DramaEpisode.project_id == DramaProject.id)
        .correlate(DramaProject)
        .scalar_subquery()
    )
    asset_count = (
        select(func.count(DramaAsset.id))
        .where(DramaAsset.project_id == DramaProject.id)
        .correlate(DramaProject)
        .scalar_subquery()
    )
    stmt = (
        select(DramaProject, owner.email, ep_count, asset_count)
        .outerjoin(owner, owner.id == DramaProject.user_id)
        .options(selectinload(DramaProject.script))
    )
    count_stmt = select(func.count()).select_from(DramaProject)

    if user_id is not None:
        stmt = stmt.where(DramaProject.user_id == user_id)
        count_stmt = count_stmt.where(DramaProject.user_id == user_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filt = or_(DramaProject.title.ilike(like), DramaProject.description.ilike(like))
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    if summary_status and summary_status.strip():
        status_val = summary_status.strip()
        stmt = stmt.join(DramaScript, DramaScript.project_id == DramaProject.id).where(
            DramaScript.params["summary_status"].as_string() == status_val
        )
        count_stmt = count_stmt.join(DramaScript, DramaScript.project_id == DramaProject.id).where(
            DramaScript.params["summary_status"].as_string() == status_val
        )
    if assets_seed_status and assets_seed_status.strip():
        seed_val = assets_seed_status.strip()
        stmt = stmt.where(DramaProject.params["assets_seed_status"].as_string() == seed_val)
        count_stmt = count_stmt.where(DramaProject.params["assets_seed_status"].as_string() == seed_val)

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(DramaProject.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    project_ids = [int(p.id) for p, _, _, _ in rows]
    usage_map = await aggregate_usage_summary(db, drama_project_ids=project_ids)
    assert isinstance(usage_map, dict)

    items: list[AdminDramaProjectOut] = []
    for project, email, ecount, acount in rows:
        data = AdminDramaProjectOut.model_validate(project)
        data.user_email = email
        data.episode_count = int(ecount or 0)
        data.asset_count = int(acount or 0)
        data.charge_fen = int((usage_map.get(project.id) or {}).get("charge_fen") or 0)
        data.summary_status = _script_status(project, "summary_status")
        data.assets_seed_status = _project_param_status(project, "assets_seed_status")
        items.append(data)

    return AdminDramaProjectListOut(
        items=items, meta=PageMeta(page=page, page_size=page_size, total=total)
    )


@router.get("/drama-projects/{project_id}", response_model=AdminDramaProjectDetailOut)
async def get_drama_project(
    project_id: int,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDramaProjectDetailOut:
    owner = aliased(User)
    row = (
        await db.execute(
            select(DramaProject, owner.email)
            .outerjoin(owner, owner.id == DramaProject.user_id)
            .where(DramaProject.id == project_id)
            .options(
                selectinload(DramaProject.script),
                selectinload(DramaProject.episodes).selectinload(DramaEpisode.fragments),
                selectinload(DramaProject.assets),
            )
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="漫剧项目不存在")
    project, email = row

    usage = await aggregate_usage_summary(db, drama_project_id=project_id)
    assert isinstance(usage, dict)

    episodes = sorted(project.episodes or [], key=lambda e: e.id)
    assets = sorted(project.assets or [], key=lambda a: a.id)
    fragment_count = sum(len(ep.fragments or []) for ep in episodes)

    base = AdminDramaProjectOut.model_validate(project)
    data = AdminDramaProjectDetailOut(**base.model_dump())
    data.user_email = email
    data.episode_count = len(episodes)
    data.asset_count = len(assets)
    data.fragment_count = fragment_count
    data.charge_fen = int(usage.get("charge_fen") or 0)
    data.summary_status = _script_status(project, "summary_status")
    data.episode_content_status = _script_status(project, "episode_content_status")
    data.assets_seed_status = _project_param_status(project, "assets_seed_status")
    data.usage = AdminProjectUsageOut(**usage)
    data.episodes = [
        AdminDramaEpisodeBriefOut(
            id=ep.id,
            name=ep.name or f"集 #{ep.id}",
            fragment_count=len(ep.fragments or []),
            fragment_plan_status=(
                str((ep.params or {}).get("fragment_plan_status"))
                if isinstance(ep.params, dict) and (ep.params or {}).get("fragment_plan_status")
                else None
            ),
        )
        for ep in episodes
    ]
    data.assets = [
        AdminDramaAssetBriefOut(
            id=a.id,
            type=str(a.type or "none"),
            name=a.name,
            has_cover=bool(a.cover or a.url),
            generation_status=_asset_generation_status(a),
        )
        for a in assets
    ]

    tasks = list(
        (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.drama_project_id == project_id)
                .order_by(TaskRun.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    data.recent_tasks = [
        AdminTaskBriefOut(
            id=t.id,
            domain=str(t.domain or ""),
            task_type=str(t.task_type or ""),
            status=str(t.status or ""),
            progress_percent=int(t.progress_percent or 0),
            billing_charged_fen=int(t.billing_charged_fen or 0),
            billing_estimate_fen=int(t.billing_estimate_fen or 0),
            error_message=t.error_message,
            created_at=t.created_at,
            finished_at=t.finished_at,
        )
        for t in tasks
    ]
    return data
