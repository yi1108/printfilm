from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.printfilm_studio.integration import generation_routes
from app.printfilm_studio.canvas import routes as canvas_routes
from app.api import tools


@pytest.mark.asyncio
async def test_image_estimate_checks_project_and_uses_generation_billing_plan(monkeypatch):
    from app.services.billing import estimates, settlement
    from app.services.media_models import planning
    from app.services import studio_generation
    project_access = AsyncMock(return_value=SimpleNamespace(id=12))
    monkeypatch.setattr(generation_routes, 'ensure_enabled', lambda: None)
    monkeypatch.setattr(generation_routes, 'get_project', project_access)
    monkeypatch.setattr(settlement, 'billing_active', lambda user: True)
    monkeypatch.setattr(studio_generation, 'validate_generation', lambda *args, **kwargs: 'image')
    prepare = AsyncMock()
    estimate = AsyncMock(return_value=180)
    monkeypatch.setattr(planning, 'prepare_task_media', prepare)
    monkeypatch.setattr(estimates, 'estimate_task_fen', estimate)
    db, user = SimpleNamespace(), SimpleNamespace(id=7)
    body = generation_routes.ImageEstimateRequest(model_id='seedream-5.0', resolution='2K', count=2)
    result = await generation_routes.estimate_image(12, body, db, user)
    assert result['estimate_yuan'] == 1.8
    task = prepare.call_args.args[1]
    assert task.task_type == 'tool_image'
    assert task.payload['pack'] == '2'
    assert estimate.call_args.args[1] is task
    project_access.side_effect = HTTPException(403, 'forbidden')
    estimate.reset_mock()
    with pytest.raises(HTTPException):
        await generation_routes.estimate_image(13, body, db, user)
    estimate.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_generation_only_accepts_queued_project_task(monkeypatch):
    from app.api import tasks
    cancel = AsyncMock()
    monkeypatch.setattr(tasks, 'cancel_task_run', cancel)
    task = SimpleNamespace(id=8, status='awaiting_poll', cancelable=False, requested_by=7)
    db = SimpleNamespace(scalar=AsyncMock(return_value=task))
    project, user = SimpleNamespace(id=12), SimpleNamespace(id=7)
    with pytest.raises(HTTPException) as error:
        await generation_routes.cancel_generation('task-8', project, db, user)
    assert error.value.status_code == 409
    cancel.assert_not_awaited()
    task.status = 'pending'
    await generation_routes.cancel_generation('task-8', project, db, user)
    assert task.cancelable is True
    cancel.assert_awaited_once_with(8, db, user)
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as error:
        await generation_routes.cancel_generation('task-9', project, db, user)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_project_generation_requires_project_membership_before_creating_task(monkeypatch):
    app = FastAPI(); app.include_router(generation_routes.router)
    db = SimpleNamespace(info={}, commit=AsyncMock(), rollback=AsyncMock())
    async def get_db():
        yield db
    app.dependency_overrides[generation_routes.get_db] = get_db
    app.dependency_overrides[generation_routes.get_current_user] = lambda: SimpleNamespace(id=7)
    project = SimpleNamespace(id=12, team_id=4)
    access = AsyncMock(side_effect=HTTPException(404, 'not a project member'))
    monkeypatch.setattr(canvas_routes, 'get_project', access)
    monkeypatch.setattr(canvas_routes, 'ensure_enabled', lambda: None)
    enqueue = AsyncMock(return_value={'kind': 'image', 'status': 'queued', 'urls': [], 'task_id': 'task-1'})
    monkeypatch.setattr(tools, 'enqueue_generation', enqueue)
    monkeypatch.setattr(tools, 'validate_generation', lambda *args: 'image')
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as client:
        response = await client.post('/printfilm-studio/projects/12/generations', data={'tool_id': 't2i', 'prompt': 'hello'})
        assert response.status_code == 404
        enqueue.assert_not_awaited()
        access.side_effect = None
        access.return_value = project
        response = await client.post('/printfilm-studio/projects/12/generations', data={'tool_id': 't2i', 'prompt': 'hello', 'node_id': 'node-output'})
        assert response.status_code == 200
        assert enqueue.call_args.kwargs['drama_project_id'] == 12
        assert enqueue.call_args.kwargs['params']['node_id'] == 'node-output'


@pytest.mark.asyncio
async def test_result_assets_are_idempotent_and_have_correct_media_kind(tmp_path):
    from app.models_drama import DramaAsset
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'assets.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(DramaAsset.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            task = SimpleNamespace(id=8, status='succeeded', result_payload={'urls': ['https://media.example.test/clip.mp4']})
            row = SimpleNamespace(urls=[], prompt='A scene', kind='video')
            first = await generation_routes.materialize_results(db, 1, task, row)
            await db.commit()
            second = await generation_routes.materialize_results(db, 1, task, row)
            assert first == second
            assets = (await db.scalars(select(DramaAsset))).all()
            assert len(assets) == 1
            assert assets[0].asset_type == 'video'
            assert assets[0].cover is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_agent_canvas_conflict_rolls_back_queued_media_task(monkeypatch):
    from app.printfilm_studio.integration.media import create_media_task
    from app.services import studio_generation
    db = SimpleNamespace(info={}, get=AsyncMock(return_value=SimpleNamespace(cancelable=False)), rollback=AsyncMock())
    canvas = SimpleNamespace(db=db, user=SimpleNamespace(id=1), project=SimpleNamespace(id=4, team_id=None), load=AsyncMock(return_value=({'nodes': [], 'edges': []}, 2)), save=AsyncMock(side_effect=HTTPException(409, 'conflict')))
    monkeypatch.setattr(studio_generation, 'enqueue_generation', AsyncMock(return_value={'platform_task_id': 12, 'task_id': 'task-12'}))
    with pytest.raises(HTTPException) as error:
        await create_media_task(canvas, 'image', 'hello')
    assert error.value.status_code == 409
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_image_reference_uses_actual_project_asset_file(monkeypatch, tmp_path):
    from PIL import Image
    from app.printfilm_studio.integration import generation_inputs
    from app.printfilm_studio.integration.media import create_media_task
    from app.services import studio_generation
    asset = SimpleNamespace(id=9, asset_type='image', url='https://storage.example.test/reference.png')
    db = SimpleNamespace(info={}, scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [asset])), get=AsyncMock(return_value=SimpleNamespace(cancelable=False)))
    doc = {'nodes': [{'id': 'source', 'type': 'image', 'position': {'x': 0, 'y': 0}, 'data': {'assetId': 9, 'mediaUrl': asset.url}}], 'edges': []}
    canvas = SimpleNamespace(db=db, user=SimpleNamespace(id=1), project=SimpleNamespace(id=4, team_id=None), load=AsyncMock(return_value=(doc, 2)), save=AsyncMock(return_value=3))
    async def read_file(_asset, path, _stopped): Image.new('RGB', (16, 16), 'blue').save(path)
    def save_file(_user, raw, _name):
        path = tmp_path / 'persistent.png'; path.write_bytes(raw); return path
    monkeypatch.setattr(generation_inputs, 'read_asset_file', read_file)
    monkeypatch.setattr(generation_inputs, 'save_upload', save_file)
    enqueue = AsyncMock(return_value={'platform_task_id': 12, 'task_id': 'task-12'})
    monkeypatch.setattr(studio_generation, 'enqueue_generation', enqueue)
    result = await create_media_task(canvas, 'image', 'edit this image', node_id='source', count=2)
    assert result['version'] == 3
    assert enqueue.call_args.kwargs['tool_id'] == 'i2i'
    assert enqueue.call_args.kwargs['params']['pack'] == '2'
    assert enqueue.call_args.kwargs['files'][0].read_bytes().startswith(b'\x89PNG')
    assert doc['edges'][-1]['source'] == 'source'
