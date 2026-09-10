# Admin project list and detail for failure triage
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.deps import get_current_admin
from app.models import Project, Shot, User
from app.models_tasks import TaskRun
from app.schemas import (
    AdminProjectDetailOut,
    AdminProjectListOut,
    AdminProjectOut,
    AdminProjectUsageOut,
    AdminShotBriefOut,
    AdminTaskBriefOut,
    PageMeta,
)
from app.services.admin.stats import aggregate_usage_summary

router = APIRouter()


@router.get("/projects", response_model=AdminProjectListOut)
async def list_projects(
    status: str | None = None,
    q: str | None = None,
    user_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminProjectListOut:
    # Paginated projects with owner email and shot count
    owner = aliased(User)
    shot_count = (
        select(func.count(Shot.id)).where(Shot.project_id == Project.id).correlate(Project).scalar_subquery()
    )
    stmt = select(Project, owner.email, shot_count).outerjoin(owner, owner.id == Project.user_id)
    count_stmt = select(func.count()).select_from(Project)

    if status and status.strip():
        stmt = stmt.where(Project.status == status.strip())
        count_stmt = count_stmt.where(Project.status == status.strip())
    if user_id is not None:
        stmt = stmt.where(Project.user_id == user_id)
        count_stmt = count_stmt.where(Project.user_id == user_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filt = or_(Project.title.ilike(like), Project.error_msg.ilike(like))
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            stmt.order_by(Project.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    project_ids = [int(project.id) for project, _, _ in rows]
    usage_map = await aggregate_usage_summary(db, project_ids=project_ids)
    assert isinstance(usage_map, dict)

    items: list[AdminProjectOut] = []
    for project, email, scount in rows:
        data = AdminProjectOut.model_validate(project)
        data.user_email = email
        data.shot_count = int(scount or 0)
        data.charge_fen = int((usage_map.get(project.id) or {}).get("charge_fen") or 0)
        items.append(data)

    return AdminProjectListOut(
        items=items, meta=PageMeta(page=page, page_size=page_size, total=total)
    )


@router.get("/projects/{project_id}", response_model=AdminProjectDetailOut)
async def get_project(
    project_id: int,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminProjectDetailOut:
    # Project detail for ops triage
    owner = aliased(User)
    shot_count = (
        select(func.count(Shot.id)).where(Shot.project_id == Project.id).correlate(Project).scalar_subquery()
    )
    row = (
        await db.execute(
            select(Project, owner.email, shot_count)
            .outerjoin(owner, owner.id == Project.user_id)
            .where(Project.id == project_id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="项目不存在")
    project, email, scount = row
    base = AdminProjectOut.model_validate(project)
    payload = base.model_dump()
    payload.update(
        {
            "user_email": email,
            "shot_count": int(scount or 0),
            "source_type": project.source_type,
            "source_text": project.source_text,
            "resolution_mode": project.resolution_mode,
            "output_ratio": project.output_ratio or "",
            "voice_id": project.voice_id or "",
        }
    )
    data = AdminProjectDetailOut(**payload)

    usage = await aggregate_usage_summary(db, project_id=project_id)
    assert isinstance(usage, dict)
    data.usage = AdminProjectUsageOut(**usage)
    data.charge_fen = int(usage.get("charge_fen") or 0)

    shots = list(
        (
            await db.execute(
                select(Shot).where(Shot.project_id == project_id).order_by(Shot.shot_no.asc())
            )
        )
        .scalars()
        .all()
    )
    data.shots = [
        AdminShotBriefOut(
            id=s.id,
            shot_no=int(s.shot_no or 0),
            status=str(s.status or ""),
            has_image=bool(s.image_url),
            has_video=bool(s.video_url),
            has_audio=bool(s.audio_url),
            duration=float(s.duration or 0),
        )
        for s in shots
    ]

    tasks = list(
        (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.project_id == project_id)
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
