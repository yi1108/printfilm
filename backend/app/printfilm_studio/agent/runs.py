"""Durable Agent runs. HTTP subscribers never own the execution lifetime."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.database import AsyncSessionLocal
from app.models import User
from app.models_printfilm_studio import (
    PrintfilmStudioAgentRun as Run, PrintfilmStudioAgentEvent as Event,
    PrintfilmStudioAgentSession as Session, PrintfilmStudioAgentMessage as Message,
)
from app.printfilm_studio.agent.director_skills import load_director_skill_block
from app.printfilm_studio.agent.queries import DatabaseCanvas, load_project_view
from app.printfilm_studio.agent.runtime import iter_agent_turn
from app.printfilm_studio.canvas.service import get_project

logger = logging.getLogger(__name__)
_workers: set[asyncio.Task] = set()
LEASE_SECONDS = 45


async def latest_run(db, session_id):
    return await db.scalar(select(Run).where(Run.session_id == session_id).order_by(Run.created_at.desc(), Run.id.desc()).limit(1))


def run_out(run):
    return None if run is None else {'id': run.id, 'status': run.status, 'last_sequence': run.next_sequence - 1}


async def append_event(db, run_id, payload):
    seq = await db.scalar(update(Run).where(Run.id == run_id, Run.status == 'running').values(next_sequence=Run.next_sequence + 1).returning(Run.next_sequence))
    if seq is None:
        raise RuntimeError('Agent run no longer exists')
    event = {**payload, 'run_id': run_id, 'sequence': seq - 1}
    db.add(Event(run_id=run_id, sequence=seq - 1, payload=event))
    await db.commit()
    return event


async def read_events(db, run_id, after=0):
    return list((await db.scalars(select(Event.payload).where(Event.run_id == run_id, Event.sequence > after).order_by(Event.sequence).limit(200))).all())


async def reserve_run(db, session_id, prompt, request_id, *, references=None, billing_context=None):
    existing = await db.scalar(select(Run).where(Run.session_id == session_id, Run.request_id == request_id))
    if existing:
        return existing, False
    claimed = await db.scalar(update(Session).where(Session.id == session_id, Session.status != 'running').values(status='running').returning(Session.id))
    if not claimed:
        await db.rollback()
        existing = await db.scalar(select(Run).where(Run.session_id == session_id, Run.request_id == request_id))
        if existing:
            return existing, False
        raise HTTPException(409, '当前会话仍在执行，请等待或先停止')
    sequence = int(await db.scalar(select(func.max(Message.sequence)).where(Message.session_id == session_id)) or 0) + 1
    run = Run(session_id=session_id, request_id=request_id, message_sequence=sequence + 1, message_id=str(uuid.uuid4()))
    db.add(run)
    db.add(Message(session_id=session_id, role='user', content=prompt, sequence=sequence,
                   message_metadata={'references': references} if references else {}))
    await db.flush()
    if billing_context:
        from app.services.billing.text_tasks import admit_text_task
        user, project = billing_context
        try:
            await admit_text_task(db, user, project, f'studio-agent:{run.id}')
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(402, str(exc)) from exc
    # Initial events and the admission claim commit together.
    run.next_sequence = 3
    db.add_all([
        Event(run_id=run.id, sequence=1, payload={'type': 'session', 'session_id': session_id, 'run_id': run.id, 'sequence': 1}),
        Event(run_id=run.id, sequence=2, payload={'type': 'message_start', 'message_id': run.message_id, 'run_id': run.id, 'sequence': 2}),
    ])
    await db.commit()
    return run, True


async def finish_run(db, run_id, status, answer='', error=None):
    # One winner owns terminal events and the assistant message.
    claimed = await db.scalar(update(Run).where(Run.id == run_id, Run.status == 'running').values(status=status).returning(Run.session_id))
    if not claimed:
        await db.rollback()
        return
    run = await db.get(Run, run_id, populate_existing=True)
    from app.services.billing.text_tasks import finish_text_task
    await finish_text_task(db, f'studio-agent:{run_id}', status == 'completed')
    await db.execute(update(Session).where(Session.id == claimed).values(status=status))
    trace = list((await db.scalars(select(Event.payload).where(Event.run_id == run_id).order_by(Event.sequence))).all())
    trace = [event for event in trace if event.get('type') in {'thinking', 'tool_start', 'tool_result', 'canvas_patch', 'task_created', 'error', 'proposal'}]
    if answer or trace or error:
        db.add(Message(id=run.message_id, session_id=claimed, role='assistant', content=answer, sequence=run.message_sequence, message_metadata={'run_id': run_id, 'status': status}))
    # Commit status and final events atomically so readers cannot miss done.
    payloads = ([error] if error else []) + [{'type': 'done', 'status': status}]
    for payload in payloads:
        db.add(Event(run_id=run_id, sequence=run.next_sequence, payload={**payload, 'run_id': run_id, 'sequence': run.next_sequence}))
        run.next_sequence += 1
    await db.commit()


async def expire_run(db, run_id):
    run = await db.get(Run, run_id, populate_existing=True)
    if not run or run.status != 'running':
        return False
    heartbeat = run.heartbeat_at.replace(tzinfo=UTC) if run.heartbeat_at.tzinfo is None else run.heartbeat_at
    if heartbeat >= datetime.now(UTC) - timedelta(seconds=LEASE_SECONDS):
        return False
    # Lock and recheck the timestamp against a concurrent heartbeat.
    changed = await db.scalar(update(Run).where(Run.id == run_id, Run.status == 'running', Run.heartbeat_at < datetime.now(UTC) - timedelta(seconds=LEASE_SECONDS)).values(heartbeat_at=Run.heartbeat_at).returning(Run.id).execution_options(synchronize_session=False))
    if not changed:
        await db.rollback()
        return False
    # Subscriber pages are limited to 200 events; recovering a partial streamed
    # answer must read the entire run, not only its first subscription page.
    events = (await db.scalars(select(Event.payload).where(Event.run_id == run_id).order_by(Event.sequence))).all()
    partial = ''.join(str(e.get('content', '')) for e in events if e.get('type') == 'message_delta')
    await finish_run(db, run_id, 'failed', partial, {'type': 'error', 'code': 'run_interrupted', 'message': '服务执行中断，已保留完成步骤；请检查画布后继续'})
    return True


async def cancel_linked_tasks(db, run_id, user):
    from app.services.tasks.service import cancel_task_for_user
    from app.models_tasks import TaskRun
    user_id = user.id
    events = (await db.scalars(select(Event.payload).where(Event.run_id == run_id))).all()
    linked = set((await db.scalars(select(TaskRun.id).where(TaskRun.requested_by == user_id, TaskRun.payload['studio_agent_run_id'].as_string() == run_id))).all())
    linked.update(e.get('platform_task_id') or str(e.get('task_id', '')).removeprefix('task-') for e in events if e.get('type') == 'task_created')
    for task_id in linked:
        if not str(task_id).isdigit():
            continue
        try:
            user = await db.get(User, user_id)
            await cancel_task_for_user(db, user, int(task_id))
        except (ValueError, HTTPException):
            await db.rollback()  # Already terminal, not cancelable or no longer accessible.


def launch_run(run_id, session_id, user_id, prompt, info, lock):
    task = asyncio.create_task(execute_run(run_id, session_id, user_id, prompt, info, lock))
    _workers.add(task)
    def complete(done):
        _workers.discard(done)
        if not done.cancelled() and done.exception():
            logger.error('Studio Agent worker failed run=%s', run_id, exc_info=done.exception())
    task.add_done_callback(complete)


async def shutdown_runs():
    tasks = list(_workers)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def execute_run(run_id, session_id, user_id, prompt, info, lock, factory=AsyncSessionLocal):
    stop = asyncio.Event()
    async def heartbeat():
        while True:
            async with factory() as db:
                run = await db.get(Run, run_id)
                if not run or run.status != 'running' or run.stop_requested:
                    stop.set()
                    return
                await db.execute(update(Run).where(Run.id == run_id, Run.status == 'running').values(heartbeat_at=datetime.now(UTC)))
                await db.commit()
            await asyncio.sleep(1)
    async def monitored_heartbeat():
        try:
            await heartbeat()
        except Exception:
            stop.set()
            logger.exception('Studio Agent heartbeat failed run=%s', run_id)
    monitor = asyncio.create_task(monitored_heartbeat())
    parts = []
    try:
        async with factory() as db:
            db.info.update(info)
            db.info['studio_agent_run_id'] = run_id
            user = await db.get(User, user_id)
            session = await db.get(Session, session_id)
            project = await get_project(db, session.project_id, user)
            async def guard():
                from app.printfilm_studio import ensure_enabled
                ensure_enabled()
                await get_project(db, project.id, user)
                current = await db.get(Run, run_id, populate_existing=True)
                if current is None or current.status != 'running' or current.stop_requested:
                    stop.set()
                if not stop.is_set():
                    view.update(await load_project_view(db, project, user))
            run = await db.get(Run, run_id)
            previous = (await db.scalars(select(Message).where(Message.session_id == session_id, Message.sequence < run.message_sequence - 1).order_by(Message.sequence.desc()).limit(20))).all()
            view = await load_project_view(db, project, user)
            canvas = DatabaseCanvas(db, project, user, **lock)
            canvas.stopped = stop.is_set
            history = [{'role': item.role, 'content': item.content} for item in reversed(previous)]
            from functools import partial
            from app.services.llm_client import chat_completions
            from app.printfilm_studio.integration.llm_stream import chat_completions_stream, TEXT_WRITING_TIMEOUT
            # Writing returns one complete response; the durable run/event channel
            # still owns cancellation and completion independently of the panel.
            writing = info.get('studio_enabled_tools') == []
            from app.config import get_settings
            from app.services.media_model_presets import current_model_selection
            model_id = current_model_selection('text', session.model_id, get_settings().model_llm) or None
            complete = partial(chat_completions, model_id=model_id, timeout=TEXT_WRITING_TIMEOUT if writing else 300.0, strict_output=writing)
            stream = None if writing else partial(chat_completions_stream, model_id=model_id, timeout=300.0)
            skill_block = await load_director_skill_block(db, user_id, info)
            async for event in iter_agent_turn(view=view, canvas=canvas, prompt=prompt, history=history, allow_write=True, stopped=stop.is_set, guard=guard, complete=complete, stream=stream, enabled_tools=info.get('studio_enabled_tools'), review_changes=bool(info.get('studio_review_changes')), skill_block=skill_block, required_tool=info.get('studio_required_tool'), planning_node_ids=info.get('studio_planning_node_ids')):
                if event.get('type') == 'message_delta':
                    parts.append(str(event.get('content') or ''))
                await append_event(db, run_id, event)
            current = await db.get(Run, run_id, populate_existing=True)
            cancelled = stop.is_set() or current.stop_requested
            if cancelled:
                await cancel_linked_tasks(db, run_id, user)
            await finish_run(db, run_id, 'cancelled' if cancelled else 'completed', ''.join(parts))
    except asyncio.CancelledError:
        async with factory() as db:
            await finish_run(db, run_id, 'failed', ''.join(parts), {'type': 'error', 'code': 'run_interrupted', 'message': '服务停止，已保留完成步骤'})
        raise
    except Exception as exc:
        logger.exception('Studio Agent run failed run=%s', run_id)
        message = str(exc) if str(exc).startswith(('文字模型响应超时', 'LLM 流式服务错误 HTTP', 'LLM 回复未完整结束', 'LLM 未返回正文')) else '助手暂时无法完成，请检查权限和模型配置后重试'
        async with factory() as db:
            await finish_run(db, run_id, 'failed', ''.join(parts), {'type': 'error', 'code': 'agent_failed', 'message': message})
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
