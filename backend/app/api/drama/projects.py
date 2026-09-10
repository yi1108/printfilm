"""Drama project CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_drama import DramaEpisode, DramaProject, DramaScript
from app.schemas_drama import (
    DramaProjectCreate,
    DramaProjectListItem,
    DramaProjectOut,
    DramaProjectUpdate,
    DramaProjectUsageStats,
    DramaScriptOut,
)
from app.services.drama.access import get_owned_drama_project
from app.services.drama.generation import project_link_last_frame_enabled
from app.services.drama.project_cover import resolve_drama_project_cover
from app.services.drama.usage_stats import (
    aggregate_drama_usage_by_project_ids,
    empty_usage_stats,
    get_drama_project_usage,
)
from app.services.drama.workflow import build_project_params, resolve_drama_workflow
from app.services.tasks.service import rebalance_project_fragment_video_queue

router = APIRouter()


def _project_out(project: DramaProject, usage: DramaProjectUsageStats | None = None) -> DramaProjectOut:
    # 组装项目详情响应，附带用量统计
    script = None
    if project.script:
        script = DramaScriptOut.model_validate(project.script)
    return DramaProjectOut(
        id=project.id,
        user_id=project.user_id,
        title=project.title,
        description=project.description,
        content=project.content,
        params=project.params,
        created_at=project.created_at,
        updated_at=project.updated_at,
        script=script,
        asset_count=len(project.assets) if project.assets is not None else 0,
        episode_count=len(project.episodes) if project.episodes is not None else 0,
        workflow=resolve_drama_workflow(project),
        usage=usage or empty_usage_stats(),
    )


@router.get("/projects", response_model=list[DramaProjectListItem])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DramaProjectListItem]:
    # List current user's drama projects
    result = await db.execute(
        select(DramaProject)
        .where(DramaProject.user_id == user.id)
        .options(
            selectinload(DramaProject.script),
            selectinload(DramaProject.assets),
            selectinload(DramaProject.episodes).selectinload(DramaEpisode.fragments),
        )
        .order_by(DramaProject.updated_at.desc())
    )
    rows = list(result.scalars().all())
    usage_map = await aggregate_drama_usage_by_project_ids(
        db, user_id=user.id, project_ids=[p.id for p in rows]
    )
    items: list[DramaProjectListItem] = []
    for p in rows:
        cover_url, cover_pending = resolve_drama_project_cover(p)
        items.append(
            DramaProjectListItem(
                id=p.id,
                title=p.title,
                description=p.description,
                created_at=p.created_at,
                updated_at=p.updated_at,
                episode_count=len(p.episodes or []),
                asset_count=len(p.assets or []),
                has_script=p.script is not None,
                cover_url=cover_url,
                cover_pending=cover_pending and not cover_url,
                workflow=resolve_drama_workflow(p),
                usage=usage_map.get(p.id) or empty_usage_stats(),
            )
        )
    return items


@router.post("/projects", response_model=DramaProjectOut)
async def create_project(
    body: DramaProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaProjectOut:
    # Create project + empty script draft from creative source
    source = (body.source or "").strip()
    if len(source) < 20:
        raise HTTPException(status_code=400, detail="原始创意至少需要 20 个字")
    title = (body.title or "").strip()
    if not title:
        title = source[:40] + ("…" if len(source) > 40 else "")
    workflow = (body.workflow or "script").strip().lower()
    if workflow not in ("script", "canvas"):
        workflow = "script"
    project_params = build_project_params(
        workflow=workflow,
        episode_count=body.episode_count,
        image_style_id=body.image_style_id,
        extra=body.params,
    )
    project = DramaProject(
        user_id=user.id,
        title=title or ("自由画布项目" if workflow == "canvas" else "未命名漫剧"),
        description=body.description,
        params=project_params,
    )
    db.add(project)
    await db.flush()
    script = DramaScript(
        project_id=project.id,
        name=project.title,
        source=source,
        params={
            "episode_count": project_params.get("episode_count") or body.episode_count,
            "image_style_id": body.image_style_id,
            "summary_status": "skipped" if workflow == "canvas" else "pending",
            "episode_content_status": "skipped" if workflow == "canvas" else "pending",
            "workflow": workflow,
        },
    )
    db.add(script)
    await db.commit()
    project = await get_owned_drama_project(
        db, project.id, user, with_script=True, with_assets=True, with_episodes=True
    )
    return _project_out(project)


@router.get("/projects/{project_id}", response_model=DramaProjectOut)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaProjectOut:
    project = await get_owned_drama_project(
        db, project_id, user, with_script=True, with_assets=True, with_episodes=True
    )
    usage = await get_drama_project_usage(db, user_id=user.id, project_id=project.id)
    return _project_out(project, usage)


@router.patch("/projects/{project_id}", response_model=DramaProjectOut)
async def update_project(
    project_id: int,
    body: DramaProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaProjectOut:
    project = await get_owned_drama_project(db, project_id, user, with_script=True)
    prev_link = project_link_last_frame_enabled(project)
    if body.title is not None:
        project.title = body.title.strip() or project.title
    if body.description is not None:
        project.description = body.description
    if body.content is not None:
        project.content = body.content
    if body.params is not None:
        project.params = body.params
    await db.commit()

    # 镜间衔接开关变化时，动态重排仍排队的分镜视频任务
    next_link = project_link_last_frame_enabled(project)
    if body.params is not None and prev_link != next_link:
        await rebalance_project_fragment_video_queue(
            db,
            project_id,
            sequential=next_link,
            user_id=user.id,
        )

    project = await get_owned_drama_project(
        db, project_id, user, with_script=True, with_assets=True, with_episodes=True
    )
    usage = await get_drama_project_usage(db, user_id=user.id, project_id=project.id)
    return _project_out(project, usage)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = await get_owned_drama_project(db, project_id, user)
    await db.delete(project)
    await db.commit()
    return {"ok": True}
