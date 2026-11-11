import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import app.models_teams  # noqa: F401
from app.models import User
from app.models_tasks import TaskRun
from app.models_printfilm_studio import (
    PrintfilmStudioAgentEvent as Event, PrintfilmStudioAgentRun as Run,
    PrintfilmStudioAgentSession as Session, PrintfilmStudioAgentMessage as Message,
)
from app.printfilm_studio.agent import runs


@pytest_asyncio.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'runs.db').as_posix()}")
    async with engine.begin() as conn:
        for table in (User, Session, Run, Event, Message, TaskRun):
            await conn.run_sync(table.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(User(id=1, email='studio-test@example.test', hashed_password='not-a-real-login'))
        db.add(Session(id='s', project_id=1, user_id=1, status='idle'))
        await db.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_retry_reuses_run_and_concurrent_prompt_is_rejected(store):
    async with store() as db:
        run, created = await runs.reserve_run(db, 's', 'hello', 'request-1')
        assert created
        same, created = await runs.reserve_run(db, 's', 'hello', 'request-1')
        assert same.id == run.id and not created
        with pytest.raises(HTTPException) as error:
            await runs.reserve_run(db, 's', 'second', 'request-2')
        assert error.value.status_code == 409
        assert len((await db.scalars(select(Message))).all()) == 1


@pytest.mark.asyncio
async def test_reference_snapshot_survives_reload_and_idempotent_retry(store):
    from app.printfilm_studio.agent.conversation import messages_out
    from app.printfilm_studio.agent.references import node_reference, asset_reference
    node = {'id': 'image-1', 'type': 'image', 'data': {'label': '主角', 'mediaUrls': ['/first.png', '/chosen.png'], 'mediaIndex': 1}}
    reference = node_reference(node, [])
    assert reference['thumbnail'] == '/chosen.png'
    assert asset_reference(SimpleNamespace(id=8, name='视频', asset_type='video', cover='/poster.png', url='/clip.mp4'))['thumbnail'] == '/poster.png'
    text = node_reference({'id': 'script-1', 'type': 'script', 'data': {'text': '正文' * 200}}, [])
    assert text['kind'] == 'text' and len(text['text']) == 180
    async with store() as db:
        run, _ = await runs.reserve_run(db, 's', '请参考主角', 'reference-request', references=[reference])
        same, created = await runs.reserve_run(db, 's', '请参考主角', 'reference-request', references=[])
        assert same.id == run.id and not created
        await runs.finish_run(db, run.id, 'completed', '完成')
    node['data']['mediaUrls'] = ['/replacement.png']
    async with store() as db:
        messages = await messages_out(db, 's')
        assert messages[0]['metadata']['references'] == [reference]
        assert messages[0]['metadata']['references'][0]['thumbnail'] == '/chosen.png'


@pytest.mark.asyncio
async def test_durable_sequence_replay_after_reconnect(store):
    async with store() as db:
        run, _ = await runs.reserve_run(db, 's', 'hello', 'req')
        run_id = run.id
        await runs.append_event(db, run_id, {'type': 'message_delta', 'content': '你好'})
        await runs.finish_run(db, run_id, 'completed', '你好')
    # A new session represents reconnecting to a different HTTP worker.
    async with store() as db:
        events = await runs.read_events(db, run_id, after=2)
        assert [e['type'] for e in events] == ['message_delta', 'done']
        assert [e['sequence'] for e in events] == [3, 4]
        assert all(e['run_id'] == run_id for e in events)
        assert (await db.get(Session, 's')).status == 'completed'
        assert len((await db.scalars(select(Message))).all()) == 2


@pytest.mark.asyncio
async def test_expired_worker_fails_without_reexecuting_tools(store):
    async with store() as db:
        run, _ = await runs.reserve_run(db, 's', 'hello', 'req')
        run.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()
        assert await runs.expire_run(db, run.id)
        assert not await runs.expire_run(db, run.id)
        events = await runs.read_events(db, run.id, after=2)
        assert [e['type'] for e in events] == ['error', 'done']
        assert events[0]['code'] == 'run_interrupted'


@pytest.mark.asyncio
async def test_expired_stream_keeps_partial_reply_beyond_first_event_page(store):
    async with store() as db:
        run, _ = await runs.reserve_run(db, 's', 'hello', 'long-stream')
        pieces = [str(index) + '。' for index in range(215)]
        db.add_all([Event(run_id=run.id, sequence=index + 3,
            payload={'type': 'message_delta', 'content': part}) for index, part in enumerate(pieces)])
        run.next_sequence = len(pieces) + 3
        run.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()
        assert await runs.expire_run(db, run.id)
        message = await db.scalar(select(Message).where(Message.role == 'assistant'))
        assert message.content == ''.join(pieces)


@pytest.mark.asyncio
async def test_stop_interrupts_pending_model_call():
    from app.printfilm_studio.agent.runtime import iter_agent_turn
    stopped = False
    cancelled = asyncio.Event()
    async def complete(*args):
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()
    canvas = SimpleNamespace(load=AsyncMock(return_value=({'nodes': [], 'edges': []}, 1)))
    async def consume():
        return [event async for event in iter_agent_turn(view={}, canvas=canvas, prompt='x', complete=complete, stopped=lambda: stopped)]
    task = asyncio.create_task(consume())
    await asyncio.sleep(.02)
    stopped = True
    assert await asyncio.wait_for(task, timeout=2) == []
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_disconnecting_subscriber_keeps_execution_and_replays_events(store, monkeypatch):
    import json
    from app.printfilm_studio.agent import routes
    gate = asyncio.Event()
    calls = []
    async def turn(**kwargs):
        calls.append(kwargs['prompt'])
        yield {'type': 'tool_start', 'tool': 'read_canvas'}
        await gate.wait()
        yield {'type': 'message_delta', 'content': '已读取'}
    project = SimpleNamespace(id=1, team_id=None)
    monkeypatch.setattr(runs, 'iter_agent_turn', turn)
    monkeypatch.setattr(runs, 'get_project', AsyncMock(return_value=project))
    monkeypatch.setattr(runs, 'load_project_view', AsyncMock(return_value={}))
    monkeypatch.setattr(routes, 'get_project', AsyncMock(return_value=project))
    monkeypatch.setattr(routes, 'AsyncSessionLocal', store)
    monkeypatch.setattr(routes, 'ensure_enabled', lambda: None)
    async with store() as db:
        run, _ = await runs.reserve_run(db, 's', 'read once', 'request')
        run_id = run.id
    worker = asyncio.create_task(runs.execute_run(run_id, 's', 1, 'read once', {}, {}, factory=store))
    subscription = routes._subscribe('s', run_id, 1, {})
    assert json.loads(await anext(subscription))['sequence'] == 1
    await subscription.aclose()
    assert not worker.done()
    gate.set()
    await asyncio.wait_for(worker, timeout=5)
    replay = [json.loads(line) async for line in routes._subscribe('s', run_id, 1, {}, after=2)]
    assert [event['type'] for event in replay] == ['tool_start', 'message_delta', 'done']
    assert calls == ['read once']


@pytest.mark.asyncio
async def test_replay_endpoint_rechecks_owner_and_run_session(store, monkeypatch):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.printfilm_studio.agent import routes
    app = FastAPI(); app.include_router(routes.router)
    async def db_override():
        async with store() as db:
            yield db
    identity = SimpleNamespace(id=2)
    app.dependency_overrides[routes.get_db] = db_override
    app.dependency_overrides[routes.get_current_user] = lambda: identity
    monkeypatch.setattr(routes, 'ensure_enabled', lambda: None)
    monkeypatch.setattr(routes, 'get_project', AsyncMock(return_value=SimpleNamespace(id=1)))
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        response = await client.get('/printfilm-studio/agent/sessions/s/runs/r/events')
        assert response.status_code == 404
        identity.id = 1
        response = await client.get('/printfilm-studio/agent/sessions/s/runs/missing/events')
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_stop_uses_durable_flag_and_only_linked_tasks(store, monkeypatch):
    from app.services.tasks import service
    cancel = AsyncMock()
    monkeypatch.setattr(service, 'cancel_task_for_user', cancel)
    async with store() as db:
        run, _ = await runs.reserve_run(db, 's', 'hello', 'req')
        await runs.append_event(db, run.id, {'type': 'task_created', 'task_id': 'task-77', 'platform_task_id': 77})
        await runs.cancel_linked_tasks(db, run.id, await db.get(User, 1))
    assert cancel.await_count == 1
    assert cancel.call_args.args[2] == 77
