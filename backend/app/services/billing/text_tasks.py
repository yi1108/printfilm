"""Admission and idempotent settlement for inline Studio text tasks."""
import json
from sqlalchemy import select
from app.models_tasks import TaskRun
from app.models import UsageEvent
from app.services.billing.settlement import ensure_balance_for_task, freeze_for_task, settle_task


async def admit_text_task(db, user, project, key, task_type='agent_chat'):
    from app.printfilm_studio.sharing import project_for
    await project_for(db, project.id, user, lock=True)
    previous = await db.scalar(select(TaskRun).where(TaskRun.domain == 'studio', TaskRun.dedupe_key == key, TaskRun.requested_by == user.id))
    if previous:
        return previous
    task = TaskRun(domain='studio', task_type=task_type, queue_type='text', status='running', requested_by=user.id,
                   team_id=None, billing_payer_user_id=user.id, drama_project_id=project.id, dedupe_key=key, payload={})
    task.billing_estimate_fen = await ensure_balance_for_task(db, user, task)
    db.add(task)
    await db.flush()
    await freeze_for_task(db, task)
    return task


async def finish_text_task(db, key, succeeded):
    task = await db.scalar(select(TaskRun).where(TaskRun.domain == 'studio', TaskRun.dedupe_key == key).with_for_update())
    if task and task.billing_status != 'settled':
        task.status = 'succeeded' if succeeded else 'failed'
        if succeeded and not await db.scalar(select(UsageEvent.id).where(UsageEvent.task_run_id == task.id).limit(1)):
            db.add(UsageEvent(user_id=task.requested_by, team_id=task.team_id, billing_payer_user_id=task.billing_payer_user_id,
                              task_run_id=task.id, drama_project_id=task.drama_project_id, domain='studio', billing_key='llm_chat',
                              provider='platform', model='text-per-call', estimated=True, charge_fen=5, cost_fen=0,
                              raw_usage_json=json.dumps({'pricing': 'fixed_text_call', 'unit_fen': 5, 'upstream_usage_unavailable': True})))
        await db.flush()
        await settle_task(db, task.id)
