from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.printfilm_studio.integration import assets


@pytest.mark.asyncio
@pytest.mark.parametrize('content_type,data', [('text/html', b'<script/>'), ('image/png', b'')])
async def test_invalid_upload_never_contacts_storage(content_type, data, monkeypatch):
    uploader = AsyncMock()
    monkeypatch.setattr(assets, 'run_in_threadpool', uploader)
    file = UploadFile(BytesIO(data), filename='file', headers=Headers({'content-type': content_type}))
    with pytest.raises(HTTPException) as error:
        await assets.upload_asset(AsyncMock(), SimpleNamespace(id=1), file)
    assert error.value.status_code == 422
    uploader.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_storage_returns_explicit_error(monkeypatch):
    monkeypatch.setattr(assets.oss, 'oss_enabled', lambda: False)
    file = UploadFile(BytesIO(b'png'), filename='image.png', headers=Headers({'content-type': 'image/png'}))
    with pytest.raises(HTTPException) as error:
        await assets.upload_asset(AsyncMock(), SimpleNamespace(id=1), file)
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_library_import_copies_asset_into_target_project(monkeypatch):
    source = SimpleNamespace(id=3, project_id=7, name='character', type='character', asset_type='image', url='https://example.com/image.png', cover=None, params={'tags': ['cast']})
    monkeypatch.setattr(assets, 'get_owned_asset', AsyncMock(return_value=source))
    added = []
    db = SimpleNamespace(get=AsyncMock(return_value=source), add=added.append, commit=AsyncMock(), refresh=AsyncMock())
    result = await assets.import_asset(db, SimpleNamespace(id=9), SimpleNamespace(id=1), 3)
    assert result.project_id == 9
    assert source.project_id == 7
    result.params['tags'].append('copy')
    assert source.params['tags'] == ['cast']
    assert added == [result]


@pytest.mark.asyncio
async def test_library_import_rejects_inaccessible_source(monkeypatch):
    monkeypatch.setattr(assets, 'get_owned_asset', AsyncMock(side_effect=HTTPException(404, 'not found')))
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await assets.import_asset(db, SimpleNamespace(id=9), SimpleNamespace(id=1), 3)
    assert error.value.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_requires_project_membership_before_any_upload(monkeypatch):
    from app.printfilm_studio.canvas import routes
    monkeypatch.setattr(routes, 'ensure_enabled', lambda: None)
    access = AsyncMock(side_effect=HTTPException(404, 'project membership removed'))
    monkeypatch.setattr(routes, 'get_project', access)
    with pytest.raises(HTTPException) as error:
        await routes.writable_project(9, AsyncMock(), SimpleNamespace(id=1), None, None, None)
    assert error.value.status_code == 404
    access.return_value = SimpleNamespace(id=9, team_id=2)
    access.side_effect = None
    assert (await routes.writable_project(9, AsyncMock(), SimpleNamespace(id=1), None, None, None)).id == 9
