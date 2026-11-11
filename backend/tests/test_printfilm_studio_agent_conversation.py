from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import User
from app.models_tasks import TaskRun
from app.models_printfilm_studio import PrintfilmStudioAgentSession as Session, PrintfilmStudioAgentMessage as Message, PrintfilmStudioAgentRun as Run, PrintfilmStudioAgentEvent as Event
from app.printfilm_studio.agent import runs, routes
from app.printfilm_studio.agent.conversation import change_history, messages_out


@pytest_asyncio.fixture
async def store(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "history.db"}')
    async with engine.begin() as conn:
        for model in (User, TaskRun, Session, Message, Run, Event):
            await conn.run_sync(model.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(User(id=1, email='history@example.test', hashed_password='test'))
        db.add(Session(id='s', project_id=1, user_id=1, title='镜头', status='idle'))
        await db.commit()
        run, _ = await runs.reserve_run(db, 's', '读取画布', 'req')
        await runs.append_event(db, run.id, {'type': 'tool_start', 'tool': 'read_canvas', 'call_id': '0', 'data': {}})
        await runs.append_event(db, run.id, {'type': 'tool_result', 'tool': 'read_canvas', 'call_id': '0', 'ok': True, 'data': {'nodes': 2}})
        await runs.finish_run(db, run.id, 'completed', '已读取')
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_review_proposal_survives_history_reload_and_branch(store):
    proposal = {'id': 'review-one', 'nodes': [{'id': 'text', 'before': None, 'after': {'id': 'text', 'type': 'text', 'data': {'text': '正文'}}}], 'edges': []}
    async with store() as db:
        run, _ = await runs.reserve_run(db, 's', '规划人物', 'review-request')
        await runs.append_event(db, run.id, {'type': 'proposal', 'data': proposal})
        await runs.finish_run(db, run.id, 'completed', '请应用这批改动')
        history = await messages_out(db, 's')
        assert history[-1]['metadata']['events'][0]['data'] == proposal
        branch = await change_history(db, 's', history[-1]['id'], 'branch', len(history))
        copied = await messages_out(db, branch)
        assert copied[-1]['metadata']['events'][0]['data'] == proposal


@pytest.mark.asyncio
async def test_history_recovers_tool_inputs_outputs_and_branch_keeps_trace(store):
    async with store() as db:
        before = await messages_out(db, 's')
        assert [e['type'] for e in before[1]['metadata']['events']] == ['tool_start', 'tool_result']
        branch = await change_history(db, 's', before[1]['id'], 'branch', 2)
        copied = await messages_out(db, branch)
        assert [m['content'] for m in copied] == ['读取画布', '已读取']
        assert copied[1]['metadata']['events'] == before[1]['metadata']['events']
        assert copied[1]['id'] != before[1]['id']
        assert len(await messages_out(db, 's')) == 2
        assert (await db.get(Session, branch)).project_id == 1


@pytest.mark.asyncio
async def test_edit_branch_excludes_edited_prompt_and_leaves_original_history(store):
    async with store() as db:
        before = await messages_out(db, 's')
        branch = await change_history(db, 's', before[0]['id'], 'edit_branch', 2)
        assert await messages_out(db, branch) == []
        assert len(await messages_out(db, 's')) == 2


@pytest.mark.asyncio
async def test_history_rejects_stale_client_and_active_run(store):
    async with store() as db:
        before = await messages_out(db, 's')
        with pytest.raises(HTTPException) as error:
            await change_history(db, 's', before[0]['id'], 'truncate', 1)
        assert error.value.status_code == 409
        await db.rollback()
        await runs.reserve_run(db, 's', '继续', 'next')
        with pytest.raises(HTTPException) as error:
            await change_history(db, 's', before[0]['id'], 'truncate', 3)
        assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_truncate_keeps_execution_audit_and_can_continue(store):
    async with store() as db:
        before = await messages_out(db, 's')
        await change_history(db, 's', before[1]['id'], 'truncate', 2)
        assert [m['content'] for m in await messages_out(db, 's')] == ['读取画布']
        assert len((await db.scalars(select(Run))).all()) == 1
        run, _ = await runs.reserve_run(db, 's', '新问题', 'next')
        await runs.finish_run(db, run.id, 'completed', '新回答')
        after = await messages_out(db, 's')
        assert [m['sequence'] for m in after] == [1, 2, 3]
        assert [m['content'] for m in after] == ['读取画布', '新问题', '新回答']
        assert not after[-1]['metadata']['events']


@pytest.mark.asyncio
async def test_empty_response_still_preserves_completed_tool_trace(store):
    async with store() as db:
        run, _ = await runs.reserve_run(db, 's', '操作', 'trace-only')
        await runs.append_event(db, run.id, {'type': 'tool_start', 'tool': 'read_canvas'})
        await runs.finish_run(db, run.id, 'cancelled')
        messages = await messages_out(db, 's')
        assert messages[-1]['role'] == 'assistant'
        assert messages[-1]['metadata']['events'][0]['tool'] == 'read_canvas'


@pytest.mark.asyncio
async def test_truncation_and_new_run_cannot_reuse_stale_history_token(store):
    async with store() as db:
        before = await messages_out(db, 's')
        await change_history(db, 's', before[1]['id'], 'truncate', 2, before[-1]['id'])
        # Same count, different suffix (e.g. another tab replaced the last response).
        db.add(Message(session_id='s', role='assistant', content='替代回复', sequence=2))
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await change_history(db, 's', before[0]['id'], 'truncate', 2, before[-1]['id'])
        assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_message_action_endpoint_rechecks_owner_project_and_message_scope(store, monkeypatch):
    app = FastAPI(); app.include_router(routes.router)
    identity = SimpleNamespace(id=2)
    async def connection():
        async with store() as db:
            yield db
    app.dependency_overrides[routes.get_db] = connection
    app.dependency_overrides[routes.get_current_user] = lambda: identity
    monkeypatch.setattr(routes, 'ensure_enabled', lambda: None)
    project = AsyncMock(return_value=SimpleNamespace(id=1))
    monkeypatch.setattr(routes, 'get_project', project)
    async with store() as db:
        message_id = (await messages_out(db, 's'))[0]['id']
        last_id = (await messages_out(db, 's'))[-1]['id']
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        payload = {'action': 'branch', 'expected_sequence': 2, 'expected_last_message_id': last_id}
        assert (await client.post(f'/printfilm-studio/agent/sessions/s/messages/{message_id}/actions', json=payload)).status_code == 404
        identity.id = 1
        project.side_effect = HTTPException(403, 'space mismatch')
        assert (await client.post(f'/printfilm-studio/agent/sessions/s/messages/{message_id}/actions', json=payload)).status_code == 403
        project.side_effect = None
        assert (await client.post('/printfilm-studio/agent/sessions/s/messages/missing/actions', json=payload)).status_code == 404
        response = await client.post(f'/printfilm-studio/agent/sessions/s/messages/{message_id}/actions', json=payload)
        assert response.status_code == 200
        assert response.json()['id'] != 's'
