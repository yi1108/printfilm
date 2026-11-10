"""Canvas layout saves cannot replace media delivered by a generation worker.

All persistence in this module uses its own temporary SQLite file, never the
configured application database or the shared db_session fixture.
"""

from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.drama import canvas
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_drama import DramaAsset, DramaProject
from app.models_teams import Team, TeamMember
from app.schemas_drama import DramaCanvasSaveRequest


OLD_URL = "https://cdn.test/previous-portrait.mp4"
NEW_URL = "https://cdn.test/latest-landscape.mp4"
NEW_COVER = "https://cdn.test/latest-cover.jpg"
METADATA = {"source": "generated", "model_id": "seedance-2.5",
            "parameters": {"aspect_ratio": "16:9", "resolution": "1080p"}}


def stale_node(asset_id=1):
    return {"id": "asset-1", "type": "asset", "position": {"x": 42, "y": 73},
            "data": {"assetId": asset_id, "kind": "video", "label": "Edited title",
                     "mediaUrl": OLD_URL, "url": OLD_URL, "cover": OLD_URL,
                     "promptHint": "Edited prompt", "videoOptions": {"aspect_ratio": "16:9"}}}


@pytest.fixture
async def canvas_store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'canvas.sqlite3').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        for model in (User, Team, TeamMember, DramaProject, DramaAsset):
            await connection.run_sync(model.__table__.create)
    async with sessions() as db:
        user = User(email="canvas-owner@test.local", hashed_password="test")
        other = User(email="canvas-other@test.local", hashed_password="test")
        db.add_all([user, other])
        await db.flush()
        team = Team(name="Canvas team", owner_user_id=user.id)
        db.add(team)
        await db.flush()
        db.add(TeamMember(team_id=team.id, user_id=user.id, role="owner"))
        projects = [DramaProject(user_id=user.id, title="Personal", content={"notes": "keep"}),
                    DramaProject(user_id=user.id, team_id=team.id, title="Team"),
                    DramaProject(user_id=other.id, title="Other")]
        db.add_all(projects)
        await db.flush()
        assets = []
        for project in projects:
            asset = DramaAsset(project_id=project.id, type="video", asset_type="video",
                               name="Server title", url=NEW_URL, cover=NEW_COVER,
                               params={"media_metadata": deepcopy(METADATA),
                                       "generation": {"status": "done"}})
            db.add(asset)
            assets.append(asset)
        await db.commit()
    yield SimpleNamespace(sessions=sessions, user=user, projects=projects, assets=assets)
    await engine.dispose()


async def client_for(store):
    app = FastAPI()
    app.include_router(canvas.router)

    async def database():
        async with store.sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: store.user
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


@pytest.mark.asyncio
async def test_stale_layout_save_preserves_generated_media_and_normalizes_both_snapshots(canvas_store):
    store = canvas_store
    node = stale_node(store.assets[0].id)
    edges = [{"id": "link", "source": "asset-1", "target": "other"}]
    async with await client_for(store) as client:
        response = await client.post("/canvas", json={"project_id": store.projects[0].id,
                                                     "nodes": [node], "edges": edges})
    assert response.status_code == 200
    async with store.sessions() as db:
        asset = await db.get(DramaAsset, store.assets[0].id)
        project = await db.get(DramaProject, store.projects[0].id)
        assert (asset.url, asset.cover) == (NEW_URL, NEW_COVER)
        assert asset.params["media_metadata"] == METADATA
        assert asset.params["generation"] == {"status": "done"}
        assert asset.name == "Edited title"
        assert project.content["notes"] == "keep"
        assert project.content["canvas_edges"] == edges
        for saved in (project.content["canvas_nodes"][0], asset.params["canvas"]):
            assert saved["position"] == node["position"]
            assert saved["data"]["label"] == "Edited title"
            assert saved["data"]["promptHint"] == "Edited prompt"
            assert saved["data"]["videoOptions"] == node["data"]["videoOptions"]
            assert saved["data"]["mediaUrl"] == NEW_URL
            assert saved["data"]["url"] == NEW_URL
            assert saved["data"]["cover"] == NEW_COVER


@pytest.mark.asyncio
async def test_personal_get_uses_current_media_without_replacing_layout_or_unsaved_title(canvas_store):
    store = canvas_store
    node = stale_node(store.assets[0].id)
    async with store.sessions() as db:
        project = await db.get(DramaProject, store.projects[0].id)
        project.content = {"canvas_nodes": [node], "canvas_edges": []}
        await db.commit()
    async with await client_for(store) as client:
        response = await client.get(f"/canvas/{store.projects[0].id}")
    assert response.status_code == 200
    saved = response.json()["nodes"][0]
    assert saved["position"] == node["position"]
    assert saved["data"]["label"] == "Edited title"
    assert saved["data"]["promptHint"] == "Edited prompt"
    assert (saved["data"]["mediaUrl"], saved["data"]["url"], saved["data"]["cover"]) == (
        NEW_URL, NEW_URL, NEW_COVER)


@pytest.mark.asyncio
async def test_generation_completed_after_initial_load_is_not_overwritten_by_stale_orm(canvas_store, monkeypatch):
    store = canvas_store
    project_id, asset_id = store.projects[0].id, store.assets[0].id
    original = canvas.get_owned_drama_project
    initial_metadata = {"source": "generated", "parameters": {"aspect_ratio": "9:16"}}
    async with store.sessions() as db:
        asset = await db.get(DramaAsset, asset_id)
        asset.url, asset.cover = OLD_URL, OLD_URL
        asset.params = {"media_metadata": initial_metadata, "generation": {"status": "generating"}}
        await db.commit()

    async def finish_after_read(db, *args, **kwargs):
        project = await original(db, *args, **kwargs)
        assert project.assets[0].url == OLD_URL
        async with store.sessions() as worker:
            asset = await worker.get(DramaAsset, asset_id)
            asset.url, asset.cover = NEW_URL, NEW_COVER
            asset.params = {"media_metadata": deepcopy(METADATA), "generation": {"status": "done"}}
            await worker.commit()
        return project

    monkeypatch.setattr(canvas, "get_owned_drama_project", finish_after_read)
    async with store.sessions() as db:
        await canvas.save_canvas(DramaCanvasSaveRequest(project_id=project_id, nodes=[stale_node(asset_id)]),
                                 db=db, user=store.user)
    async with store.sessions() as db:
        asset = await db.get(DramaAsset, asset_id)
        assert (asset.url, asset.cover) == (NEW_URL, NEW_COVER)
        assert asset.params["media_metadata"] == METADATA
        assert asset.params["generation"] == {"status": "done"}


@pytest.mark.asyncio
async def test_team_save_keeps_asset_fields_authoritative_and_prompt_editable(canvas_store):
    store = canvas_store
    node = stale_node(store.assets[1].id)
    async with await client_for(store) as client:
        response = await client.post("/canvas", json={"project_id": store.projects[1].id, "nodes": [node]})
        loaded = await client.get(f"/canvas/{store.projects[1].id}")
    assert response.status_code == 200
    data = loaded.json()["nodes"][0]["data"]
    assert (data["mediaUrl"], data["cover"], data["label"]) == (NEW_URL, NEW_COVER, "Server title")
    assert data["promptHint"] == "Edited prompt"
    async with store.sessions() as db:
        asset = await db.get(DramaAsset, store.assets[1].id)
        assert (asset.url, asset.cover, asset.name) == (NEW_URL, NEW_COVER, "Server title")
        assert asset.params == {"media_metadata": METADATA, "generation": {"status": "done"}}


@pytest.mark.asyncio
async def test_new_node_initial_upload_keeps_existing_creation_behavior(canvas_store):
    store = canvas_store
    node = stale_node()
    node["data"].pop("assetId")
    node["data"].update(kind="image", mediaUrl="https://cdn.test/upload.png")
    async with await client_for(store) as client:
        response = await client.post("/canvas", json={"project_id": store.projects[0].id, "nodes": [node]})
    assert response.status_code == 200
    async with store.sessions() as db:
        asset = await db.scalar(select(DramaAsset).where(DramaAsset.project_id == store.projects[0].id,
                                                       DramaAsset.name == "Edited title"))
        assert asset.url == "https://cdn.test/upload.png"
        assert asset.cover == "https://cdn.test/upload.png"
        assert asset.params["canvas"]["data"]["promptHint"] == "Edited prompt"


@pytest.mark.asyncio
async def test_unknown_asset_id_does_not_modify_another_projects_asset(canvas_store):
    store = canvas_store
    node = stale_node(store.assets[2].id)
    async with await client_for(store) as client:
        response = await client.post("/canvas", json={"project_id": store.projects[0].id, "nodes": [node]})
    assert response.status_code == 200
    async with store.sessions() as db:
        foreign = await db.get(DramaAsset, store.assets[2].id)
        assert (foreign.url, foreign.cover, foreign.name) == (NEW_URL, NEW_COVER, "Server title")
        assert foreign.params == {"media_metadata": METADATA, "generation": {"status": "done"}}
        created = await db.scalar(select(DramaAsset).where(DramaAsset.project_id == store.projects[0].id,
                                                         DramaAsset.name == "Edited title"))
        assert created is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,url,cover", [("audio", "https://cdn.test/latest.mp3", None),
                                          ("image", "https://cdn.test/latest.png", "https://cdn.test/thumb.png"),
                                          ("video", None, None)])
async def test_existing_media_and_empty_values_remain_server_owned(canvas_store, kind, url, cover):
    store = canvas_store
    async with store.sessions() as db:
        asset = await db.get(DramaAsset, store.assets[0].id)
        asset.type, asset.asset_type, asset.url, asset.cover = kind, kind, url, cover
        await db.commit()
    node = stale_node(store.assets[0].id)
    node["data"]["kind"] = kind
    async with await client_for(store) as client:
        response = await client.post("/canvas", json={"project_id": store.projects[0].id, "nodes": [node]})
    assert response.status_code == 200
    async with store.sessions() as db:
        asset = await db.get(DramaAsset, store.assets[0].id)
        assert (asset.url, asset.cover) == (url, cover)
        data = asset.params["canvas"]["data"]
        assert (data["mediaUrl"], data["url"], data["cover"]) == (url, url, cover)
