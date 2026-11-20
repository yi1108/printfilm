"""Studio integration tests: real SQL and lifecycle, isolated local database, no providers."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import ToolRun, User
from app.models import UsageEvent
from app.models_tasks import TaskRun, TaskStep
from PIL import Image
from app.services import studio_generation as generation
from app.services.tasks import executor, scheduler
from app.services.tasks.queues import task_queue


@pytest.fixture
async def studio(monkeypatch):
    # Register FKs without starting the API or connecting to its configured database.
    import app.main  # noqa: F401
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(generation, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(executor, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(get_settings(), "billing_enabled", False)
    monkeypatch.setattr(generation, "ensure_public_urls", lambda urls: list(urls or []))
    async with sessions() as db:
        user = User(email="studio@example.test", hashed_password="test", balance_fen=100000)
        other = User(email="other@example.test", hashed_password="test", balance_fen=100000)
        db.add_all([user, other])
        await db.commit()
    yield sessions, user, other
    await engine.dispose()


@pytest.mark.parametrize("kind,payload,queue", [
    ("script_summary", {}, "text"), ("voice_synthesis", {}, "text"), ("tool_audio", {}, "text"),
    ("asset_image", {}, "image"), ("tool_image", {}, "image"), ("shot_regen_image", {}, "image"),
    ("fragment_video", {}, "video"), ("asset_video", {}, "video"),
    ("project_pipeline", {"phase": "script"}, "text"), ("project_pipeline", {"phase": "assets"}, "image"),
    ("project_pipeline", {"phase": "videos"}, "video"),
])
def test_queue_routing(kind, payload, queue):
    assert task_queue(kind, payload) == queue


async def enqueue(sessions, user, tool_id="t2i"):
    async with sessions() as db:
        data = await generation.enqueue_generation(db, user, tool_id=tool_id, prompt="A sunny forest",
            params={"duration": "5s", "voice": "narrator_calm"}, files=[])
        await db.commit()
    return data


async def test_submission_is_durable_before_generation(studio, monkeypatch):
    sessions, user, _ = studio
    provider = AsyncMock()
    monkeypatch.setattr(generation, "run_image_tool", provider)
    data = await enqueue(sessions, user)
    async with sessions() as db:
        task = await db.get(TaskRun, data["platform_task_id"])
        row = await db.get(ToolRun, data["run_id"])
        assert task.queue_type == "image" and task.status == "pending"
        assert task.next_action_at is not None
        assert row.task_id == f"task-{task.id}"
        assert row.params["billing_task_id"] == task.id
        assert (await db.execute(select(TaskStep).where(TaskStep.task_id == task.id))).scalar_one()
    provider.assert_not_awaited()


async def test_image_execution_uses_one_task_and_reuses_saved_result(studio, monkeypatch):
    sessions, user, _ = studio
    provider = AsyncMock(return_value={"kind": "image", "urls": ["https://cdn.test/image.png"], "status": "succeeded"})
    monkeypatch.setattr(generation, "run_image_tool", provider)
    data = await enqueue(sessions, user)
    await executor.execute_task_run(data["platform_task_id"])
    async with sessions() as db:
        row = await db.get(ToolRun, data["run_id"])
        task = await generation.sync_generation_record(db, row)
        assert task.status == row.status == "succeeded"
        assert row.urls == ["https://cdn.test/image.png"]
        assert task.progress_percent == 100 and task.finished_at is not None
        assert len((await db.execute(select(TaskRun))).scalars().all()) == 1
        await generation.execute_generation(task)
    provider.assert_awaited_once()


async def test_audio_runs_on_text_queue_and_returns_audio(studio, monkeypatch):
    sessions, user, _ = studio
    tts = AsyncMock(return_value="https://cdn.test/narration.mp3")
    monkeypatch.setattr("app.services.ark.get_ark", lambda: SimpleNamespace(tts=tts))
    usage = AsyncMock()
    monkeypatch.setattr("app.services.billing.record_line", usage)
    data = await enqueue(sessions, user, "audio")
    await executor.execute_task_run(data["platform_task_id"])
    async with sessions() as db:
        row = await db.get(ToolRun, data["run_id"])
        task = await generation.sync_generation_record(db, row)
        assert task.queue_type == "text" and row.status == "succeeded"
        assert row.urls == ["https://cdn.test/narration.mp3"]
    assert tts.await_args.kwargs["shot_no"] == data["run_id"]
    usage.assert_awaited_once()


async def test_video_resumes_existing_provider_id_and_polls_without_billing(studio, monkeypatch):
    sessions, user, _ = studio
    submit = AsyncMock(return_value={"task_id": "upstream-video-123", "preview_url": "https://cdn.test/frame.png"})
    poll = AsyncMock(return_value={"status": "succeeded", "kind": "video", "urls": ["https://cdn.test/movie.mp4"], "usage": {"total_tokens": 100}})
    usage = AsyncMock()
    monkeypatch.setattr(generation, "start_video_tool", submit)
    monkeypatch.setattr(generation, "poll_video_task", poll)
    monkeypatch.setattr("app.services.drama.billing_util.record_seedance_video_usage", usage)
    data = await enqueue(sessions, user, "t2v")
    task_id = data["platform_task_id"]
    await executor.execute_task_run(task_id)
    async with sessions() as db:
        task = await db.get(TaskRun, task_id)
        assert task.status == "awaiting_poll" and task.provider_task_id == "upstream-video-123"
        await generation.execute_generation(task)
    submit.assert_awaited_once()
    await generation.poll_generation_video(task_id)
    await generation.poll_generation_video(task_id)
    async with sessions() as db:
        row = await db.get(ToolRun, data["run_id"])
        task = await db.get(TaskRun, task_id)
        assert row.status == task.status == "succeeded"
        assert row.urls == ["https://cdn.test/movie.mp4"]
        assert task.provider_status == "succeeded"
    poll.assert_awaited_once()
    usage.assert_awaited_once()


async def test_failed_generation_remains_visible_in_history(studio, monkeypatch):
    sessions, user, _ = studio
    monkeypatch.setattr(generation, "run_image_tool", AsyncMock(side_effect=RuntimeError("provider unavailable")))
    data = await enqueue(sessions, user)
    await executor.execute_task_run(data["platform_task_id"])
    async with sessions() as db:
        row = await db.get(ToolRun, data["run_id"])
        await generation.sync_generation_record(db, row)
        assert row.status == "failed" and "provider unavailable" in row.error


async def test_full_image_lane_does_not_block_text_or_video(studio, monkeypatch):
    sessions, user, _ = studio
    settings = get_settings()
    for queue in ("text", "image", "video"):
        monkeypatch.setattr(settings, f"task_queue_{queue}_concurrency", 1)
    monkeypatch.setattr(settings, "task_user_max_concurrency", 1)
    monkeypatch.setattr(scheduler, "_running_jobs", {})
    monkeypatch.setattr(scheduler, "_running_queues", {})
    monkeypatch.setattr(scheduler, "_cancel_jobs", {})
    monkeypatch.setattr(scheduler, "_run_one", AsyncMock())
    await enqueue(sessions, user, "t2i")
    await enqueue(sessions, user, "t2i")
    await enqueue(sessions, user, "audio")
    await enqueue(sessions, user, "t2v")
    await scheduler._tick()
    await asyncio.sleep(0)
    async with sessions() as db:
        rows = (await db.execute(select(TaskRun))).scalars().all()
        assert sorted(task.queue_type for task in rows if task.status == "leased") == ["image", "text", "video"]
        assert sum(task.status == "pending" for task in rows) == 1


async def test_balance_failure_before_provider_is_exposed(studio, monkeypatch):
    sessions, user, _ = studio
    data = await enqueue(sessions, user)
    provider = AsyncMock()
    monkeypatch.setattr(generation, "run_image_tool", provider)
    monkeypatch.setattr(executor, "freeze_for_task", AsyncMock(side_effect=ValueError("insufficient balance")))
    await executor.execute_task_run(data["platform_task_id"])
    async with sessions() as db:
        row = await db.get(ToolRun, data["run_id"])
        task = await generation.sync_generation_record(db, row)
        assert task.error_code == "insufficient_balance" and row.status == "failed"
    provider.assert_not_awaited()


async def test_generation_freezes_and_settles_one_task_once(studio, monkeypatch):
    from app.services.billing import record_line
    sessions, user, _ = studio
    monkeypatch.setattr(get_settings(), "billing_enabled", True)
    async def provider(db, owner, **_kwargs):
        await record_line(db, user_id=owner.id, billing_key="seedream", model="test-image", tokens=45000,
                          estimated=True, domain="studio")
        return {"kind": "image", "status": "succeeded", "urls": ["https://cdn.test/paid.png"]}
    generate = AsyncMock(side_effect=provider)
    monkeypatch.setattr(generation, "run_image_tool", generate)
    data = await enqueue(sessions, user)
    await executor.execute_task_run(data["platform_task_id"])
    async with sessions() as db:
        task = await db.get(TaskRun, data["platform_task_id"])
        owner = await db.get(User, user.id)
        assert task.billing_status == "settled"
        assert owner.frozen_fen == 0
        assert owner.balance_fen == 100000 - task.billing_charged_fen
        await generation.execute_generation(task)
        events = (await db.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))).scalars().all()
        assert len(events) == 1
    generate.assert_awaited_once()


async def test_history_filters_counts_provider_id_and_ownership(studio):
    from app.api.tools import router
    sessions, user, other = studio
    first = await enqueue(sessions, user)
    await enqueue(sessions, user, "audio")
    hidden = await enqueue(sessions, other)
    async with sessions() as db:
        task = await db.get(TaskRun, first["platform_task_id"])
        task.status = "succeeded"
        task.provider_task_id = "find-upstream-id"
        await db.commit()
    api = FastAPI()
    api.include_router(router, prefix="/api")
    api.dependency_overrides[get_current_user] = lambda: user
    async def database():
        async with sessions() as db:
            yield db
    api.dependency_overrides[get_db] = database
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
        result = (await client.get("/api/tools/runs?kind=image&status=succeeded&task_id=find-upstream-id")).json()
        assert result["total"] == 1 and result["counts"] == {"succeeded": 1, "all": 1}
        assert result["items"][0]["platform_task_id"] == first["platform_task_id"]
        assert "file_paths" not in result["items"][0]["params"]
        assert (await client.get(f"/api/tools/tasks/{hidden['task_id']}")).status_code == 404
        assert (await client.get(f"/api/tools/runs/{hidden['run_id']}")).status_code == 404
        assert (await client.get("/api/tools/runs?kind=unsupported")).status_code == 422
        assert (await client.get("/api/tools/runs?created_from=2026-10-22T00:00:00Z&created_to=2026-10-20T00:00:00Z")).status_code == 400


async def test_live_remote_lease_is_not_recovered(studio, monkeypatch):
    sessions, user, _ = studio
    data = await enqueue(sessions, user)
    async with sessions() as db:
        task = await db.get(TaskRun, data["platform_task_id"])
        task.status = "running"
        task.updated_at = datetime.now(UTC) - timedelta(minutes=20)
        task.lease_until = datetime.now(UTC) + timedelta(minutes=2)
        await db.commit()
    monkeypatch.setattr(scheduler, "_running_jobs", {})
    assert await scheduler.recover_orphaned_tasks() == 0
    async with sessions() as db:
        task = await db.get(TaskRun, data["platform_task_id"])
        task.lease_until = datetime.now(UTC) - timedelta(minutes=1)
        task.updated_at = datetime.now(UTC) - timedelta(minutes=20)
        await db.commit()
    assert await scheduler.recover_orphaned_tasks() == 1


@pytest.fixture
async def studio_api(studio, monkeypatch, tmp_path):
    from app.api.tools import router
    from app.printfilm_studio.integration.generation_routes import router as canvas_router
    from app.services import studio_tools
    sessions, user, _ = studio
    api = FastAPI()
    api.include_router(router, prefix="/api")
    api.include_router(canvas_router, prefix="/api")
    api.dependency_overrides[get_current_user] = lambda: user
    async def database():
        async with sessions() as db:
            yield db
    api.dependency_overrides[get_db] = database
    monkeypatch.setattr(studio_tools, "tools_dir", lambda _user_id: tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
        yield client


async def add_reference_asset(sessions, user, *, kind="image", name="Reference", team_id=None, url=None, cover=None):
    from app.models_drama import DramaAsset, DramaProject
    async with sessions() as db:
        project = DramaProject(user_id=user.id, title="References", team_id=team_id)
        db.add(project)
        await db.flush()
        asset = DramaAsset(project_id=project.id, type=kind, asset_type="image", name=name,
                           url=url, cover=cover)
        db.add(asset)
        await db.commit()
    return asset


def video_request(**overrides):
    return {"tool_id": "t2v", "model_id": "seedance-2.0-fast", "video_mode": "text_to_video",
            "prompt": "A sunny forest", "duration": "6s", "resolution": "720p", "ratio": "16:9",
            "references": [], **overrides}


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (16, 16), "green").save(output, "PNG")
    return output.getvalue()


async def test_reference_library_filters_media_and_personal_ownership(studio, studio_api):
    sessions, user, other = studio
    image = await add_reference_asset(sessions, user, kind="character", name="Alice", cover="https://cdn.test/alice.png")
    video = await add_reference_asset(sessions, user, kind="video", name="Forest", url="https://cdn.test/forest.mp4", cover="https://cdn.test/forest.jpg")
    voice = await add_reference_asset(sessions, user, kind="voice", name="Narrator", url="https://cdn.test/narrator.mp3")
    await add_reference_asset(sessions, user, kind="voice", name="No recording", cover="https://cdn.test/voice-cover.png")
    await add_reference_asset(sessions, other, kind="character", cover="https://cdn.test/private.png")
    await add_reference_asset(sessions, user, kind="character", team_id=987, cover="https://cdn.test/team.png")
    result = (await studio_api.get("/api/tools/reference-assets?page_size=2")).json()
    assert result["total"] == 3 and len(result["items"]) == 2
    for kind, asset in (("image", image), ("video", video), ("audio", voice)):
        response = await studio_api.get(f"/api/tools/reference-assets?kind={kind}")
        assert response.status_code == 200
        assert [(item["id"], item["media_kind"]) for item in response.json()["items"]] == [(asset.id, kind)]
    searched = (await studio_api.get("/api/tools/reference-assets?q=Alice")).json()
    assert searched["total"] == 1 and searched["items"][0]["id"] == image.id


async def test_text_video_has_no_helper_image_and_preserves_selected_settings(studio, studio_api, monkeypatch):
    from app.services import studio_tools
    sessions, _, _ = studio
    create = AsyncMock(return_value="text-provider-task")
    image = AsyncMock()
    monkeypatch.setattr(studio_tools, "get_ark", lambda: SimpleNamespace(gen_video_seedance_body=create, gen_image=image))
    request = video_request()
    response = await studio_api.post("/api/tools/run", data={**request, "references": json.dumps(request["references"])})
    assert response.status_code == 200
    task_id = response.json()["platform_task_id"]
    await executor.execute_task_run(task_id)
    async with sessions() as db:
        task = await db.get(TaskRun, task_id)
        assert task.status == "awaiting_poll"
        assert len(task.billing_snapshot["items"]) == 1
        assert task.billing_snapshot["items"][0]["capability"] == "video"
        assert not task.billing_snapshot["items"][0]["params"]["reference_images"]
    body = create.await_args.args[0]
    assert body["model"] == "seedance-2.0-fast" and body["resolution"] == "720p"
    assert body["duration"] == 6 and body["ratio"] == "16:9"
    assert body["content"] == [{"type": "text", "text": request["prompt"]}]
    image.assert_not_awaited()


async def test_seedance_prompt_limits_and_full_submission(studio_api, monkeypatch):
    from app.services import studio_tools
    from app.services.tasks.generation_metadata import submitted_generation_params
    from app.services.tokenfree_video import prepare_video_create_body
    from app.services.upstream_sanitize import sanitize_upstream_value

    create = AsyncMock(return_value="long-prompt-provider-task")
    monkeypatch.setattr(studio_tools, "get_ark", lambda: SimpleNamespace(gen_video_seedance_body=create))
    prompt = "镜" * 14_996 + "尾部标记"
    request = video_request(model_id="seedance-2.5", prompt=prompt)
    quote = await studio_api.post("/api/tools/estimate", json=request)
    assert quote.status_code == 200
    response = await studio_api.post("/api/tools/run", files={
        key: (None, json.dumps(value) if key == "references" else value)
        for key, value in request.items()
    })
    assert response.status_code == 200
    await executor.execute_task_run(response.json()["platform_task_id"])
    body = prepare_video_create_body(create.await_args.args[0])
    assert body["prompt"] == prompt
    assert submitted_generation_params(sanitize_upstream_value(body))["prompt"] == prompt
    record = await studio_api.get(f"/api/tools/runs/{response.json()['run_id']}")
    assert record.json()["prompt"] == prompt

    too_long = await studio_api.post("/api/tools/run", data={**request, "references": "[]", "prompt": prompt + "多"})
    assert too_long.status_code == 422
    for model in ("seedance-2.0", "seedance-2.0-fast"):
        quote = await studio_api.post("/api/tools/estimate", json=video_request(model_id=model, prompt=prompt[:7000]))
        assert quote.status_code == 200
        rejected = await studio_api.post("/api/tools/estimate", json=video_request(model_id=model, prompt=prompt[:7001]))
        assert rejected.status_code in (400, 422)
        assert "7000" in rejected.json()["detail"]


async def test_seedance_25_accepts_fifty_configured_references(studio_api, monkeypatch):
    from collections import Counter
    from app.services import studio_tools
    from app.services.model_settings import get_routing_snapshot
    from app.services.tokenfree_video import prepare_video_create_body

    monkeypatch.setitem(get_routing_snapshot().media_reference_limits, "seedance-2.5", {
        "images": 30, "videos": 10, "audios": 10,
    })
    create = AsyncMock(return_value="fifty-references-provider-task")
    monkeypatch.setattr(studio_tools, "get_ark", lambda: SimpleNamespace(gen_video_seedance_body=create))
    monkeypatch.setattr(studio_tools, "publish_public", lambda path: f"https://cdn.test/{path.name}")
    uploads = (
        [("image", "png", "image/png", png_bytes())] * 30
        + [("video", "mp4", "video/mp4", b"\x00\x00\x00\x14ftypisom")] * 10
        + [("audio", "wav", "audio/wav", b"RIFF\x00\x00\x00\x00WAVE")] * 10
    )
    refs = [{"file_index": index, "role": f"reference_{kind}"} for index, (kind, *_rest) in enumerate(uploads)]
    request = video_request(model_id="seedance-2.5", video_mode="omni_reference", references=refs)
    quote = await studio_api.post("/api/tools/estimate", json=request)
    assert quote.status_code == 200, quote.text
    response = await studio_api.post("/api/tools/run", data={**request, "references": json.dumps(refs)}, files=[
        ("files", (f"ref-{index}.{suffix}", raw, mime))
        for index, (_kind, suffix, mime, raw) in enumerate(uploads)
    ])
    assert response.status_code == 200, response.text
    await executor.execute_task_run(response.json()["platform_task_id"])
    body = prepare_video_create_body(create.await_args.args[0])
    assert Counter(item["role"] for item in body["metadata"]["content"]) == {
        "reference_image": 30, "reference_video": 10, "reference_audio": 10,
    }
    rejected = await studio_api.post("/api/tools/estimate", json={
        **request, "references": refs + [{"role": "reference_image", "asset_id": 99}],
    })
    assert rejected.status_code == 422


async def test_frame_mode_combines_upload_and_library_asset(studio, studio_api, monkeypatch):
    from app.services import studio_tools
    sessions, user, _ = studio
    last = await add_reference_asset(sessions, user, kind="scene", cover="https://cdn.test/end.png")
    refs = [{"role": "first_frame", "file_index": 0}, {"role": "last_frame", "asset_id": last.id}]
    create = AsyncMock(return_value="frame-provider-task")
    monkeypatch.setattr(studio_tools, "get_ark", lambda: SimpleNamespace(gen_video_seedance_body=create))
    monkeypatch.setattr(studio_tools, "publish_public", lambda _path: "https://cdn.test/start.png")
    response = await studio_api.post("/api/tools/run", data={**video_request(video_mode="first_last_frame"), "references": json.dumps(refs)},
                                     files=[("files", ("start.png", png_bytes(), "image/png"))])
    assert response.status_code == 200, response.text
    await executor.execute_task_run(response.json()["platform_task_id"])
    content = create.await_args.args[0]["content"]
    assert [(item["role"], item["image_url"]["url"]) for item in content if item["type"] == "image_url"] == [
        ("first_frame", "https://cdn.test/start.png"), ("last_frame", "https://cdn.test/end.png")]
    history = (await studio_api.get(f"/api/tools/runs/{response.json()['run_id']}")).json()
    assert history["params"]["references"] == refs
    assert "first_frame" not in history["params"] and "file_paths" not in history["params"]


async def test_omni_mode_keeps_all_media_roles(studio, studio_api, monkeypatch):
    from app.services import studio_tools
    sessions, user, _ = studio
    image = await add_reference_asset(sessions, user, kind="prop", url="https://cdn.test/item.png")
    video = await add_reference_asset(sessions, user, kind="video", url="https://cdn.test/motion.mp4")
    audio = await add_reference_asset(sessions, user, kind="audio", url="https://cdn.test/voice.wav")
    refs = [{"role": role, "asset_id": asset.id} for role, asset in (
        ("reference_image", image), ("reference_video", video), ("reference_audio", audio))]
    create = AsyncMock(return_value="omni-provider-task")
    monkeypatch.setattr(studio_tools, "get_ark", lambda: SimpleNamespace(gen_video_seedance_body=create))
    response = await studio_api.post("/api/tools/run", data={**video_request(video_mode="omni_reference"), "references": json.dumps(refs)})
    assert response.status_code == 200, response.text
    await executor.execute_task_run(response.json()["platform_task_id"])
    content = create.await_args.args[0]["content"]
    assert {item.get("role") for item in content if item["type"] != "text"} == {"reference_image", "reference_video", "reference_audio"}


@pytest.mark.parametrize("mode,refs", [
    ("text_to_video", [{"role": "reference_image", "file_index": 0}]),
    ("first_last_frame", [{"role": "last_frame", "file_index": 0}]),
    ("omni_reference", []),
    ("omni_reference", [{"role": "reference_image", "url": "http://127.0.0.1/private"}]),
    ("omni_reference", [{"role": "reference_image", "file_index": 0, "asset_id": 1}]),
])
async def test_invalid_reference_sources_or_modes_are_rejected(studio_api, mode, refs):
    response = await studio_api.post("/api/tools/run", data={**video_request(video_mode=mode), "references": json.dumps(refs)})
    assert response.status_code == 400


async def test_reference_ids_cannot_access_other_users_or_teams(studio, studio_api):
    sessions, user, other = studio
    foreign = await add_reference_asset(sessions, other, kind="image", url="https://cdn.test/private.png")
    team = await add_reference_asset(sessions, user, kind="image", team_id=123, url="https://cdn.test/team.png")
    for asset in (foreign, team):
        request = video_request(video_mode="first_last_frame", references=[{"role": "first_frame", "asset_id": asset.id}])
        assert (await studio_api.post("/api/tools/estimate", json=request)).status_code == 400
        response = await studio_api.post("/api/tools/run", data={**request, "references": json.dumps(request["references"])})
        assert response.status_code == 400


async def test_canvas_generation_uses_project_asset_without_upload(studio, studio_api, monkeypatch):
    from app.services import studio_tools

    monkeypatch.setattr(get_settings(), "printfilm_studio_enabled", True)
    sessions, user, other = studio
    own = await add_reference_asset(sessions, user, kind="image", url="https://cdn.test/scene.png")
    unrelated = await add_reference_asset(sessions, user, kind="image", url="https://cdn.test/other-project.png")
    foreign = await add_reference_asset(sessions, other, kind="image", url="https://cdn.test/private.png")
    create = AsyncMock(return_value="existing-asset-provider-task")
    monkeypatch.setattr(studio_tools, "get_ark", lambda: SimpleNamespace(gen_video_seedance_body=create))
    path = f"/api/printfilm-studio/projects/{own.project_id}/generations"
    request = video_request(video_mode="omni_reference")
    for asset, expected_status in [(unrelated, 400), (foreign, 400), (own, 200)]:
        response = await studio_api.post(path, files={
            **{key: (None, value) for key, value in request.items() if key != "references"},
            "references": (None, json.dumps([{"role": "reference_image", "asset_id": asset.id}])),
        })
        assert response.status_code == expected_status, response.text
    await executor.execute_task_run(response.json()["platform_task_id"])
    assert create.await_args.args[0]["content"][-1] == {
        "type": "image_url", "image_url": {"url": own.url}, "role": "reference_image",
    }


async def test_upload_role_and_file_content_are_validated(studio_api):
    refs = [{"role": "reference_video", "file_index": 0}]
    response = await studio_api.post("/api/tools/run", data={**video_request(video_mode="omni_reference"), "references": json.dumps(refs)},
                                     files=[("files", ("reference.mp4", b"not a video", "video/mp4"))])
    assert response.status_code == 400
    refs = [{"role": "reference_audio", "file_index": 0}]
    response = await studio_api.post("/api/tools/run", data={**video_request(video_mode="omni_reference"), "references": json.dumps(refs)},
                                     files=[("files", ("image.png", png_bytes(), "image/png"))])
    assert response.status_code == 400


async def test_omni_uploads_accept_video_audio_and_images_without_dropping_any(studio, studio_api, monkeypatch):
    from app.services import studio_tools
    import wave
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 16000)
    # A media container header is enough for admission; the provider remains mocked.
    files = [("files", ("image.png", png_bytes(), "image/png")),
             ("files", ("motion.mp4", b"\0\0\0\x18ftypmp42" + b"\0" * 20, "video/mp4")),
             ("files", ("sound.wav", output.getvalue(), "audio/wav"))]
    refs = [{"role": role, "file_index": index} for index, role in enumerate(
        ("reference_image", "reference_video", "reference_audio"))]
    create = AsyncMock(return_value="uploaded-omni-provider-task")
    monkeypatch.setattr(studio_tools, "get_ark", lambda: SimpleNamespace(gen_video_seedance_body=create))
    monkeypatch.setattr(studio_tools, "publish_public", lambda path: f"https://cdn.test/{path.name}")
    response = await studio_api.post("/api/tools/run", data={**video_request(video_mode="omni_reference"), "references": json.dumps(refs)}, files=files)
    assert response.status_code == 200, response.text
    await executor.execute_task_run(response.json()["platform_task_id"])
    content = create.await_args.args[0]["content"]
    assert [item.get("role") for item in content if item["type"] != "text"] == [
        "reference_image", "reference_audio", "reference_video"]


async def test_estimate_empty_prompt_matches_admission_and_checks_price_version(studio, studio_api, monkeypatch):
    from app.models_settings import AppSettings, MediaPriceVersion
    sessions, user, _ = studio
    monkeypatch.setattr(get_settings(), "billing_enabled", True)
    async with sessions() as db:
        version = MediaPriceVersion(prices={"seedance-2.0-fast": {"720p": "0.2000"}}, created_by=user.id)
        db.add(version)
        await db.flush()
        db.add(AppSettings(id="media_pricing", config_json={"active_version": version.id, "enabled": True}))
        await db.commit()
    response = await studio_api.post("/api/tools/estimate", json=video_request(prompt=""))
    assert response.status_code == 200, response.text
    quote = response.json()
    assert quote["estimate_fen"] == 120 and quote["estimate_yuan"] == 1.2
    assert quote["billing_mode"] == "fixed_media" and quote["billing_enabled"]
    assert quote["price_version"] == version.id and len(quote["items"]) == 1
    request = {**video_request(), "references": "[]", "price_version": str(version.id)}
    response = await studio_api.post("/api/tools/run", data=request)
    assert response.status_code == 200, response.text
    async with sessions() as db:
        task = await db.get(TaskRun, response.json()["platform_task_id"])
        assert task.billing_estimate_fen == quote["estimate_fen"]
    response = await studio_api.post("/api/tools/run", data={**request, "price_version": str(version.id + 1)})
    assert response.status_code == 409
    assert (await studio_api.post("/api/tools/run", data={**request, "price_version": "0"})).status_code == 200


async def test_reference_limits_and_asset_types_apply_to_quotes(studio, studio_api):
    sessions, user, _ = studio
    audio = await add_reference_asset(sessions, user, kind="voice", url="https://cdn.test/voice.mp3")
    request = video_request(video_mode="first_last_frame", references=[{"role": "first_frame", "asset_id": audio.id}])
    assert (await studio_api.post("/api/tools/estimate", json=request)).status_code == 400
    request = video_request(model_id="MiniMax-H3", resolution="480p", video_mode="omni_reference",
                            references=[{"role": "reference_video", "file_index": 0}])
    assert (await studio_api.post("/api/tools/estimate", json=request)).status_code == 422
    request = video_request(video_mode="omni_reference", references=[{"role": "reference_image", "file_index": i} for i in range(10)])
    assert (await studio_api.post("/api/tools/estimate", json=request)).status_code == 422
