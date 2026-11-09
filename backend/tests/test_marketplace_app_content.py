"""App 内容、可续期播放和跨环境权益；仅写隔离测试 schema，OSS/Redis 使用测试替身。"""
import copy
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.marketplace import app_access, app_content, app_media, app_playback, storage
from app.marketplace.app_media import compatible_source, discover, media_for
from app.marketplace.app_media_models import AppMedia
from app.marketplace.app_models import AuthorBlock, CoinGrant, CoinUnlock
from app.marketplace.dependencies import optional_user
from app.marketplace.models import (Asset, ContentOrder, Entitlement, EpisodePreview, MarketBase,
    Publication, Rights, Series, SeriesEpisode, Work, WorkPreview)
from conftest import _ensure_test_database, _resolve_test_database_url


class MemorySessions:
    """测试专用短期会话缓存，不作为业务降级实现。"""
    def __init__(self, clock):
        self.clock, self.values = clock, {}

    async def set(self, key, value, ex):
        self.values[key] = (value, self.clock.current + ex)

    async def get(self, key):
        value = self.values.get(key)
        return value[0] if value and value[1] > self.clock.current else None


@pytest_asyncio.fixture
async def app_ctx(monkeypatch):
    """服务端提交只提交 savepoint，最终连 schema 一起回滚。"""
    from app.marketplace.app_schema import register_models
    register_models()
    url, name = _resolve_test_database_url(get_settings().database_url)
    await _ensure_test_database(url, name)
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        outer = await connection.begin()
        schema = f"app_content_test_{uuid.uuid4().hex}"
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection = await connection.execution_options(schema_translate_map={None: schema})
        await connection.run_sync(lambda sync: User.__table__.create(sync))
        await connection.run_sync(MarketBase.metadata.create_all)
        db = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        owner, buyer = User(email="author@app.test", hashed_password="unused"), User(email="viewer@app.test", hashed_password="unused")
        db.add_all([owner, buyer])
        await db.flush()
        ctx = SimpleNamespace(db=db, owner=owner, buyer=buyer, user=None, signed=[], clock=SimpleNamespace(current=100000.0))
        redis = MemorySessions(ctx.clock)
        monkeypatch.setattr(app_playback, "time", SimpleNamespace(time=lambda: ctx.clock.current))
        monkeypatch.setattr(app_playback, "session_store", lambda: redis)
        monkeypatch.setattr(app_access, "app_open", lambda: True)
        monkeypatch.setattr(app_access, "environment", lambda: "Production")
        monkeypatch.setattr(app_playback, "environment", lambda: "Production")
        monkeypatch.setattr(storage, "configured", lambda: True)
        monkeypatch.setattr(storage, "signed", lambda key, content_type: f"https://oss.test/{key}?signed=300")
        monkeypatch.setattr(storage, "read", lambda key: b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n#EXTINF:6.0,\nsegment-00000.ts\n#EXTINF:4.0,\nsegment-00001.ts\n#EXT-X-ENDLIST\n")

        def sign(method, key, expires, **kwargs):
            ctx.signed.append((key, expires))
            return f"https://private.test/{key}?expires={expires}"

        monkeypatch.setattr(storage, "bucket", lambda: SimpleNamespace(sign_url=sign))

        async def session_override():
            yield db

        async def visitor_override():
            return ctx.user

        async def actor_override():
            if not ctx.user:
                raise HTTPException(401, "请登录")
            return ctx.user

        app = FastAPI()
        from app.marketplace.locale_middleware import install_locale
        install_locale(app)
        app.include_router(app_content.router, prefix="/api/marketplace/app/v1")
        app.include_router(app_playback.router, prefix="/api/marketplace/app/v1")
        app.dependency_overrides[get_db] = session_override
        app.dependency_overrides[optional_user] = visitor_override
        app.dependency_overrides[get_current_user] = actor_override
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                ctx.client = client
                yield ctx
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


async def make_work(ctx, sale_type="free", title="App 视频"):
    """创建真实审核状态，免费历史作品故意不创建 Publication。"""
    asset = Asset(owner_id=ctx.owner.id, kind="video", filename="video.mp4", content_type="video/mp4", size_bytes=100,
        duration_seconds=100, object_key=f"marketplace/works/{uuid.uuid4().hex}.mp4", status="ready")
    ctx.db.add(asset)
    await ctx.db.flush()
    proof = Rights(owner_id=ctx.owner.id, asset_id=asset.id, basic_status="approved", full_status="approved",
        details={"source": "external"}, certificate_asset_id=asset.id)
    work = Work(owner_id=ctx.owner.id, title=title, source="external", asset_id=asset.id, sale_type=sale_type,
        price_fen=0, unlock_price_fen=100, audit_status="approved", listed=True)
    ctx.db.add_all([proof, work])
    await ctx.db.flush()
    publication = None
    if sale_type != "free":
        preview = WorkPreview(work_id=work.id, asset_id=asset.id, version=work.version, status="done",
            object_key=f"marketplace/previews-v2/works/{work.id}/preview.mp4")
        publication = Publication(content_type="work", content_id=work.id, owner_id=ctx.owner.id,
            version=work.version, asset_id=asset.id, sale_type=sale_type, unlock_price_fen=100, share_bps=2000,
            audit_status="approved", listed=True, playback_status="done", playback_manifest_key="marketplace/hls/old/index.m3u8")
        ctx.db.add_all([preview, publication])
    for variant in ("full", "preview"):
        ctx.db.add(AppMedia(content_type="work", content_id=work.id, version=work.version, variant=variant,
            asset_id=asset.id, source_key=asset.object_key, status="done", manifest_key=f"marketplace/app-hls/{work.id}/{variant}/index.m3u8"))
    await ctx.db.flush()
    return SimpleNamespace(work=work, asset=asset, rights=proof, publication=publication)


async def session(ctx, **target):
    return await ctx.client.post("/api/marketplace/app/v1/playback-sessions", json=target)


async def test_app_bilingual_categories_feed_and_playback_preserve_business(app_ctx):
    ctx = app_ctx
    item = await make_work(ctx, title="标题保持原文")
    item.work.category = '短片'
    item.work.category_code = 'short_film'
    await ctx.db.flush()
    categories = await ctx.client.get('/api/marketplace/app/v1/categories', headers={'Accept-Language':'en-US'})
    assert categories.status_code == 200 and categories.headers['content-language'] == 'en'
    assert categories.json()['items'][0]['code'] == 'short_film'
    assert categories.json()['items'][0]['label'] == 'Short Film'
    path = '/api/marketplace/app/v1/feed?category_code=short_film&category=广告'
    zh = (await ctx.client.get(path)).json()['items'][0]
    en = (await ctx.client.get(path, headers={'Accept-Language':'en'})).json()['items'][0]
    for key in ('id','title','category_code','sale_type','content_type','publication_id','unlock_coins','is_free','access_mode'):
        assert zh[key] == en[key]
    assert en['category_label'] == 'Short Film' and en['content_type_label'] == 'Video'
    assert en['access_mode_label'] == 'Free full playback'
    created = await ctx.client.post('/api/marketplace/app/v1/playback-sessions', headers={'Accept-Language':'en'}, json={'content_type':'work','content_id':item.work.id})
    assert created.json()['access_mode'] == 'free' and created.json()['access_mode_label'] == 'Free full playback'


@pytest.mark.asyncio
async def test_app_free_legacy_content_plays_complete_without_publication(app_ctx):
    ctx = app_ctx
    item = await make_work(ctx)
    feed = await ctx.client.get("/api/marketplace/app/v1/feed")
    assert feed.status_code == 200
    assert feed.json()["items"][0]["publication_id"] is None
    assert feed.json()["items"][0]["is_free"] is True
    created = await session(ctx, content_type="work", content_id=item.work.id)
    assert created.status_code == 200
    body = created.json()
    assert body["access_mode"] == "free"
    manifest = await ctx.client.get(f"/api/marketplace/app/v1/playback-sessions/{body['session_id']}/index.m3u8")
    assert "segments/0" in manifest.text and "private.test" not in manifest.text
    part = await ctx.client.get(f"/api/marketplace/app/v1/playback-sessions/{body['session_id']}/segments/0")
    assert part.status_code == 302
    assert ctx.signed[-1][1] == 60
    assert "/full/" in ctx.signed[-1][0]


@pytest.mark.asyncio
async def test_app_paid_without_entitlement_only_receives_short_preview(app_ctx):
    ctx = app_ctx
    item = await make_work(ctx, "platform_unlock")
    created = await session(ctx, content_type="work", content_id=item.work.id)
    assert created.json()["access_mode"] == "preview"
    token = created.json()["session_id"]
    result = await ctx.client.get(f"/api/marketplace/app/v1/playback-sessions/{token}/segments/0")
    assert result.status_code == 302
    assert "/preview/" in ctx.signed[-1][0]
    assert item.asset.object_key not in str(result.headers)


@pytest.mark.asyncio
async def test_playback_preparation_status_uses_viewers_access_variant(app_ctx):
    ctx = app_ctx
    item = await make_work(ctx, "platform_unlock")
    full = await media_for(ctx.db, "work", item.work.id, item.work.version, "full")
    full.status = "pending"
    await ctx.db.flush()
    result = await ctx.client.get(f"/api/marketplace/app/v1/works/{item.work.id}")
    assert result.json()["access_mode"] == "preview"
    assert result.json()["playback_ready"] is True
    ctx.user = ctx.buyer
    ctx.db.add(Entitlement(user_id=ctx.buyer.id, publication_id=item.publication.id, active=True))
    await ctx.db.flush()
    result = await ctx.client.get(f"/api/marketplace/app/v1/works/{item.work.id}")
    assert result.json()["access_mode"] == "entitled"
    assert result.json()["playback_ready"] is False


@pytest.mark.asyncio
async def test_discovery_repairs_missing_preview_even_when_full_hls_exists(app_ctx):
    ctx = app_ctx
    item = await make_work(ctx, "platform_unlock")
    await ctx.db.execute(delete(AppMedia).where(AppMedia.content_type == "work",
        AppMedia.content_id == item.work.id, AppMedia.variant == "preview"))
    await discover(ctx.db)
    preview = await media_for(ctx.db, "work", item.work.id, item.work.version, "preview")
    assert preview and preview.status == "pending"
    assert preview.source_key.startswith("marketplace/previews-v2/")


@pytest.mark.asyncio
@pytest.mark.parametrize("replace_task_source", [False, True])
async def test_media_worker_fences_result_without_overwriting_new_content(app_ctx, monkeypatch, replace_task_source):
    """新内容版本不覆盖旧买家的派生物；任务本身被替换时旧结果不得回写。"""
    ctx = app_ctx
    item = await make_work(ctx)
    job = await media_for(ctx.db, "work", item.work.id, item.work.version, "full")
    job.status, job.manifest_key = "pending", None
    await ctx.db.flush()

    @asynccontextmanager
    async def session_factory():
        yield ctx.db

    async def render(snapshot):
        assert snapshot["asset_id"] == item.asset.id and snapshot["version"] == 1
        item.work.version += 1
        if replace_task_source:
            job.source_key = "marketplace/works/replaced.mp4"
        await ctx.db.flush()
        return "marketplace/app-hls/result/index.m3u8"

    monkeypatch.setattr(app_media, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(app_media, "render", render)
    assert await app_media.run_app_media_once()
    await ctx.db.refresh(job)
    assert item.work.version == 2 and job.version == 1
    assert job.status == ("running" if replace_task_source else "done")
    assert job.manifest_key == (None if replace_task_source else "marketplace/app-hls/result/index.m3u8")
    assert await media_for(ctx.db, "work", item.work.id, item.work.version, "full") is None


@pytest.mark.asyncio
async def test_old_purchase_plays_after_update_and_catalog_off_but_revocation_stops(app_ctx, monkeypatch):
    ctx = app_ctx
    item = await make_work(ctx, "platform_unlock")
    ctx.user = ctx.buyer
    entitlement = Entitlement(user_id=ctx.buyer.id, publication_id=item.publication.id, active=True)
    ctx.db.add(entitlement)
    item.work.version += 1
    item.work.listed, item.publication.listed = False, False
    await ctx.db.flush()
    monkeypatch.setattr(app_access, "app_open", lambda: False)
    created = await session(ctx, publication_id=item.publication.id)
    assert created.status_code == 200
    assert created.json()["access_mode"] == "entitled"
    token = created.json()["session_id"]
    entitlement.active = False
    await ctx.db.flush()
    result = await ctx.client.get(f"/api/marketplace/app/v1/playback-sessions/{token}/segments/0")
    assert result.status_code == 403
    assert not ctx.signed


@pytest.mark.asyncio
async def test_author_block_only_filters_discovery_and_preserves_library(app_ctx):
    ctx = app_ctx
    item = await make_work(ctx, "platform_unlock")
    ctx.user = ctx.buyer
    ctx.db.add_all([AuthorBlock(user_id=ctx.buyer.id, author_id=ctx.owner.id),
        Entitlement(user_id=ctx.buyer.id, publication_id=item.publication.id, active=True)])
    await ctx.db.flush()
    assert (await ctx.client.get("/api/marketplace/app/v1/feed")).json()["items"] == []
    assert (await ctx.client.get(f"/api/marketplace/app/v1/works/{item.work.id}")).status_code == 404
    assert len((await ctx.client.get("/api/marketplace/app/v1/me/entitlements")).json()["items"]) == 1


@pytest.mark.asyncio
async def test_feed_omits_copyright_sales_and_live_blocked_or_expired_rights(app_ctx):
    ctx = app_ctx
    good = await make_work(ctx, title="有效")
    blocked = await make_work(ctx, title="封禁")
    expired = await make_work(ctx, title="过期")
    await make_work(ctx, "copyright_contact", "线下版权")
    blocked.work.blocked = True
    expired.rights.valid_until = datetime(2020, 1, 1, tzinfo=timezone.utc)
    good.asset.display_width, good.asset.display_height = 1080, 1920
    await ctx.db.flush()
    result = await ctx.client.get("/api/marketplace/app/v1/feed")
    items = result.json()["items"]
    assert [row["id"] for row in items] == [good.work.id]
    assert items[0]["author"]["id"] == ctx.owner.id
    assert "avatar_url" in items[0]["author"]
    assert items[0]["display_width"] == 1080
    assert items[0]["display_height"] == 1920
    assert items[0]["orientation"] == "portrait"


@pytest.mark.asyncio
async def test_playback_activity_extends_idle_but_not_two_hour_absolute_limit(app_ctx):
    ctx = app_ctx
    item = await make_work(ctx)
    created = await session(ctx, content_type="work", content_id=item.work.id)
    token = created.json()["session_id"]
    url = f"/api/marketplace/app/v1/playback-sessions/{token}/segments/0"
    for _ in range(7):
        ctx.clock.current += 900
        assert (await ctx.client.get(url)).status_code == 302
    ctx.clock.current += 901
    assert (await ctx.client.get(url)).status_code == 401


@pytest.mark.asyncio
async def test_idle_session_expires_and_media_version_change_cannot_reuse_free_token(app_ctx):
    ctx = app_ctx
    item = await make_work(ctx)
    created = await session(ctx, content_type="work", content_id=item.work.id)
    token = created.json()["session_id"]
    item.work.sale_type = "platform_unlock"
    item.work.version += 1
    await ctx.db.flush()
    result = await ctx.client.get(f"/api/marketplace/app/v1/playback-sessions/{token}/segments/0")
    assert result.status_code in (404, 409)
    ctx.clock.current += 1801
    assert (await ctx.client.get(f"/api/marketplace/app/v1/playback-sessions/{token}/segments/0")).status_code == 401


@pytest.mark.asyncio
async def test_sandbox_grants_cannot_authorize_production_playback(app_ctx, monkeypatch):
    ctx = app_ctx
    item = await make_work(ctx, "platform_unlock")
    order = ContentOrder(out_trade_no=uuid.uuid4().hex, user_id=ctx.buyer.id, publication_id=item.publication.id,
        amount_fen=100, pay_type="coins", status="paid", idempotency_key=uuid.uuid4().hex)
    ctx.db.add(order)
    await ctx.db.flush()
    unlock = CoinUnlock(user_id=ctx.buyer.id, environment="Sandbox", order_id=order.id,
        publication_id=item.publication.id, coins=100, amount_fen=100, status="paid", idempotency_key=uuid.uuid4().hex)
    ctx.db.add(unlock)
    await ctx.db.flush()
    ctx.db.add(CoinGrant(user_id=ctx.buyer.id, environment="Sandbox", publication_id=item.publication.id,
        order_id=order.id, unlock_id=unlock.id, active=True))
    await ctx.db.flush()
    ctx.user = ctx.buyer
    assert not await app_access.has_entitlement(ctx.db, ctx.buyer.id, item.publication.id)
    assert (await session(ctx, publication_id=item.publication.id)).status_code == 403
    assert (await ctx.client.get("/api/marketplace/app/v1/me/entitlements")).json()["items"] == []
    monkeypatch.setattr(app_access, "environment", lambda: "Sandbox")
    assert await app_access.has_entitlement(ctx.db, ctx.buyer.id, item.publication.id)
    assert len((await ctx.client.get("/api/marketplace/app/v1/me/entitlements")).json()["items"]) == 1


@pytest.mark.asyncio
async def test_paid_series_free_first_episode_is_not_mistaken_for_paid(app_ctx):
    ctx = app_ctx
    series = Series(owner_id=ctx.owner.id, title="两集短剧", sale_type="platform_unlock", free_episode_count=1,
        audit_status="approved", listed=True)
    ctx.db.add(series)
    await ctx.db.flush()
    for number in (1, 2):
        asset = Asset(owner_id=ctx.owner.id, kind="video", filename="episode.mp4", content_type="video/mp4", size_bytes=100,
            duration_seconds=100, display_width=1920 if number == 1 else 1080, display_height=1080 if number == 1 else 1920,
            object_key=f"marketplace/series/{uuid.uuid4().hex}.mp4", status="ready")
        ctx.db.add(asset)
        await ctx.db.flush()
        episode = SeriesEpisode(owner_id=ctx.owner.id, series_id=series.id, episode_no=number, title=f"第{number}集",
            source="external", asset_id=asset.id, unlock_price_fen=100, audit_status="approved", listed=True)
        ctx.db.add_all([episode, Rights(owner_id=ctx.owner.id, asset_id=asset.id, basic_status="approved", full_status="approved",
            certificate_asset_id=asset.id, details={"source": "external"})])
        await ctx.db.flush()
        if number == 2:
            ctx.db.add(EpisodePreview(episode_id=episode.id, asset_id=asset.id, version=episode.version, status="done",
                object_key=f"marketplace/previews-v2/episodes/{episode.id}/preview.mp4"))
        ctx.db.add(Publication(content_type="series_episode", content_id=episode.id, owner_id=ctx.owner.id,
            version=episode.version, asset_id=asset.id, sale_type="platform_unlock", unlock_price_fen=0 if number == 1 else 100,
            share_bps=2000, audit_status="approved", listed=True))
    await ctx.db.flush()
    feed = await ctx.client.get("/api/marketplace/app/v1/feed")
    assert [row["content_type"] for row in feed.json()["items"]] == ["series"]
    assert feed.json()["items"][0]["orientation"] == "landscape"
    episodes = await ctx.client.get(f"/api/marketplace/app/v1/series/{series.id}/episodes")
    assert episodes.status_code == 200
    rows = episodes.json()["items"]
    assert [row["is_free"] for row in rows] == [True, False]
    assert [row["unlock_coins"] for row in rows] == [0, 100]
    assert [row["orientation"] for row in rows] == ["landscape", "portrait"]


@pytest.mark.asyncio
async def test_cursor_pagination_has_no_duplicate_and_redis_failure_fails_closed(app_ctx, monkeypatch):
    ctx = app_ctx
    for number in range(3):
        await make_work(ctx, title=f"游标{number}")
    first = (await ctx.client.get("/api/marketplace/app/v1/feed?limit=2")).json()
    second = (await ctx.client.get("/api/marketplace/app/v1/feed", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert len({row["id"] for row in first["items"] + second["items"]}) == 3
    assert not second["has_more"]

    class BrokenRedis:
        async def set(self, *args, **kwargs):
            raise ConnectionError("unavailable")

    monkeypatch.setattr(app_playback, "session_store", lambda: BrokenRedis())
    created = await session(ctx, content_type="work", content_id=first["items"][0]["id"])
    assert created.status_code == 503
    assert created.json()["detail"]["code"] == "MARKETPLACE_PLAYBACK_UNAVAILABLE"


def test_missing_or_failed_display_size_stays_null():
    """探测失败写成 0 时，接口仍返回空画幅，不把失败记录当成方形。"""
    assert app_content.video_shape(None) == {"display_width": None, "display_height": None, "orientation": None}
    failed = SimpleNamespace(display_width=0, display_height=0)
    assert app_content.video_shape(failed)["orientation"] is None


@pytest.mark.parametrize("reference", ["https://evil.test/a.ts", "../segment-00000.ts", "/segment-00000.ts", "segment-00000.ts?x=1", "sub/segment-00000.ts", "segment-%2e%2e.ts"])
def test_playlist_rejects_external_and_path_traversal(reference):
    with pytest.raises(HTTPException):
        app_playback.parse_playlist(f"#EXTM3U\n#EXTINF:1,\n{reference}\n#EXT-X-ENDLIST", "marketplace/app-hls/1/token/")


@pytest.mark.parametrize("tag", ['#EXT-X-KEY:METHOD=AES-128,URI="https://evil.test/key"', '#EXT-X-MAP:URI="init.mp4"', "#EXT-X-STREAM-INF:BANDWIDTH=1000"])
def test_playlist_rejects_uri_tags_and_nested_manifests(tag):
    with pytest.raises(HTTPException):
        app_playback.parse_playlist(f"#EXTM3U\n{tag}\nsegment-00000.ts\n#EXT-X-ENDLIST", "marketplace/app-hls/1/token/")


def test_ios_copy_gate_checks_codecs_pixels_audio_and_rotation():
    probe = {"streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"}, {"codec_type": "audio", "codec_name": "aac"}]}
    assert compatible_source(probe)
    for patch in ({"codec_name": "vp9"}, {"pix_fmt": "yuv420p10le"}, {"side_data_list": [{"rotation": 90}]}):
        changed = copy.deepcopy(probe)
        changed["streams"][0].update(patch)
        assert not compatible_source(changed)
    probe["streams"][1]["codec_name"] = "opus"
    assert not compatible_source(probe)


def test_cursor_tampering_and_invalid_target_are_rejected():
    cursor = app_content.encode_cursor(datetime.now(timezone.utc), "work", 20)
    assert app_content.decode_cursor(cursor)[1:] == ("work", 20)
    with pytest.raises(HTTPException):
        app_content.decode_cursor(cursor[:-8] + "abcdefgh")
    with pytest.raises(ValueError):
        app_playback.PlaybackInput(content_type="work", content_id=1, publication_id=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["work", "series_episode"])
async def test_purchased_detail_and_list_share_live_social_without_changing_version(app_ctx, monkeypatch, kind):
    from app.marketplace.app_social_models import AppContentStats, AppLike, AppFavorite, AppSocialSetting
    from app.marketplace.app_engagement_models import MetricsBaseline
    from app.marketplace.app_settings import get_app_settings
    ctx = app_ctx
    content = await make_work(ctx, "platform_unlock")
    item = content.work
    if kind == "series_episode":
        parent = Series(owner_id=ctx.owner.id, title="series", sale_type="platform_unlock", audit_status="approved", listed=True)
        ctx.db.add(parent)
        await ctx.db.flush()
        item = SeriesEpisode(owner_id=ctx.owner.id, series_id=parent.id, episode_no=2, title="episode", source="external", asset_id=content.asset.id,
                             audit_status="approved", listed=True, unlock_price_fen=100)
        ctx.db.add(item)
        await ctx.db.flush()
        content.publication.content_type, content.publication.content_id = kind, item.id
        ctx.db.add(EpisodePreview(episode_id=item.id, asset_id=content.asset.id, version=1, status="done",
            object_key=f"marketplace/previews-v2/episodes/{item.id}/preview.mp4"))
        ctx.db.add(AppMedia(content_type=kind, content_id=item.id, version=1, variant="full", asset_id=content.asset.id,
            source_key=content.asset.object_key, status="done", manifest_key="marketplace/app-hls/episode/full/index.m3u8"))
    ctx.user = ctx.buyer
    ctx.owner.nickname, ctx.owner.avatar_url = "视频作者", "https://example.com/avatar.png"
    stored = "episode" if kind == "series_episode" else kind
    ctx.db.add_all([
        Entitlement(user_id=ctx.buyer.id, publication_id=content.publication.id, active=True),
        AppContentStats(target_type=stored, target_id=item.id, like_count=7, favorite_count=3, comment_count=2, share_count=1),
        MetricsBaseline(target_type=stored, target_id=item.id, like_count=6000, favorite_count=3000, share_count=900),
        AppLike(target_type=stored, target_id=item.id, user_id=ctx.buyer.id),
        AppFavorite(target_type=stored, target_id=item.id, user_id=ctx.buyer.id),
        AppSocialSetting(target_type=stored, target_id=item.id, comments_enabled=True),
    ])
    monkeypatch.setattr(get_app_settings(), "social_enabled", True)
    monkeypatch.setattr(get_app_settings(), "comments_enabled", True)
    await ctx.db.flush()
    path = f"/api/marketplace/app/v1/me/entitlements/{content.publication.id}"
    response = await ctx.client.get(path)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["engagement"] == {"like_count": 6007, "favorite_count": 3003, "share_count": 901,
                                    "comment_count": 2, "liked_by_me": True, "favorited_by_me": True}
    assert detail["creator"] == {"id": ctx.owner.id, "name": "视频作者", "avatar_url": "https://example.com/avatar.png"}
    assert detail["social"] == {"comments_enabled": True, "interaction_available": True}
    assert detail["id"] == detail["content_id"] == item.id and detail["content_type"] == kind
    assert detail["playback_ready"] and detail["version"] == 1
    listing = (await ctx.client.get("/api/marketplace/app/v1/me/entitlements")).json()["items"]
    assert listing == [detail]
    # 已购版本继续播放旧媒体，不因内容升级、下架、屏蔽或发现入口关闭而依赖公开详情。
    item.version = 2
    item.listed = False
    ctx.db.add(AuthorBlock(user_id=ctx.buyer.id, author_id=ctx.owner.id))
    await ctx.db.flush()
    monkeypatch.setattr(app_content, "app_open", lambda: False)
    monkeypatch.setattr(app_access, "app_open", lambda: False)
    old = (await ctx.client.get(path, headers={"Accept-Language": "en"})).json()
    assert old["version"] == 1 and old["playback_ready"] and old["access_mode"] == "entitled"
    assert old["engagement"] == detail["engagement"] and not old["social"]["interaction_available"]
    assert not old["social"]["comments_enabled"]
    assert (await session(ctx, publication_id=content.publication.id)).status_code == 200
    # 实时封禁禁止播放并隐藏互动；不删除历史购买记录。
    item.blocked = True
    await ctx.db.flush()
    restricted = (await ctx.client.get(path)).json()
    assert restricted["restricted_reason"] and not restricted["playback_ready"]
    assert restricted["engagement"]["like_count"] == 0 and not restricted["engagement"]["liked_by_me"]
    assert not restricted["social"]["interaction_available"]
    assert (await session(ctx, publication_id=content.publication.id)).status_code == 403
    assert "object_key" not in response.text and "share_bps" not in response.text


@pytest.mark.asyncio
async def test_purchased_detail_requires_own_active_environment_entitlement(app_ctx, monkeypatch):
    ctx = app_ctx
    content = await make_work(ctx, "platform_unlock")
    path = f"/api/marketplace/app/v1/me/entitlements/{content.publication.id}"
    assert (await ctx.client.get(path)).status_code == 401
    ctx.user = ctx.buyer
    assert (await ctx.client.get(path)).status_code == 403
    assert (await ctx.client.get("/api/marketplace/app/v1/me/entitlements/99999999")).status_code == 403
    order = ContentOrder(out_trade_no=uuid.uuid4().hex, user_id=ctx.buyer.id, publication_id=content.publication.id,
        amount_fen=100, pay_type="platform_balance", status="paid", idempotency_key=uuid.uuid4().hex)
    ctx.db.add(order)
    await ctx.db.flush()
    unlock = CoinUnlock(user_id=ctx.buyer.id, environment="Sandbox", order_id=order.id,
        publication_id=content.publication.id, coins=100, amount_fen=100, status="paid", idempotency_key=uuid.uuid4().hex)
    ctx.db.add(unlock)
    await ctx.db.flush()
    grant = CoinGrant(user_id=ctx.buyer.id, environment="Sandbox", publication_id=content.publication.id,
        order_id=order.id, unlock_id=unlock.id, active=True)
    ctx.db.add(grant)
    await ctx.db.flush()
    assert (await ctx.client.get(path)).status_code == 403
    monkeypatch.setattr(app_access, "environment", lambda: "Sandbox")
    assert (await ctx.client.get(path)).status_code == 200
    grant.active = False
    await ctx.db.flush()
    assert (await ctx.client.get(path)).status_code == 403
    assert (await ctx.client.get("/api/marketplace/app/v1/me/entitlements")).json()["items"] == []
