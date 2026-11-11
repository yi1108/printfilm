"""Membership-aware task cancellation without interrupting submitted upstream work."""
from datetime import UTC, datetime
from sqlalchemy import select
from app.models_tasks import TaskRun


async def prepare_background_task(db, project_id: int, fallback_user):
    """A server-side child inherits its active parent actor; the lock layer checks coverage."""
    from app.models import User
    from app.models_drama import DramaProject
    from app.services.billing.context import get_current_task_run_id
    from app.services.tasks.service import ACTIVE_TASK_STATUSES

    parent_id = get_current_task_run_id()
    if parent_id is None:
        return fallback_user
    parent = await db.get(TaskRun, parent_id)
    project = await db.get(DramaProject, project_id)
    if parent is None or parent.team_id is None:
        return fallback_user
    if (
        project is None
        or parent.domain != "drama"
        or parent.drama_project_id != project.id
        or parent.team_id != project.team_id
        or parent.status not in ACTIVE_TASK_STATUSES
        or parent.cancel_requested
    ):
        raise ValueError("后台派生任务与父任务范围不匹配")
    actor = await db.get(User, int(parent.requested_by))
    if actor is None:
        raise ValueError("任务发起人不存在")
    await ensure_task_may_submit(db, parent)
    from app.services.teams.edit_locks import task_resource

    db.info["team_parent_task_id"] = int(parent.id)
    db.info["team_parent_resource"] = await task_resource(db, parent)
    return actor


async def ensure_task_may_submit(db, task: TaskRun) -> None:
    if task.domain == 'studio' and task.drama_project_id is not None:
        from app.models_drama import DramaProject
        from app.printfilm_studio.sharing import require_canvas_access
        project = await db.get(DramaProject, task.drama_project_id)
        if not project:
            raise ValueError('画布不存在')
        await require_canvas_access(db, project, task.requested_by)
    if task.team_id is None:
        return
    from app.services.teams.access import get_team
    await get_team(db, int(task.team_id), int(task.requested_by))
    if task.cancel_requested:
        raise ValueError("任务已请求取消，不能提交新的生成")


async def ensure_upstream_submission_allowed(db, task_id: int) -> None:
    task = await db.get(TaskRun, task_id)
    if task is not None:
        await ensure_task_may_submit(db, task)


async def cancel_removed_member_tasks(db, team_id: int, user_id: int) -> int:
    """Caller owns the membership transaction. Only unstarted tasks terminate immediately."""
    from app.services.billing.settlement import settle_task
    from app.services.tasks.service import ACTIVE_TASK_STATUSES, append_task_event
    tasks = list((await db.execute(select(TaskRun).where(TaskRun.team_id == team_id, TaskRun.requested_by == user_id, TaskRun.status.in_(tuple(ACTIVE_TASK_STATUSES))).with_for_update())).scalars().all())
    changed = 0
    for task in tasks:
        payload = task.payload if isinstance(task.payload, dict) else {}
        submitted = bool(task.provider_task_id or payload.get("provider_task_id") or task.started_at)
        if submitted:
            # Membership is checked before every new upstream POST. Existing GET polling and
            # download continue, preserving delivered output and charging its original wallet.
            continue
        task.cancel_requested = True
        task.status = "cancelled"
        task.error_code = "team_member_removed"
        task.error_message = "成员已退出团队，尚未开始的任务已取消"
        task.finished_at = datetime.now(UTC)
        task.next_action_at = None
        task.lease_token = None
        task.lease_until = None
        await append_task_event(db, task.id, event_type="task.cancelled", status="cancelled", message=task.error_message)
        await settle_task(db, task.id)
        changed += 1
    return changed
