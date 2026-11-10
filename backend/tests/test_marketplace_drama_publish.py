"""漫剧到市场的整集发布：隔离测试库/schema，文件存储仅使用测试替身。"""
from types import SimpleNamespace
from contextlib import asynccontextmanager
from datetime import timedelta
import uuid

from fastapi import FastAPI, HTTPException
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.database import Base, get_db
from app.deps import get_current_user
from app.models import Project, Shot, Template, User
from app.models_drama import DramaAsset, DramaEpisode, DramaEpisodeFragment, DramaProject, DramaScript
from app.models_tasks import TaskRun
from app.models_teams import Team, TeamMember
from app.marketplace import drama_media, drama_publish, handoff, storage
from app.marketplace import series as series_api
from app.marketplace.authorization import VERSION
from app.marketplace.models import Asset, Authorization, DramaPublishBatch, Handoff, MarketBase, Publication, Rights, Series, SeriesEpisode
from app.marketplace.service import now
from conftest import _ensure_test_database, _resolve_test_database_url


@pytest_asyncio.fixture
async def drama_publish_ctx(monkeypatch):
    url, name = _resolve_test_database_url(get_settings().database_url)
    await _ensure_test_database(url, name)
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        outer = await connection.begin()
        schema = f"drama_publish_test_{uuid.uuid4().hex}"
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection = await connection.execution_options(schema_translate_map={None: schema})
        tables = [item.__table__ for item in (User, Team, TeamMember, Template, Project, Shot, DramaProject, DramaScript, DramaAsset, DramaEpisode, DramaEpisodeFragment, TaskRun)]
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        await connection.run_sync(MarketBase.metadata.create_all)
        db = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        owner = User(email="drama-owner@test.invalid", hashed_password="unused")
        other = User(email="drama-other@test.invalid", hashed_password="unused")
        db.add_all([owner, other])
        await db.commit()
        ctx = SimpleNamespace(db=db, owner=owner, other=other, user=owner, source_revision=1)

        async def db_override():
            try:
                yield db
            except Exception:
                await db.rollback()
                await db.refresh(owner)
                await db.refresh(other)
                raise

        async def actor_override():
            return ctx.user

        def source_stamp(locator):
            return {"kind": "local", "locator": locator, "size_bytes": 100, "file_id": "source-file", "mtime_ns": ctx.source_revision, "fingerprint": f"revision-{ctx.source_revision}"}

        app = FastAPI()
        from app.marketplace.locale_middleware import install_locale
        install_locale(app)
        app.include_router(drama_publish.router, prefix="/api/marketplace")
        app.include_router(handoff.router, prefix="/api/marketplace")
        app.dependency_overrides[get_db] = db_override
        app.dependency_overrides[get_current_user] = actor_override
        monkeypatch.setattr(storage, "bucket", lambda: object())
        monkeypatch.setattr(storage, "configured", lambda: True)
        monkeypatch.setattr(drama_media, "source_stamp", source_stamp)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                ctx.client = client
                yield ctx
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


async def source(ctx, *, owner=None, episodes=1, fragments=3):
    project = DramaProject(user_id=(owner or ctx.owner).id, title="完整漫剧", description="导入后的独立介绍")
    ctx.db.add(project)
    await ctx.db.flush()
    items, clips = [], []
    for number in range(1, episodes + 1):
        episode = DramaEpisode(project_id=project.id, name=f"原第{number}集", params={"episodeNumber": number})
        ctx.db.add(episode)
        await ctx.db.flush()
        for index in range(fragments):
            # 故意逆序创建，用排序断言防止只导入最后一镜。
            order = fragments - index - 1
            clip = DramaEpisodeFragment(episode_id=episode.id, sort_order=order, video=f"/static/test/episode-{number}-shot-{order}.mp4", cover=f"/static/test/cover-{number}.png")
            ctx.db.add(clip)
            clips.append(clip)
        items.append(episode)
    await ctx.db.commit()
    return project, items, clips


async def publish_payload(ctx, project, episodes, *, key=None, series=None, update=False):
    snapshot = [await drama_publish.episode_snapshot(ctx.db, ctx.owner.id, project.id, episode.id) for episode in episodes]
    return {"episodes": [{"episode_id": item["drama_episode_id"], "source_version": item["source_version"], "update": update} for item in snapshot],
            "series_id": series.id if series else None, "series_version": series.version if series else None, "idempotency_key": key or uuid.uuid4().hex}


async def post_publish(ctx, project, payload):
    return await ctx.client.post(f"/api/marketplace/printfilm/dramas/{project.id}/publish", json=payload)


async def published(ctx):
    project, episodes, clips = await source(ctx)
    response = await post_publish(ctx, project, await publish_payload(ctx, project, episodes))
    assert response.status_code == 200, response.text
    body = response.json()
    task = await ctx.db.get(Handoff, body["handoffs"][0]["id"])
    target = await ctx.db.get(SeriesEpisode, body["items"][0]["id"])
    series = await ctx.db.get(Series, body["series_id"])
    return SimpleNamespace(project=project, episodes=episodes, clips=clips, task=task, target=target, series=series)


async def test_context_shows_complete_counts_and_all_owned_target_series(drama_publish_ctx):
    ctx = drama_publish_ctx
    project, episodes, clips = await source(ctx, episodes=2)
    clips[0].video = ""
    own = Series(owner_id=ctx.owner.id, title="我的其他系列")
    foreign = Series(owner_id=ctx.other.id, title="其他人的系列")
    ctx.db.add_all([own, foreign])
    await ctx.db.commit()
    response = await ctx.client.get(f"/api/marketplace/printfilm/dramas/{project.id}/publish-context")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project"]["description"] == project.description
    assert body["episodes"][0]["fragment_count"] == 3 and body["episodes"][0]["completed_count"] == 2
    assert body["episodes"][0]["ready"] is False and "SOURCE_NOT_READY" in body["episodes"][0]["reason"]
    assert body["episodes"][1]["ready"] is True
    assert [item["id"] for item in body["series"]] == [own.id]
    assert body["storage_configured"] is True and body["authorization_ready"] is False
    assert "/static/" not in response.text
    english = await ctx.client.get(f"/api/marketplace/printfilm/dramas/{project.id}/publish-context", headers={"Accept-Language": "en-US"})
    failed = english.json()["episodes"][0]
    assert failed["reason_code"] == "MARKETPLACE_SOURCE_NOT_READY"
    assert failed["reason_label"] == "Complete all shot videos for this episode first."
    assert failed["reason"].startswith("MARKETPLACE_SOURCE_NOT_READY:")
    assert failed["name"] == body["episodes"][0]["name"]


async def test_team_creator_loses_publish_access_and_import_source_after_leaving(drama_publish_ctx):
    """创建者身份不会绕过离队限制，来源列表也保留个人与账号隔离。"""
    ctx = drama_publish_ctx
    team = Team(name="市场导入团队", owner_user_id=ctx.other.id)
    ctx.db.add(team)
    await ctx.db.flush()
    membership = TeamMember(team_id=team.id, user_id=ctx.owner.id, role="member", active=True)
    ctx.db.add(membership)
    personal, _, _ = await source(ctx)
    project, _, _ = await source(ctx)
    foreign, _, _ = await source(ctx, owner=ctx.other)
    project.team_id = foreign.team_id = team.id
    await ctx.db.commit()
    personal_id, project_id, foreign_id = personal.id, project.id, foreign.id
    path = f"/api/marketplace/printfilm/dramas/{project_id}/publish-context"

    response = await ctx.client.get(path)
    assert response.status_code == 200, response.text
    sources = await series_api.import_sources(ctx.db, ctx.owner)
    assert {item["id"] for item in sources["items"]} == {personal_id, project_id}
    assert foreign_id not in {item["id"] for item in sources["items"]}

    membership.active = False
    await ctx.db.commit()
    response = await ctx.client.get(path)
    assert response.status_code == 404, response.text
    assert (await ctx.db.get(DramaProject, project_id)).user_id == ctx.owner.id
    sources = await series_api.import_sources(ctx.db, ctx.owner)
    assert [item["id"] for item in sources["items"]] == [personal_id]


@pytest.mark.parametrize("case", ["foreign_project", "foreign_episode", "foreign_target"])
async def test_publish_rejects_cross_account_sources_and_targets(drama_publish_ctx, case):
    ctx = drama_publish_ctx
    project, episodes, _ = await source(ctx)
    payload = await publish_payload(ctx, project, episodes)
    if case == "foreign_project":
        ctx.user = ctx.other
    elif case == "foreign_episode":
        other_project, other_episodes, _ = await source(ctx, owner=ctx.other)
        payload["episodes"][0]["episode_id"] = other_episodes[0].id
    else:
        target = Series(owner_id=ctx.other.id, title="其他系列")
        ctx.db.add(target)
        await ctx.db.commit()
        payload["series_id"] = target.id
        payload["series_version"] = target.version
    response = await post_publish(ctx, project, payload)
    assert response.status_code == 404, response.text
    assert await ctx.db.scalar(select(func.count()).select_from(Handoff)) == 0
    assert await ctx.db.scalar(select(func.count()).select_from(DramaPublishBatch)) == 0


@pytest.mark.parametrize("case", ["missing_shot", "task_video", "task_plan", "episode_plan", "shot_video"])
async def test_incomplete_or_generating_episode_creates_no_market_draft(drama_publish_ctx, case):
    ctx = drama_publish_ctx
    project, episodes, clips = await source(ctx)
    payload = await publish_payload(ctx, project, episodes)
    if case == "missing_shot":
        clips[0].video = ""
    elif case.startswith("task_"):
        ctx.db.add(TaskRun(domain="drama", task_type="fragment_video" if case == "task_video" else "fragment_plan", status="running", requested_by=ctx.owner.id,
                           episode_id=episodes[0].id, drama_project_id=project.id, fragment_id=clips[0].id))
    elif case == "episode_plan":
        episodes[0].params = {"episodeNumber": 1, "fragment_plan_status": "running"}
    else:
        clips[0].params = {"video_gen": {"status": "running"}}
    await ctx.db.commit()
    response = await post_publish(ctx, project, payload)
    assert response.status_code == 409 and "MARKETPLACE_SOURCE_NOT_READY" in response.text
    assert await ctx.db.scalar(select(func.count()).select_from(Series)) == 0
    assert await ctx.db.scalar(select(func.count()).select_from(Handoff)) == 0


async def test_storage_unavailable_never_creates_empty_series(drama_publish_ctx, monkeypatch):
    ctx = drama_publish_ctx
    project, episodes, _ = await source(ctx)
    payload = await publish_payload(ctx, project, episodes)

    def unavailable():
        raise HTTPException(503, {"code": "MARKETPLACE_STORAGE_UNAVAILABLE", "message": "文件服务暂未配置"})

    monkeypatch.setattr(storage, "bucket", unavailable)
    response = await post_publish(ctx, project, payload)
    assert response.status_code == 503 and "MARKETPLACE_STORAGE_UNAVAILABLE" in response.text
    assert await ctx.db.scalar(select(func.count()).select_from(Series)) == 0


async def test_atomic_publish_is_idempotent_orders_all_clips_and_keeps_upstream(drama_publish_ctx):
    ctx = drama_publish_ctx
    project, episodes, clips = await source(ctx, episodes=2)
    payload = await publish_payload(ctx, project, list(reversed(episodes)))
    response = await post_publish(ctx, project, payload)
    assert response.status_code == 200, response.text
    result = response.json()
    again = await post_publish(ctx, project, payload)
    assert again.status_code == 200 and again.json() == result
    assert await ctx.db.scalar(select(func.count()).select_from(Series)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(SeriesEpisode)) == 2
    assert await ctx.db.scalar(select(func.count()).select_from(Handoff)) == 2
    target = await ctx.db.get(Series, result["series_id"])
    assert target.title == project.title and target.description == project.description
    for index, item in enumerate(result["items"]):
        assert item["episode_no"] == index + 1 and item["title"] == episodes[index].name
        task = await ctx.db.get(Handoff, result["handoffs"][index]["id"])
        assert [clip["sort_order"] for clip in task.source_snapshot["clips"]] == [0, 1, 2]
        assert len(task.source_snapshot["clips"]) == 3
    assert all(clip.video.startswith("/static/test/") for clip in clips)
    payload["title"] = "另一次不同发布"
    conflict = await post_publish(ctx, project, payload)
    assert conflict.status_code == 409


async def test_snapshots_keep_project_card_cover_and_episode_cover_distinct(drama_publish_ctx):
    """选择第二集时保留该集图片，系列封面仍与项目卡片的第一集一致。"""
    ctx = drama_publish_ctx
    project, episodes, clips = await source(ctx, episodes=2)
    snapshot = await drama_publish.episode_snapshot(ctx.db, ctx.owner.id, project.id, episodes[1].id)
    assert snapshot["cover_locator"] == "/static/test/cover-2.png"
    assert snapshot["project_cover_locator"] == "/static/test/cover-1.png"
    assert snapshot["project_cover_stamp"]["locator"] == snapshot["project_cover_locator"]
    # 没有独立图片的分镜在项目卡片上显示视频首帧；市场保存同一受控来源。
    for clip in clips:
        clip.cover = ""
    await ctx.db.commit()
    snapshot = await drama_publish.episode_snapshot(ctx.db, ctx.owner.id, project.id, episodes[1].id)
    assert snapshot["project_cover_locator"] == "/static/test/episode-1-shot-0.mp4"
    assert snapshot["cover_locator"] == snapshot["project_cover_locator"]


@pytest.mark.parametrize("case", ["new_series", "existing_series", "series_edited", "episode_cover_selected"])
async def test_project_cover_binding_only_fills_unchanged_new_series(drama_publish_ctx, case):
    """异步回填带入新系列封面，保留现有系列、用户编辑及分集自选封面。"""
    ctx = drama_publish_ctx
    project, episodes, _ = await source(ctx)
    series = None
    if case == "existing_series":
        series = Series(owner_id=ctx.owner.id, title="已有系列")
        ctx.db.add(series)
        await ctx.db.commit()
    response = await post_publish(ctx, project, await publish_payload(ctx, project, episodes, series=series))
    assert response.status_code == 200, response.text
    result = response.json()
    series = await ctx.db.get(Series, result["series_id"])
    target = await ctx.db.get(SeriesEpisode, result["items"][0]["id"])
    task = await ctx.db.get(Handoff, result["handoffs"][0]["id"])
    video = Asset(owner_id=ctx.owner.id, kind="video", filename="video.mp4", content_type="video/mp4", size_bytes=100,
                  object_key="marketplace/video.mp4", status="ready")
    cover = Asset(owner_id=ctx.owner.id, kind="image", filename="cover.png", content_type="image/png", size_bytes=10,
                  object_key="marketplace/cover.png", status="ready")
    own_cover = Asset(owner_id=ctx.owner.id, kind="image", filename="chosen.png", content_type="image/png", size_bytes=10,
                      object_key="marketplace/chosen.png", status="ready")
    ctx.db.add_all([video, cover, own_cover])
    await ctx.db.flush()
    if case == "series_edited":
        # 包括用户明确移除封面的情形；旧任务不能重新填回。
        series.version += 1
    elif case == "episode_cover_selected":
        target.cover_asset_id = own_cover.id
        series.cover_asset_id = own_cover.id
    task.asset_id = video.id
    await handoff._bind(ctx.db, task, video.id, cover.id, cover.id)
    assert target.cover_asset_id == (own_cover.id if case == "episode_cover_selected" else cover.id)
    expected = cover.id if case == "new_series" else own_cover.id if case == "episode_cover_selected" else None
    assert series.cover_asset_id == expected


async def test_worker_copies_project_and_episode_covers_to_independent_market_assets(drama_publish_ctx, monkeypatch):
    """从第二集发布时，项目封面和分集封面都经私有市场存储再独立绑定。"""
    ctx = drama_publish_ctx
    project, episodes, _ = await source(ctx, episodes=2)
    response = await post_publish(ctx, project, await publish_payload(ctx, project, [episodes[1]]))
    assert response.status_code == 200, response.text
    body = response.json()
    series = await ctx.db.get(Series, body["series_id"])
    target = await ctx.db.get(SeriesEpisode, body["items"][0]["id"])
    copies = []

    @asynccontextmanager
    async def sessions():
        yield ctx.db

    async def prepare_video(snapshot, destination, on_phase):
        return {"size_bytes": 100, "content_type": "video/mp4", "fingerprint": "f" * 64, "duration_seconds": 9.0}

    async def prepare_cover(locator, destination, stamp):
        assert stamp["locator"] == locator
        copies.append((locator, destination))
        return {"size_bytes": 10, "content_type": "image/png"}

    monkeypatch.setattr(handoff, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(drama_media, "prepare_drama_video", prepare_video)
    monkeypatch.setattr(drama_media, "prepare_drama_cover", prepare_cover)
    monkeypatch.setattr(storage, "discard_generated", lambda key: None)
    assert await handoff.run_handoff_once() is True
    assert [locator for locator, _ in copies] == ["/static/test/cover-2.png", "/static/test/cover-1.png"]
    assert series.cover_asset_id != target.cover_asset_id
    assert (await ctx.db.get(Asset, target.cover_asset_id)).object_key == copies[0][1]
    assert (await ctx.db.get(Asset, series.cover_asset_id)).object_key == copies[1][1]
    assert all(key.startswith("marketplace/series/") for _, key in copies)


@pytest.mark.parametrize("case", ["episode_existing_shared", "both_existing_shared", "episode_existing_distinct", "series_existing_distinct"])
async def test_worker_creates_only_attached_cover_assets_and_discards_unused_objects(drama_publish_ctx, monkeypatch, case):
    """已有封面不产生孤立 Asset；共用对象仍可只挂给缺封面的新系列。"""
    ctx = drama_publish_ctx
    project, episodes, _ = await source(ctx, episodes=2 if case.endswith("distinct") else 1)
    response = await post_publish(ctx, project, await publish_payload(ctx, project, [episodes[-1]]))
    body = response.json()
    series = await ctx.db.get(Series, body["series_id"])
    episode = await ctx.db.get(SeriesEpisode, body["items"][0]["id"])
    own = Asset(owner_id=ctx.owner.id, kind="image", filename="chosen.png", content_type="image/png", size_bytes=10,
                object_key="marketplace/already-chosen.png", status="ready")
    ctx.db.add(own)
    await ctx.db.flush()
    if case.startswith(("episode_", "both_")):
        episode.cover_asset_id = own.id
    if case.startswith(("series_", "both_")):
        series.cover_asset_id = own.id
    await ctx.db.commit()
    produced, discarded = [], []

    @asynccontextmanager
    async def sessions():
        yield ctx.db

    async def prepare_video(snapshot, destination, on_phase):
        return {"size_bytes": 100, "content_type": "video/mp4", "fingerprint": "f" * 64, "duration_seconds": 9.0}

    async def prepare_cover(locator, destination, stamp):
        produced.append(destination)
        return {"size_bytes": 10, "content_type": "image/png"}

    monkeypatch.setattr(handoff, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(drama_media, "prepare_drama_video", prepare_video)
    monkeypatch.setattr(drama_media, "prepare_drama_cover", prepare_cover)
    monkeypatch.setattr(storage, "discard_generated", discarded.append)
    assert await handoff.run_handoff_once() is True
    covers = list((await ctx.db.execute(select(Asset).where(Asset.kind == "image"))).scalars().all())
    assert {cover.id for cover in covers} == {episode.cover_asset_id, series.cover_asset_id}
    assert set(discarded) == set(produced) - {cover.object_key for cover in covers}
    if case.startswith(("episode_", "both_")):
        assert episode.cover_asset_id == own.id
    if case.startswith(("series_", "both_")):
        assert series.cover_asset_id == own.id
    if case == "episode_existing_shared":
        assert series.cover_asset_id != own.id and len(covers) == 2 and discarded == []


async def test_snapshot_reuses_only_its_own_frozen_video_stamp_for_cover(drama_publish_ctx, monkeypatch):
    """同一快照用视频首帧作封面时只算一次指纹，下一次快照仍重新校验源文件。"""
    ctx = drama_publish_ctx
    project, episodes, clips = await source(ctx)
    for clip in clips:
        clip.cover = ""
    await ctx.db.commit()
    calls = []
    original = drama_media.source_stamp

    def counted(locator):
        calls.append(locator)
        return original(locator)

    monkeypatch.setattr(drama_media, "source_stamp", counted)
    first = await drama_publish.episode_snapshot(ctx.db, ctx.owner.id, project.id, episodes[0].id)
    assert len(calls) == 3 and len(set(calls)) == 3
    ctx.source_revision += 1
    second = await drama_publish.episode_snapshot(ctx.db, ctx.owner.id, project.id, episodes[0].id)
    assert len(calls) == 6 and first["source_version"] != second["source_version"]


async def test_same_source_version_in_same_target_reuses_episode_across_batches(drama_publish_ctx):
    ctx = drama_publish_ctx
    existing = await published(ctx)
    response = await post_publish(ctx, existing.project, await publish_payload(ctx, existing.project, existing.episodes, series=existing.series))
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == existing.target.id
    assert response.json()["handoffs"][0]["id"] == existing.task.id
    assert await ctx.db.scalar(select(func.count()).select_from(SeriesEpisode)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(Handoff)) == 1


async def test_changed_source_requires_confirmation_and_preserves_old_publication_asset(drama_publish_ctx):
    ctx = drama_publish_ctx
    existing = await published(ctx)
    old_asset = Asset(owner_id=ctx.owner.id, kind="video", filename="old.mp4", content_type="video/mp4", size_bytes=100, object_key="marketplace/old.mp4", status="ready")
    ctx.db.add(old_asset)
    await ctx.db.flush()
    existing.target.asset_id, existing.target.audit_status, existing.target.listed = old_asset.id, "approved", True
    existing.target.source_snapshot = {**existing.target.source_snapshot, "pending_handoff_id": None, "last_handoff_id": existing.task.id}
    existing.task.status, existing.task.asset_id = "ready", old_asset.id
    existing.series.audit_status, existing.series.listed = "approved", True
    publication = Publication(content_type="series_episode", content_id=existing.target.id, owner_id=ctx.owner.id, version=existing.target.version,
                              asset_id=old_asset.id, sale_type="copyright_contact", audit_status="approved", listed=True)
    ctx.db.add(publication)
    await ctx.db.commit()
    ctx.source_revision = 2
    payload = await publish_payload(ctx, existing.project, existing.episodes, series=existing.series)
    response = await post_publish(ctx, existing.project, payload)
    assert response.status_code == 409 and "SOURCE_CHANGED" in response.text
    # Failed request rolls back the savepoint; fetch state again before a new request.
    await ctx.db.refresh(existing.series)
    await ctx.db.refresh(existing.target)
    await ctx.db.refresh(publication)
    await ctx.db.refresh(existing.project)
    await ctx.db.refresh(old_asset)
    for episode in existing.episodes:
        await ctx.db.refresh(episode)
    payload = await publish_payload(ctx, existing.project, existing.episodes, series=existing.series, update=True)
    response = await post_publish(ctx, existing.project, payload)
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == existing.target.id
    assert existing.target.asset_id == old_asset.id and publication.asset_id == old_asset.id
    assert existing.series.listed is False and existing.series.audit_status == "draft"
    assert existing.target.listed is False and publication.listed is False
    assert await ctx.db.scalar(select(func.count()).select_from(Handoff)) == 2


@pytest.mark.parametrize("case", ["version", "asset", "new_task", "blocked", "deleted_series"])
async def test_fenced_bind_never_overwrites_modified_deleted_or_superseded_target(drama_publish_ctx, case):
    ctx = drama_publish_ctx
    existing = await published(ctx)
    candidate = Asset(owner_id=ctx.owner.id, kind="video", filename="new.mp4", content_type="video/mp4", size_bytes=100, object_key=f"marketplace/{uuid.uuid4().hex}.mp4", status="ready")
    ctx.db.add(candidate)
    await ctx.db.flush()
    if case == "version":
        existing.target.version += 1
    elif case == "asset":
        existing.target.asset_id = candidate.id
    elif case == "new_task":
        existing.target.source_snapshot = {**existing.target.source_snapshot, "pending_handoff_id": existing.task.id + 1}
    elif case == "blocked":
        existing.target.blocked = True
    else:
        existing.series.deleted_at = now()
    before = existing.target.asset_id
    await ctx.db.flush()
    with pytest.raises(HTTPException, match="MARKETPLACE_TARGET_CHANGED"):
        await handoff._bind(ctx.db, existing.task, candidate.id, None)
    assert existing.target.asset_id == before


async def test_successful_bind_auto_attaches_authorization_without_approving_rights(drama_publish_ctx):
    ctx = drama_publish_ctx
    existing = await published(ctx)
    ctx.db.add(Authorization(owner_id=ctx.owner.id, template_version=VERSION, signer_name="测试用户", body="terms", body_hash="0"*64,
                             letter_key="marketplace/letter.png", signature_key="marketplace/signature.png", client_ip="127.0.0.1", user_agent="test"))
    candidate = Asset(owner_id=ctx.owner.id, kind="video", filename="new.mp4", content_type="video/mp4", size_bytes=100, object_key="marketplace/new.mp4", status="ready")
    ctx.db.add(candidate)
    await ctx.db.flush()
    existing.task.asset_id = candidate.id
    await handoff._bind(ctx.db, existing.task, candidate.id, None)
    await ctx.db.flush()
    proof = (await ctx.db.execute(select(Rights).where(Rights.asset_id == candidate.id))).scalar_one()
    assert existing.target.asset_id == candidate.id and existing.task.status == "ready"
    assert proof.details["source"] == "printfilm" and int(proof.details["authorization_id"]) > 0
    assert proof.basic_status != "approved" and proof.full_status != "approved"


async def test_source_file_change_is_detected_before_worker_binding(drama_publish_ctx):
    ctx = drama_publish_ctx
    existing = await published(ctx)
    ctx.source_revision += 1
    with pytest.raises(HTTPException, match="MARKETPLACE_SOURCE_CHANGED"):
        await handoff._validate_drama_source(ctx.db, existing.task)
    assert existing.target.asset_id is None


def legacy_v2_snapshot(task):
    """构造升级前真实的完整分集协议，用原算法冻结版本以验证向后兼容。"""
    frozen = {key: value for key, value in task.source_snapshot.items() if key not in (
        "project_cover_locator", "project_cover_stamp", "inherit_series_cover", "series_cover_version")}
    if not any(clip["cover"] for clip in frozen["clips"]):
        frozen["cover_locator"], frozen["cover_stamp"] = "", None
    frozen["source_version"] = drama_publish.digest({"episode": frozen["drama_episode_id"], "title": frozen["title"],
        "episode_number": frozen["episode_number"], "updated_at": frozen["episode_updated_at"],
        "cover_stamp": drama_media.stamp_version(frozen["cover_stamp"]) if frozen["cover_stamp"] else None,
        "clips": [{"id": clip["id"], "sort_order": clip["sort_order"], "updated_at": clip["updated_at"],
                   "stamp": drama_media.stamp_version(clip["stamp"]), "cover": clip["cover"]} for clip in frozen["clips"]]})
    return frozen


@pytest.mark.parametrize("with_images", [True, False])
async def test_legacy_complete_episode_task_remains_retryable_and_reusable(drama_publish_ctx, with_images):
    """升级前的 schema2 完整任务不会仅因新增封面字段就被误判源视频更新。"""
    ctx = drama_publish_ctx
    project, episodes, clips = await source(ctx)
    if not with_images:
        for clip in clips:
            clip.cover = ""
        await ctx.db.commit()
    response = await post_publish(ctx, project, await publish_payload(ctx, project, episodes))
    result = response.json()
    task = await ctx.db.get(Handoff, result["handoffs"][0]["id"])
    series = await ctx.db.get(Series, result["series_id"])
    task.source_snapshot = legacy_v2_snapshot(task)
    task.source_version = task.source_snapshot["source_version"]
    original_version = task.source_version
    task.status, task.error = "failed", "复制成片失败，请稍后重试"
    await ctx.db.commit()
    await handoff._validate_drama_source(ctx.db, task)
    retry = await ctx.client.post(f"/api/marketplace/handoffs/{task.id}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "pending"
    context = (await ctx.client.get(f"/api/marketplace/printfilm/dramas/{project.id}/publish-context")).json()
    mapping = next(item for item in context["series"] if item["id"] == series.id)["imports"][0]
    assert mapping["source_version"] == context["episodes"][0]["source_version"]
    assert mapping["requires_update"] is False
    repeated = await post_publish(ctx, project, await publish_payload(ctx, project, episodes, series=series))
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["handoffs"][0]["id"] == task.id
    assert task.source_version == original_version and "project_cover_stamp" not in task.source_snapshot
    assert await ctx.db.scalar(select(func.count()).select_from(Handoff)) == 1


@pytest.mark.parametrize("changed", ["video_file", "cover_locator"])
async def test_legacy_complete_episode_still_rejects_actual_source_changes(drama_publish_ctx, changed):
    """旧协议兼容不跳过分镜视频文件身份及原有图片封面的真实变化。"""
    ctx = drama_publish_ctx
    existing = await published(ctx)
    existing.task.source_snapshot = legacy_v2_snapshot(existing.task)
    existing.task.source_version = existing.task.source_snapshot["source_version"]
    await ctx.db.commit()
    if changed == "video_file":
        ctx.source_revision += 1
    else:
        existing.clips[-1].cover = "/static/test/replaced-cover.png"
        await ctx.db.commit()
    with pytest.raises(HTTPException, match="MARKETPLACE_SOURCE_CHANGED"):
        await handoff._validate_drama_source(ctx.db, existing.task)


async def test_terminal_same_source_can_be_explicitly_resynced(drama_publish_ctx):
    """源恢复原状后仍能重新确认，不永远复用终止的旧任务。"""
    ctx = drama_publish_ctx
    existing = await published(ctx)
    existing.task.status = "failed"
    existing.task.error = "MARKETPLACE_SOURCE_CHANGED:源分集曾在同步时重新生成"
    await ctx.db.commit()
    context = (await ctx.client.get(f"/api/marketplace/printfilm/dramas/{existing.project.id}/publish-context")).json()
    target = next(row for row in context["series"] if row["id"] == existing.series.id)
    assert target["imports"][0]["requires_update"] is True
    payload = await publish_payload(ctx, existing.project, existing.episodes, series=existing.series, update=True)
    response = await post_publish(ctx, existing.project, payload)
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == existing.target.id
    assert response.json()["handoffs"][0]["id"] != existing.task.id
    assert response.json()["handoffs"][0]["status"] == "pending"
    assert await ctx.db.scalar(select(func.count()).select_from(SeriesEpisode)) == 1


@pytest.mark.parametrize("case", ["success", "source_changed", "target_changed", "lease_stolen", "resume_expired_lease"])
async def test_worker_recovery_and_final_binding_guards(drama_publish_ctx, monkeypatch, case):
    """实际执行领取/阶段/终态；仅替换远端存储与媒体制作，不伪造任务状态。"""
    ctx = drama_publish_ctx
    existing = await published(ctx)
    discarded, produced, phases = [], [], []
    original_phase = handoff._phase

    @asynccontextmanager
    async def sessions():
        # 每个 worker 阶段顺序使用同一测试连接，保持随机 schema 和外层回滚。
        yield ctx.db

    async def phase(handoff_id, token, value):
        phases.append(value)
        return await original_phase(handoff_id, token, value)

    async def prepare_video(snapshot, destination, on_phase):
        assert [item["sort_order"] for item in snapshot["clips"]] == [0, 1, 2]
        produced.append(destination)
        for value in ("copying", "composing", "validating"):
            await on_phase(value)
        if case == "source_changed":
            ctx.source_revision += 1
        elif case == "target_changed":
            existing.target.version += 1
            await ctx.db.commit()
        elif case == "lease_stolen":
            existing.task.lease_token = "other-worker"
            await ctx.db.commit()
        return {"size_bytes": 100, "content_type": "video/mp4", "fingerprint": "f"*64, "duration_seconds": 9.0}

    async def prepare_cover(_locator, destination, _stamp=None):
        produced.append(destination)
        return {"size_bytes": 10, "content_type": "image/png"}

    monkeypatch.setattr(handoff, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(handoff, "_phase", phase)
    monkeypatch.setattr(drama_media, "prepare_drama_video", prepare_video)
    monkeypatch.setattr(drama_media, "prepare_drama_cover", prepare_cover)
    monkeypatch.setattr(storage, "discard_generated", discarded.append)
    if case == "resume_expired_lease":
        existing.task.status, existing.task.lease_token = "running", "dead-worker"
        existing.task.lease_until = now() - timedelta(seconds=1)
        await ctx.db.commit()
    assert await handoff.run_handoff_once() is True
    assert phases == ["copying", "composing", "validating"]
    if case in ("success", "resume_expired_lease"):
        assert existing.task.status == "ready" and existing.target.asset_id is not None
        assert existing.task.lease_token is None and existing.task.lease_until is None
        assert existing.target.cover_asset_id is not None
        assert existing.series.cover_asset_id == existing.target.cover_asset_id
        assert await ctx.db.scalar(select(func.count()).select_from(Asset)) == 2
        assert discarded == []
    else:
        assert existing.target.asset_id is None and existing.target.cover_asset_id is None
        assert await ctx.db.scalar(select(func.count()).select_from(Asset)) == 0
        assert sorted(discarded) == sorted(produced)
        if case == "lease_stolen":
            assert existing.task.lease_token == "other-worker"  # 旧 worker 不得改新租约。
        else:
            assert existing.task.status == "failed" and ("SOURCE_CHANGED" if case == "source_changed" else "TARGET_CHANGED") in existing.task.error
