"""Conversation history actions; none of these rewind canvas edits or media tasks."""
from __future__ import annotations

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from app.models_printfilm_studio import (
    PrintfilmStudioAgentSession as Session, PrintfilmStudioAgentMessage as Message,
    PrintfilmStudioAgentEvent as Event, PrintfilmStudioAgentRun as Run,
)

TRACE_TYPES = {'thinking', 'tool_start', 'tool_result', 'canvas_patch', 'task_created', 'error', 'proposal'}


async def messages_out(db, session_id):
    messages = list((await db.scalars(select(Message).where(Message.session_id == session_id).order_by(Message.sequence))).all())
    # Recover traces from pre-trace messages as well; one bounded-by-session query.
    rows = (await db.execute(select(Run.message_id, Event.payload).join(Event, Event.run_id == Run.id).where(Run.session_id == session_id, Run.status != 'running').order_by(Run.message_sequence, Event.sequence))).all()
    traces = {}
    for message_id, payload in rows:
        if payload.get('type') in TRACE_TYPES:
            traces.setdefault(message_id, []).append(payload)
    return [dict(id=m.id, role=m.role, content=m.content, sequence=m.sequence,
                 metadata={**(m.message_metadata or {}), 'events': traces.get(m.id, (m.message_metadata or {}).get('events', []))}) for m in messages]


async def change_history(db, session_id, message_id, action, expected_sequence, expected_last_message_id=None):
    # Serialize against reserve_run. Checking a previously loaded status alone races.
    claimed = await db.scalar(update(Session).where(Session.id == session_id, Session.status != 'running').values(status=Session.status).returning(Session.id))
    if not claimed:
        raise HTTPException(409, '请先停止当前执行，再修改对话历史')
    latest = int(await db.scalar(select(func.max(Message.sequence)).where(Message.session_id == session_id)) or 0)
    if latest != expected_sequence:
        raise HTTPException(409, '对话已更新，请重新打开会话后操作')
    latest_id = await db.scalar(select(Message.id).where(Message.session_id == session_id, Message.sequence == latest))
    if expected_last_message_id is not None and latest_id != expected_last_message_id:
        raise HTTPException(409, '对话内容已变化，请重新打开会话后操作')
    message = await db.get(Message, message_id)
    if not message or message.session_id != session_id:
        raise HTTPException(404, '消息不存在')
    if action == 'edit_branch' and message.role != 'user':
        raise HTTPException(422, '只能编辑用户消息')
    if action == 'truncate':
        await db.execute(delete(Message).where(Message.session_id == session_id, Message.sequence >= message.sequence))
        # Keep durable run records for auditing/idempotence. Their old replies must not
        # be resurrected by later runs or returned as the latest recoverable run.
        row = await db.get(Session, session_id)
        row.status = 'idle'
        await db.commit()
        return row.id
    row = await db.get(Session, session_id)
    branch = Session(project_id=row.project_id, team_id=row.team_id, user_id=row.user_id,
                     model_id=row.model_id, title=f'{row.title[:185]} · 分支', status='idle')
    db.add(branch)
    await db.flush()
    for item in await messages_out(db, session_id):
        if item['sequence'] > message.sequence or (action == 'edit_branch' and item['sequence'] == message.sequence):
            break
        metadata = deepcopy(item['metadata'])
        metadata.pop('run_id', None)
        db.add(Message(session_id=branch.id, role=item['role'], content=deepcopy(item['content']),
                       sequence=item['sequence'], message_metadata=metadata))
    await db.commit()
    return branch.id
