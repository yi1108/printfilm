"""Persistence regressions use a disposable SQLite file, never the business DB."""
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import app.models_teams  # noqa: F401 - resolves the team foreign-key type

from app.models_printfilm_studio import PrintfilmStudioCanvasDocument, PrintfilmStudioWorkflowRun
from app.printfilm_studio.canvas.service import get_or_create, save


@pytest_asyncio.fixture
async def studio_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr("app.printfilm_studio.sharing.ensure_enabled", lambda: None)
    from app.models_drama import DramaProject
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'canvas.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(DramaProject.__table__.create)
        await connection.execute(DramaProject.__table__.insert().values(id=1, user_id=1, title="测试项目"))
        await connection.run_sync(PrintfilmStudioCanvasDocument.__table__.create)
        await connection.run_sync(PrintfilmStudioWorkflowRun.__table__.create)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stale_session_cannot_overwrite_saved_document(studio_sessions):
    project, user = SimpleNamespace(id=1, team_id=None), SimpleNamespace(id=1)
    async with studio_sessions() as first, studio_sessions() as stale:
        await get_or_create(first, project, user)
        await first.commit()
        cached = await get_or_create(stale, project, user)
        assert cached.document_version == 1
        saved = await save(first, project, user, {'nodes': [], 'marker': 'winner'}, 1)
        assert saved.document_version == 2
        with pytest.raises(HTTPException) as conflict:
            await save(stale, project, user, {'nodes': [], 'marker': 'stale'}, 1)
        assert conflict.value.status_code == 409
        await stale.rollback()
    async with studio_sessions() as reader:
        current = await get_or_create(reader, project, user)
        assert current.document_version == 2
        assert current.document['marker'] == 'winner'


@pytest.mark.asyncio
async def test_running_workflow_does_not_block_manual_canvas_save(studio_sessions):
    """后台生成不是人工编辑锁，节点修改仍按文档版本正常保存。"""
    project, user = SimpleNamespace(id=1, team_id=None), SimpleNamespace(id=1)
    async with studio_sessions() as db:
        await get_or_create(db, project, user)
        db.add(PrintfilmStudioWorkflowRun(project_id=1, user_id=1, status='running', plan={'ids': ['image']}))
        await db.commit()
        saved = await save(db, project, user, {'nodes': [], 'marker': '生成期间的人工编辑'}, 1)
        assert saved.document_version == 2
        assert saved.document['marker'] == '生成期间的人工编辑'


@pytest.mark.asyncio
async def test_invalid_document_returns_422_before_writing(studio_sessions):
    async with studio_sessions() as db:
        with pytest.raises(HTTPException) as invalid:
            await save(db, SimpleNamespace(id=1, team_id=None), SimpleNamespace(id=1), {'nodes': [{'id': 'a', 'position': {'x': float('inf')}}]}, 1)
        assert invalid.value.status_code == 422
        assert (await db.get(PrintfilmStudioCanvasDocument, 'missing')) is None


@pytest.mark.asyncio
async def test_session_access_rechecks_project_membership(monkeypatch):
    from app.printfilm_studio.agent import routes
    from unittest.mock import AsyncMock
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(user_id=1, project_id=5)))
    denied = AsyncMock(side_effect=HTTPException(status_code=403, detail='membership revoked'))
    monkeypatch.setattr(routes, 'get_project', denied)
    with pytest.raises(HTTPException) as error:
        await routes._session(db, 'session', SimpleNamespace(id=1))
    assert error.value.status_code == 403
    denied.assert_awaited_once()


@pytest.mark.asyncio
async def test_story_repair_endpoint_saves_once_and_rejects_stale_versions(studio_sessions):
    from app.printfilm_studio.canvas.routes import repair_story, StoryRepairRequest
    project, user = SimpleNamespace(id=1, team_id=None), SimpleNamespace(id=1)
    async with studio_sessions() as db:
        await get_or_create(db, project, user)
        await db.commit()
        await save(db, project, user, {'nodes': [{'id': 's', 'type': 'script', 'data': {'text': '场景一：桃园 - 日\n（桃花盛开）'}}], 'edges': []}, 1)
        result = await repair_story(StoryRepairRequest(script_node_id='s', expected_version=2), project, db, user)
        assert result['version'] == 3
        assert len([node for node in result['document']['nodes'] if node['type'] == 'scene']) == 1
        with pytest.raises(HTTPException) as conflict:
            await repair_story(StoryRepairRequest(script_node_id='s', expected_version=2), project, db, user)
        assert conflict.value.status_code == 409
        current = await get_or_create(db, project, user)
        assert current.document_version == 3
