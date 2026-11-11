from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.printfilm_studio.agent import routes
from app.printfilm_studio.agent.tools import validate_tool_input


@pytest.mark.asyncio
async def test_session_settings_model_validation_and_busy_guard(monkeypatch):
    row = SimpleNamespace(id='session', project_id=1, title='Old', model_id=None, status='idle', created_at=None, updated_at=None)
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(routes, 'ensure_enabled', lambda: None)
    monkeypatch.setattr(routes, '_session', AsyncMock(return_value=row))
    monkeypatch.setattr(routes, 'agent_config', AsyncMock(return_value={'models': [{'id': 'available'}]}))
    await routes.update_session('session', routes.SessionUpdate(title='New title', model_id='available'), db, None)
    assert row.title == 'New title' and row.model_id == 'available'
    with pytest.raises(HTTPException) as error:
        await routes.update_session('session', routes.SessionUpdate(model_id='unavailable'), db, None)
    assert error.value.status_code == 422
    row.status = 'running'
    with pytest.raises(HTTPException) as error:
        await routes.update_session('session', routes.SessionUpdate(title='Blocked'), db, None)
    assert error.value.status_code == 409
    assert row.title == 'New title'


@pytest.mark.asyncio
async def test_orphaned_legacy_session_recovers_without_restarting_tools(monkeypatch):
    row = SimpleNamespace(id='old', user_id=7, project_id=1, status='running', updated_at=datetime.now(UTC) - timedelta(days=1))
    db = SimpleNamespace(get=AsyncMock(return_value=row), commit=AsyncMock())
    monkeypatch.setattr(routes, 'get_project', AsyncMock())
    monkeypatch.setattr(routes.runs, 'latest_run', AsyncMock(return_value=None))
    assert (await routes._session(db, 'old', SimpleNamespace(id=7))).status == 'failed'
    db.commit.assert_awaited_once()
    with pytest.raises(HTTPException) as error:
        await routes._session(db, 'old', SimpleNamespace(id=8))
    assert error.value.status_code == 404


def test_agent_media_input_cannot_pass_wrong_types_or_nonfinite_values():
    with pytest.raises(ValueError): validate_tool_input('edit_media', {'operation': 'speed', 'speed': float('nan')})
    with pytest.raises(ValueError): validate_tool_input('attach_asset_to_node', {'node_id': 'a', 'asset_id': True})
    with pytest.raises(ValueError): validate_tool_input('create_image_task', {'prompt': ''})
