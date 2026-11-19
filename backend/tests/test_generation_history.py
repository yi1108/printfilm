"""Generation history merges durable tasks and legacy rows without mutating either."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.deps import get_current_user
from app.models import Project, Shot, Template, ToolRun, UsageEvent, User
from app.models_drama import DramaAsset, DramaEpisode, DramaEpisodeFragment, DramaProject
from app.models_tasks import TaskEvent, TaskRun
from app.models_teams import Team, TeamMember
from app.services.tasks.generation_history import project_generation


@pytest.fixture
async def history():
    import app.main  # noqa: F401
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        users = [User(email=f"history-{index}@test.local", hashed_password="test") for index in range(3)]
        db.add_all(users)
        await db.flush()
        team = Team(name="History", owner_user_id=users[0].id)
        db.add(team)
        await db.flush()
        db.add_all([TeamMember(team_id=team.id, user_id=user.id, role="owner" if index == 0 else "member")
                    for index, user in enumerate(users[:2])])
        await db.commit()
    yield sessions, users, team
    await engine.dispose()


def task(user, task_type="asset_image", **values):
    return TaskRun(domain="drama", task_type=task_type, requested_by=user.id,
                   queue_type="image", status="succeeded", payload={}, **values)


async def client_for(sessions, user):
    from app.api.tasks import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    async def database():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: user
    return httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")


@pytest.mark.asyncio
async def test_history_merges_all_domains_and_legacy_without_duplicates(history):
    sessions, (user, other, _), team = history
    async with sessions() as db:
        rows = [task(user), task(user, "voice_synthesis"), task(user, "episode_script"),
                TaskRun(domain="api", task_type="v1_seedance", queue_type="video", requested_by=user.id,
                        status="awaiting_poll", provider_task_id="provider-video", payload={}),
                task(other), task(user, team_id=team.id)]
        db.add_all(rows)
        await db.flush()
        db.add_all([ToolRun(user_id=user.id, tool_id="t2i", kind="image", status="succeeded",
                           task_id=f"task-{rows[0].id}", params={"platform_task_id": rows[0].id}, prompt="linked prompt"),
                    ToolRun(user_id=user.id, tool_id="t2v", kind="video", status="failed", task_id="legacy-video"),
                    ToolRun(user_id=other.id, tool_id="t2i", kind="image", status="succeeded")])
        await db.commit()
    async with await client_for(sessions, user) as client:
        response = await client.get("/api/tasks/generations?page_size=2")
        assert response.status_code == 200
        result = response.json()
        assert result["total"] == 4
        assert result["counts"] == {"all": 4, "processing": 1, "succeeded": 2, "failed": 1, "cancelled": 0}
        assert len(result["items"]) == 2
        all_rows = (await client.get("/api/tasks/generations?page_size=50")).json()["items"]
        linked = next(row for row in all_rows if row["record_key"] == f"task:{rows[0].id}")
        assert linked["prompt"] == "linked prompt"
        assert {row["kind"] for row in all_rows} == {"image", "video", "audio"}
        assert len([row for row in all_rows if row["source"] == "tool"]) == 1
        filtered = (await client.get("/api/tasks/generations?kind=video&status=processing")).json()
        assert filtered["total"] == 1 and filtered["counts"]["all"] == 2
        assert filtered["items"][0]["status"] == "running"
        assert (await client.get("/api/tasks/generations?task_id=provider-video")).json()["total"] == 1
        assert (await client.get(f"/api/tasks/generations?task_id={rows[0].id}")).json()["total"] == 1


@pytest.mark.asyncio
async def test_pipeline_phase_kind_matches_sql_filter_and_projection(history):
    sessions, (user, _, _), _team = history
    expected = {"assets": "image", "audio": "audio", "storyboard": "text", "script": "text", "compose": "video"}
    async with sessions() as db:
        for phase in expected:
            db.add(TaskRun(domain="kepu", task_type="project_pipeline", queue_type="video", status="succeeded",
                           requested_by=user.id, payload={"phase": phase}))
        await db.commit()
    async with await client_for(sessions, user) as client:
        for kind in {"image", "audio", "text", "video"}:
            result = (await client.get(f"/api/tasks/generations?kind={kind}")).json()
            assert result["total"] == (sum(value == kind for value in expected.values()) if kind != "text" else 0)
            assert all(row["kind"] == kind and expected[row["params"]["phase"]] == kind for row in result["items"])


@pytest.mark.asyncio
async def test_text_tasks_are_excluded_before_counting_search_and_pagination(history):
    sessions, (user, _, _), _team = history
    async with sessions() as db:
        image = task(user)
        text = task(user, "episode_script")
        text.status = "failed"
        db.add_all([image, text, ToolRun(user_id=user.id, tool_id="text", kind="text", status="queued")])
        await db.commit()
    async with await client_for(sessions, user) as client:
        result = (await client.get("/api/tasks/generations?page_size=1")).json()
        assert result["total"] == result["counts"]["all"] == 1
        assert result["counts"]["failed"] == result["counts"]["processing"] == 0
        assert result["items"][0]["id"] == image.id
        assert (await client.get(f"/api/tasks/generations?task_id={text.id}")).json()["total"] == 0
        assert (await client.get("/api/tasks/generations?kind=text")).json()["total"] == 0
        # Hiding list entries must not remove durable task/detail compatibility.
        assert (await client.get(f"/api/tasks/generations/{text.id}")).json()["kind"] == "text"
    async with sessions() as db:
        assert (await db.get(TaskRun, text.id)).status == "failed"


@pytest.mark.asyncio
async def test_legacy_auto_script_is_hidden_despite_incorrect_empty_video_snapshot(history):
    sessions, (user, _, _), _team = history
    async with sessions() as db:
        row = TaskRun(domain="kepu", task_type="project_pipeline", queue_type="video", requested_by=user.id,
                      status="succeeded", payload={"phase": "produce"}, result_payload={"kind": "video", "urls": []})
        db.add(row)
        await db.flush()
        db.add(UsageEvent(user_id=user.id, task_run_id=row.id, billing_key="llm_chat", capability="llm", domain="kepu"))
        await db.commit()
    async with await client_for(sessions, user) as client:
        listing = (await client.get("/api/tasks/generations")).json()
        assert listing["total"] == listing["counts"]["all"] == 0
        assert (await client.get(f"/api/tasks/generations/{row.id}")).json()["kind"] == "text"


@pytest.mark.asyncio
async def test_provider_id_links_require_matching_tool_domain_and_media_kind(history):
    sessions, (user, _, _), _team = history
    async with sessions() as db:
        api = TaskRun(domain="api", task_type="v1_image", queue_type="image", requested_by=user.id,
                      status="succeeded", provider_task_id="id-api", payload={})
        different_kind = TaskRun(domain="studio", task_type="tool_video", queue_type="video", requested_by=user.id,
                                status="succeeded", provider_task_id="id-kind", payload={})
        matched = TaskRun(domain="studio", task_type="tool_image", queue_type="image", requested_by=user.id,
                          status="succeeded", provider_task_id="id-match", payload={})
        db.add_all([api, different_kind, matched])
        db.add_all([ToolRun(user_id=user.id, tool_id="t2i", kind="image", status="succeeded", task_id=provider_id,
                           urls=[f"https://output.test/{provider_id}.png"])
                    for provider_id in ("id-api", "id-kind", "id-match")])
        await db.commit()
    async with await client_for(sessions, user) as client:
        result = (await client.get("/api/tasks/generations")).json()
        assert result["total"] == 5
        tasks = {row["id"]: row for row in result["items"] if row["source"] == "task"}
        assert tasks[api.id]["urls"] == []
        assert tasks[different_kind.id]["urls"] == []
        assert tasks[matched.id]["urls"] == ["https://output.test/id-match.png"]
        assert tasks[api.id]["prompt"] == ""


@pytest.mark.asyncio
async def test_workspace_and_detail_are_isolated_and_money_is_private(history):
    sessions, (owner, member, stranger), team = history
    async with sessions() as db:
        personal = task(owner)
        shared = task(owner, team_id=team.id, billing_charged_fen=420, billing_status="settled")
        db.add_all([personal, shared])
        await db.commit()
    async with await client_for(sessions, member) as client:
        assert (await client.get("/api/tasks/generations")).json()["total"] == 0
        listing = (await client.get("/api/tasks/generations", headers={"X-Team-Id": str(team.id)})).json()
        assert listing["total"] == 1 and listing["items"][0]["billing_charged_fen"] is None
        assert (await client.get(f"/api/tasks/generations/{shared.id}")).status_code == 404
        detail = await client.get(f"/api/tasks/generations/{shared.id}", headers={"X-Team-Id": str(team.id)})
        assert detail.status_code == 200 and detail.json()["billing_charged_fen"] is None
        assert (await client.get(f"/api/tasks/generations/{personal.id}", headers={"X-Team-Id": str(team.id)})).status_code == 404
        assert (await client.get(f"/api/tasks/generations?team_id={team.id + 1}", headers={"X-Team-Id": str(team.id)})).status_code == 422
    async with await client_for(sessions, stranger) as client:
        assert (await client.get("/api/tasks/generations", headers={"X-Team-Id": str(team.id)})).status_code in {403, 404}
    async with await client_for(sessions, owner) as client:
        detail = await client.get(f"/api/tasks/generations/{shared.id}", headers={"X-Team-Id": str(team.id)})
        assert detail.json()["billing_charged_fen"] == 420


@pytest.mark.asyncio
async def test_history_filters_dates_preserves_rows_and_ignores_missing_links(history):
    sessions, (user, _, _), _team = history
    past = datetime.now(UTC) - timedelta(days=4)
    async with sessions() as db:
        row = task(user, created_at=past)
        db.add(row)
        db.add(ToolRun(user_id=user.id, tool_id="t2i", kind="image", status="queued",
                       params={"platform_task_id": 999999}, prompt="orphan"))
        await db.commit()
    async with await client_for(sessions, user) as client:
        result = await client.get("/api/tasks/generations", params={"created_from": (past + timedelta(days=1)).isoformat()})
        assert result.json()["total"] == 1
        assert result.json()["items"][0]["source"] == "tool"
        assert (await client.get("/api/tasks/generations?created_from=2026-10-02&created_to=2026-10-01")).status_code == 400
    async with sessions() as db:
        persisted = await db.get(TaskRun, row.id)
        assert persisted.status == "succeeded" and persisted.result_payload is None


@pytest.mark.asyncio
async def test_old_tasks_use_only_the_latest_owned_entity_output(history):
    sessions, (user, other, _), _team = history
    now = datetime.now(UTC)
    async with sessions() as db:
        project = DramaProject(user_id=user.id, title="Legacy project")
        other_project = DramaProject(user_id=other.id, title="Other project")
        db.add_all([project, other_project])
        await db.flush()
        asset = DramaAsset(project_id=project.id, asset_type="image", url="https://output.test/latest.png", updated_at=now)
        unrelated = DramaAsset(project_id=other_project.id, asset_type="image", url="https://private.test/other.png", updated_at=now)
        db.add_all([asset, unrelated])
        await db.flush()
        old = task(user, asset_id=asset.id, drama_project_id=project.id, finished_at=now)
        latest = task(user, asset_id=asset.id, drama_project_id=project.id, finished_at=now)
        mismatched = task(user, asset_id=unrelated.id, drama_project_id=project.id, finished_at=now)
        db.add_all([old, latest, mismatched])
        await db.commit()
    async with await client_for(sessions, user) as client:
        data = (await client.get("/api/tasks/generations")).json()["items"]
        by_id = {row["id"]: row for row in data}
        assert by_id[latest.id]["urls"] == ["https://output.test/latest.png"]
        assert by_id[old.id]["urls"] == []
        assert by_id[mismatched.id]["urls"] == []


@pytest.mark.asyncio
async def test_fragment_shot_and_project_artifacts_have_legacy_previews(history):
    sessions, (user, _, _), _team = history
    now = datetime.now(UTC)
    async with sessions() as db:
        drama = DramaProject(user_id=user.id, title="Legacy drama")
        template = Template(id="history", name="History", style_prefix="")
        db.add_all([drama, template])
        await db.flush()
        episode = DramaEpisode(project_id=drama.id, name="First episode")
        project = Project(user_id=user.id, template_id=template.id, title="Science", source_text="source",
                          final_video_url="https://output.test/final.mp4", updated_at=now)
        db.add_all([episode, project])
        await db.flush()
        fragment = DramaEpisodeFragment(episode_id=episode.id, video="https://output.test/fragment.mp4", updated_at=now)
        shot = Shot(project_id=project.id, shot_no=1, audio_url="https://output.test/narration.wav")
        db.add_all([fragment, shot])
        await db.flush()
        fragment_task = task(user, "fragment_video", drama_project_id=drama.id,
                             episode_id=episode.id, fragment_id=fragment.id, finished_at=now)
        audio_task = task(user, "shot_regen_audio", project_id=project.id, shot_id=shot.id, finished_at=now)
        final_task = task(user, "project_compose_only", project_id=project.id, finished_at=now)
        db.add_all([fragment_task, audio_task, final_task])
        await db.commit()
    async with await client_for(sessions, user) as client:
        records = (await client.get("/api/tasks/generations")).json()["items"]
        by_id = {row["id"]: row for row in records}
        assert by_id[fragment_task.id]["urls"] == ["https://output.test/fragment.mp4"]
        assert by_id[audio_task.id]["urls"] == ["https://output.test/narration.wav"]
        assert by_id[final_task.id]["urls"] == ["https://output.test/final.mp4"]


def test_projection_accepts_only_outputs_and_safe_parameters():
    row = SimpleNamespace(id=14, task_type="asset_image", domain="drama", queue_type="image", status="succeeded",
        payload={"prompt": "a tree", "file_paths": ["C:/private.png"], "api_key": "secret", "ratio": "1:1",
                 "reference_images": ["https://input.test/input.png"]},
        result_payload={"url": "https://output.test/generated.png", "input": {"url": "https://input.test/input.png"},
                        "api_key": "secret", "preview_url": "file:///private.png"},
        steps=[], team_id=None, requested_by=1)
    output = project_generation(row, viewer_id=1)
    assert output.urls == ["https://output.test/generated.png"]
    assert output.params == {"prompt": "a tree", "ratio": "1:1", "aspect_ratio": "1:1"}
    assert output.preview_url == output.urls[0]
    assert "secret" not in output.model_dump_json() and "private.png" not in output.model_dump_json()
    row.result_payload = {"url": "C:/secret.png"}
    assert project_generation(row, viewer_id=1).urls == []


def test_text_and_step_projections_exclude_upstream_traces():
    row = SimpleNamespace(id=1, task_type="episode_script", domain="drama", queue_type="text", status="succeeded",
        payload={}, result_payload={"text": "generated script", "token": "private", "provider_response": {"content": "secret"}},
        steps=[], team_id=None, requested_by=1)
    assert project_generation(row, viewer_id=1).text_content == "generated script"
    row.task_type = "v1_video"
    row.queue_type = "video"
    row.result_payload = {"ok": True}
    row.steps = [SimpleNamespace(output_payload={"video_url": "https://output.test/result.mp4", "api_key": "private"})]
    result = project_generation(row, viewer_id=1)
    assert result.urls == ["https://output.test/result.mp4"] and result.text_content == ""


@pytest.mark.asyncio
async def test_history_restores_actual_submission_without_other_attempts_or_helper_images(history):
    """Current accepted video parameters override requested/planned data, without leaking traces."""
    sessions, (user, _, _), _team = history
    async with sessions() as db:
        row = TaskRun(domain="drama", task_type="fragment_video", queue_type="video", status="succeeded",
            requested_by=user.id, provider_task_id="final-video",
            payload={"model_id": "requested", "duration_sec": 12, "ratio": "9:16"},
            billing_snapshot={"items": [{"capability": "video", "model_id": "planned",
                                         "params": {"duration": 10, "aspect_ratio": "9:16"}}]},
            result_payload={"urls": ["https://output.test/video.mp4"],
                            "media_info": {"duration_sec": 8.04, "width": 854, "height": 480}})
        db.add(row)
        await db.flush()
        actual = {"model": "MiniMax-H3", "seconds": "6", "ratio": "16:9", "resolution": "480p",
                  "generate_audio": False, "content": [{"type": "text", "text": "Final submitted scene"},
                  {"type": "image_url", "image_url": {"url": "https://private.test/reference.png"}}], "api_key": "private"}
        for event_type, provider_id, is_video, body in (
            ("upstream.request.accepted", "final-video", True, actual),
            ("upstream.request.accepted", None, False, {"model": "helper-image", "prompt": "Helper still"}),
            ("upstream.request.failed", "final-video", True, {"model": "failed", "prompt": "Failed retry"}),
            ("upstream.request.accepted", "other-video", True, {"model": "other", "prompt": "Other attempt"}),
        ):
            db.add(TaskEvent(task_id=row.id, event_type=event_type, payload={
                "method": "POST", "endpoint": "https://gateway.test/v1/videos" if is_video else "https://gateway.test/v1/images/generations",
                "is_video_submit": is_video, "provider_task_id": provider_id,
                "request": {"body": body, "headers": {"Authorization": "private-header"}},
            }))
        await db.commit()
    async with await client_for(sessions, user) as client:
        response = await client.get(f"/api/tasks/generations/{row.id}")
        assert response.status_code == 200
        record = response.json()
        assert record["prompt"] == "Final submitted scene"
        assert record["params"]["model_id"] == "MiniMax-H3"
        assert record["params"]["duration"] == record["params"]["duration_sec"] == "6"
        assert record["params"]["ratio"] == record["params"]["aspect_ratio"] == "16:9"
        assert record["params"]["generate_audio"] is False
        assert record["params"]["media_duration_sec"] == 8.04
        assert record["params"]["media_width"] == 854 and record["params"]["media_height"] == 480
        assert "private" not in response.text and "Helper still" not in response.text
    async with sessions() as db:
        persisted = await db.get(TaskRun, row.id)
        assert persisted.payload == {"model_id": "requested", "duration_sec": 12, "ratio": "9:16"}


def test_history_uses_prepared_snapshot_and_leaves_unknown_prompt_empty():
    """Helper operations cannot supply video parameters; missing historical prompts stay unknown."""
    row = SimpleNamespace(id=1, task_type="fragment_video", domain="drama", queue_type="video", status="running",
        payload={"generation_params": {"prompt": "Frozen scene", "model_id": "actual", "duration": 6}},
        billing_snapshot={"items": [{"capability": "video", "model_id": "planned", "params": {"duration": 8}},
                                    {"capability": "image", "model_id": "helper", "params": {"prompt": "Helper"}}]},
        result_payload={}, steps=[], team_id=None, requested_by=1)
    output = project_generation(row, viewer_id=1)
    assert output.prompt == "Frozen scene" and output.params["model_id"] == "actual"
    assert output.params["duration"] == 6
    long_prompt = "镜" * 14_996 + "尾部标记"
    row.payload = {"generation_params": {"prompt": long_prompt, "model_id": "seedance-2.5"}}
    output = project_generation(row, viewer_id=1)
    assert output.prompt == output.params["prompt"] == long_prompt
    row.payload = {}
    assert project_generation(row, viewer_id=1).prompt == ""


@pytest.mark.asyncio
async def test_history_restores_matching_local_simulated_http_parameters(history):
    """本地模拟同样保留最终参数，但必须匹配实际产出 request_id，不串入后续请求。"""
    sessions, (user, _, _), _team = history
    async with sessions() as db:
        row = TaskRun(domain="drama", task_type="fragment_video", queue_type="video", status="succeeded",
                      requested_by=user.id, provider_task_id="local-media-matching", payload={})
        db.add(row)
        await db.flush()
        for request_id, overrides in (("matching", {}), ("later", {}), ("matching", {"provider": "untrusted"}),
                                       ("matching", {"request_stage": "business_input"})):
            db.add(TaskEvent(task_id=row.id, event_type="upstream.request.simulated", payload={
                "method": "POST", "endpoint": "https://gateway.test/v1/videos", "provider": "local-mock",
                "simulated": True, "operation": "video.generate", "request_stage": "http_ready",
                "request_id": request_id,
                "request": {"body": {"model": "MiniMax-H3", "prompt": f"Prompt {request_id}", "seconds": "12",
                    "metadata": {"ratio": "9:16", "resolution": "480p", "generate_audio": True,
                                 "duration": 12, "api_key": "private", "prompt": "Nested unrelated prompt"}}},
                **overrides,
            }))
        await db.commit()
    async with await client_for(sessions, user) as client:
        response = await client.get(f"/api/tasks/generations/{row.id}")
        assert response.status_code == 200
        record = response.json()
        assert record["prompt"] == "Prompt matching"
        assert record["params"]["duration"] == "12" and record["params"]["resolution"] == "480p"
        assert record["params"]["aspect_ratio"] == "9:16" and record["params"]["generate_audio"] is True
        assert "Nested unrelated" not in response.text and "private" not in response.text


@pytest.mark.asyncio
async def test_image_history_restores_the_final_responses_input(history):
    """TokenFree /responses 生图实际文案在 input，画幅等计费规格来自本次固定快照。"""
    sessions, (user, _, _), _team = history
    async with sessions() as db:
        row = task(user, billing_snapshot={"items": [{"capability": "image", "model_id": "gpt-image-2",
                                                      "params": {"aspect_ratio": "3:4", "resolution": "2K"}}]})
        db.add(row)
        await db.flush()
        db.add(TaskEvent(task_id=row.id, event_type="upstream.request.accepted", payload={
            "method": "POST", "endpoint": "https://gateway.test/v1/responses",
            "request": {"body": {"model": "gpt-image-2", "input": "Character sheet. Final canvas must be 3:4."}},
        }))
        await db.commit()
    async with await client_for(sessions, user) as client:
        record = (await client.get(f"/api/tasks/generations/{row.id}")).json()
        assert record["prompt"] == "Character sheet. Final canvas must be 3:4."
        assert record["params"]["model_id"] == "gpt-image-2" and record["params"]["aspect_ratio"] == "3:4"


@pytest.mark.asyncio
async def test_postgres_union_and_json_task_links(db_session):
    """Exercise PostgreSQL JSON text extraction, correlation and union pagination."""
    from app.services.tasks.generation_history import list_generations
    from tests.conftest import make_user
    user = await make_user(db_session)
    shared_team = Team(name="Postgres history", owner_user_id=user.id)
    db_session.add(shared_team)
    await db_session.flush()
    image = task(user, result_payload={"urls": ["https://output.test/image.png"]})
    audio = task(user, "voice_preview")
    shared = task(user, team_id=shared_team.id)
    waiting = TaskRun(domain="api", task_type="v1_seedance", requested_by=user.id,
                      queue_type="video", status="cancel_requested", payload={})
    reviewing = TaskRun(domain="api", task_type="v1_video", requested_by=user.id,
                        queue_type="video", status="awaiting_review", payload={})
    db_session.add_all([image, audio, shared, waiting, reviewing])
    await db_session.flush()
    db_session.add_all([
        ToolRun(user_id=user.id, tool_id="t2i", kind="image", status="succeeded", params={"billing_task_id": image.id}),
        ToolRun(user_id=user.id, tool_id="t2i", kind="image", status="succeeded", params={"platform_task_id": shared.id}),
        ToolRun(user_id=user.id, tool_id="t2i", kind="image", status="succeeded", params={"platform_task_id": "old-nonnumeric"}),
    ])
    await db_session.flush()
    result = await list_generations(db_session, user, page_size=2)
    assert result.total == 5 and result.counts["processing"] == 2 and len(result.items) == 2
    all_records = await list_generations(db_session, user, page_size=100)
    assert len([row for row in all_records.items if row.source == "tool"]) == 1
    assert (await list_generations(db_session, user, kind="audio")).items[0].platform_task_id == audio.id
    assert (await list_generations(db_session, user, status="processing")).total == 2
