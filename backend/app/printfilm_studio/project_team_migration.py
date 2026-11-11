"""Detach retired organization scopes. Never rewrite historical tasks or money."""
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.models_drama import DramaProject
from app.models_tasks import TaskRun
from app.models_teams import TeamMember
from app.models_printfilm_studio import PrintfilmStudioCanvasDocument as StudioCanvas
from app.printfilm_studio.sharing import CanvasMember
from app.services.drama.workflow import resolve_drama_workflow

async def migrate_project_teams(db):
    active = await db.scalar(select(func.count()).select_from(TaskRun).where(TaskRun.team_id.is_not(None), TaskRun.status.in_(['pending','leased','running','awaiting_poll','awaiting_review','cancel_requested'])))
    if active:
        raise ValueError('旧团队仍有活动任务，请完成后迁移')
    projects = list((await db.scalars(select(DramaProject).where(DramaProject.team_id.is_not(None)).options(selectinload(DramaProject.script)).with_for_update())).all())
    members = 0
    for project in projects:
        old_team = project.team_id
        if resolve_drama_workflow(project) == 'canvas':
            user_ids = (await db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == old_team, TeamMember.active.is_(True), TeamMember.user_id != project.user_id))).all()
            for user_id in user_ids:
                exists = await db.scalar(select(CanvasMember.id).where(CanvasMember.project_id == project.id, CanvasMember.user_id == user_id))
                if not exists:
                    db.add(CanvasMember(project_id=project.id, user_id=user_id)); members += 1
        project.params = {**(project.params or {}), 'legacy_team_id': old_team}
        project.team_id = None
        for canvas in (await db.scalars(select(StudioCanvas).where(StudioCanvas.project_id == project.id))).all():
            canvas.team_id = None
    await db.flush()
    return {'projects': len(projects), 'project_members': members}
