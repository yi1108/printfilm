"""隔离 SQLite 事务验证互动运营与分享，不连接业务库或 OSS。"""
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.marketplace import app_engagement as engagement, app_sharing, app_social
from app.marketplace.app_engagement_models import (EngagementMaintenance, MetricsAudit, MetricsBaseline,
    MetricsInitializationJob, ShareCredit, ShareEvent, ShareLink, ShareSession)
from app.marketplace.app_social_models import AppComment, AppContentStats, AppFavorite, AppLike, AppSocialSetting
from app.marketplace.models import Asset, MarketBase, Work


class AsyncSQLite:
    """使用实际 SQLAlchemy/SQLite 唯一约束，异步外观仅避免新增数据库驱动。"""
    def __init__(self, session):
        self.session, self.bind = session, session.bind

    async def execute(self, statement): return self.session.execute(statement)
    async def scalar(self, statement): return self.session.scalar(statement)
    async def scalars(self, statement): return self.session.scalars(statement)
    async def get(self, model, key): return self.session.get(model, key)
    async def flush(self): self.session.flush()
    async def commit(self): self.session.commit()
    async def delete(self, row): self.session.delete(row)
    def add(self, row): self.session.add(row)

    @asynccontextmanager
    async def begin_nested(self):
        with self.session.begin_nested():
            yield


@pytest.fixture
def ctx(monkeypatch):
    engine = create_engine("sqlite://")
    tables = [Asset.__table__, Work.__table__, AppContentStats.__table__, AppLike.__table__, AppFavorite.__table__,
        AppComment.__table__, AppSocialSetting.__table__, MetricsBaseline.__table__, MetricsAudit.__table__,
        MetricsInitializationJob.__table__, ShareSession.__table__, ShareLink.__table__, ShareEvent.__table__,
        ShareCredit.__table__, EngagementMaintenance.__table__]
    MarketBase.metadata.create_all(engine, tables=tables)
    session = Session(engine, expire_on_commit=False)
    db = AsyncSQLite(session)
    work = Work(owner_id=7, title="公开作品", description="介绍", price_fen=0, sale_type="free", listed=True, audit_status="approved")
    session.add(work)
    session.commit()
    user = SimpleNamespace(id=9)
    config = SimpleNamespace(social_initialization_enabled=True, sharing_enabled=True, comments_enabled=True,
        share_base_url="https://share.example.com", share_apple_team_id="ABCDE12345", share_bundle_id="com.deep.printfilm")

    async def current(db, kind, target_id, user_id=None):
        if not work.listed:
            raise HTTPException(404, {"code": "MARKETPLACE_CONTENT_UNAVAILABLE", "message": "已下架"})
        return work, work, None, None, True

    async def target(db, kind, target_id, user_id=None):
        await current(db, kind, target_id, user_id)
        return kind, work

    async def cover(db, asset_id): return "https://cover.example.com/image.jpg"

    monkeypatch.setattr(engagement, "current_content", current)
    monkeypatch.setattr(app_sharing, "current_content", current)
    monkeypatch.setattr(app_social, "_target", target)
    monkeypatch.setattr("app.marketplace.app_content.cover_url", cover)
    monkeypatch.setattr("app.marketplace.app_settings.get_app_settings", lambda: config)
    monkeypatch.setattr(app_sharing, "get_app_settings", lambda: config)
    monkeypatch.setattr(app_sharing, "require_app_open", lambda: None)
    monkeypatch.setattr("app.marketplace.app_access.app_open", lambda: True)
    result = SimpleNamespace(db=db, session=session, work=work, user=user, config=config)
    yield result
    session.close()
    engine.dispose()


def test_random_initial_counts_have_feasible_strict_order():
    for _ in range(500):
        values = engagement.generated_baseline()
        assert 2001 <= values["like_count"] <= 12000
        assert 2000 <= values["favorite_count"] <= 5000
        assert 500 <= values["share_count"] <= 3000
        assert values["share_count"] < values["favorite_count"] < values["like_count"]


@pytest.mark.asyncio
async def test_initialization_adjustment_and_clear_never_reseed(ctx):
    assert await engagement.initialize_target(ctx.db, "work", ctx.work.id)
    first = await engagement.metrics_record(ctx.db, "work", ctx.work.id)
    assert not await engagement.initialize_target(ctx.db, "work", ctx.work.id)
    cleared = await engagement.adjust_metrics(ctx.db, "work", ctx.work.id, version=first["version"], reason="恢复真实数量",
        desired={}, clear=True, operator_id=1)
    assert cleared["initial"] == dict.fromkeys(engagement.COUNT_KEYS, 0)
    assert not await engagement.initialize_target(ctx.db, "work", ctx.work.id)
    with pytest.raises(HTTPException) as exc:
        await engagement.adjust_metrics(ctx.db, "work", ctx.work.id, version=first["version"], reason="旧版本",
            desired=dict.fromkeys(engagement.COUNT_KEYS, 100), clear=False, operator_id=1)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_like_unlike_are_idempotent_and_return_combined_counts(ctx):
    await engagement.initialize_target(ctx.db, "work", ctx.work.id)
    initial = await engagement.totals(ctx.db, "work", ctx.work.id)
    liked = await app_social._mutate(ctx.db, ctx.user, "works", ctx.work.id, AppLike, True)
    again = await app_social._mutate(ctx.db, ctx.user, "work", ctx.work.id, AppLike, True)
    assert liked["like_count"] == again["like_count"] == initial["like_count"] + 1
    assert liked["liked_by_me"] is True
    assert liked["share_count"] == initial["share_count"]
    unliked = await app_social._mutate(ctx.db, ctx.user, "works", ctx.work.id, AppLike, False)
    duplicate = await app_social._mutate(ctx.db, ctx.user, "work", ctx.work.id, AppLike, False)
    assert unliked["like_count"] == duplicate["like_count"] == initial["like_count"]
    assert not unliked["liked_by_me"]


@pytest.mark.asyncio
async def test_admin_totals_cannot_underwrite_real_interactions(ctx):
    await app_social._mutate(ctx.db, ctx.user, "work", ctx.work.id, AppFavorite, True)
    with pytest.raises(HTTPException) as exc:
        await engagement.adjust_metrics(ctx.db, "work", ctx.work.id, version=0, reason="不允许抹掉真实收藏",
            desired=dict.fromkeys(engagement.COUNT_KEYS, 0), clear=False, operator_id=1)
    assert exc.value.status_code == 422
    record = await engagement.adjust_metrics(ctx.db, "work", ctx.work.id, version=0, reason="运营展示",
        desired=dict.fromkeys(engagement.COUNT_KEYS, 500), clear=False, operator_id=1)
    assert record["display"] == dict.fromkeys(engagement.COUNT_KEYS, 500)
    assert record["real"]["favorite_count"] == 1
    assert record["initial"]["favorite_count"] == 499


@pytest.mark.asyncio
async def test_share_completion_copy_dedup_and_cancel(ctx):
    await engagement.initialize_target(ctx.db, "work", ctx.work.id)
    initial = (await engagement.totals(ctx.db, "work", ctx.work.id))["share_count"]
    first = await app_sharing.create_share_session("works", ctx.work.id, app_sharing.ShareInput(), ctx.db, ctx.user)
    assert first["url"].startswith("https://share.example.com/s/")
    assert "object_key" not in first and "manifest" not in first
    body = app_sharing.ShareEventInput(action="completed")
    event = await app_sharing.finish_share_session(first["token"], body, ctx.db, ctx.user)
    retry = await app_sharing.finish_share_session(first["token"], body, ctx.db, ctx.user)
    assert event["share_count"] == retry["share_count"] == initial + 1
    second = await app_sharing.create_share_session("works", ctx.work.id, app_sharing.ShareInput(), ctx.db, ctx.user)
    copy = await app_sharing.finish_share_session(second["token"], app_sharing.ShareEventInput(action="copied"), ctx.db, ctx.user)
    assert copy["share_count"] == initial + 1 and copy["counted"] is False
    third = await app_sharing.create_share_session("works", ctx.work.id, app_sharing.ShareInput(), ctx.db, ctx.user)
    cancel = await app_sharing.finish_share_session(third["token"], app_sharing.ShareEventInput(action="cancelled"), ctx.db, ctx.user)
    assert cancel["share_count"] == initial + 1 and not cancel["counted"]
    assert ctx.session.scalar(select(func.count()).select_from(ShareEvent)) == 1


@pytest.mark.asyncio
async def test_share_expiry_identity_and_visibility_are_rechecked(ctx):
    guest = "anonymous_installation_123"
    created = await app_sharing.create_share_session("works", ctx.work.id, app_sharing.ShareInput(anonymous_id=guest), ctx.db, None)
    with pytest.raises(HTTPException) as exc:
        await app_sharing.finish_share_session(created["token"], app_sharing.ShareEventInput(action="completed", anonymous_id="another_installation_123"), ctx.db, None)
    assert exc.value.status_code == 404
    ctx.work.listed = False
    with pytest.raises(HTTPException) as exc:
        await app_sharing.finish_share_session(created["token"], app_sharing.ShareEventInput(action="completed", anonymous_id=guest), ctx.db, None)
    assert exc.value.status_code == 404
    ctx.work.listed = True
    row = ctx.session.scalar(select(ShareSession))
    row.expires_at = engagement.utcnow() - timedelta(seconds=1)
    ctx.session.flush()
    with pytest.raises(HTTPException) as exc:
        await app_sharing.finish_share_session(created["token"], app_sharing.ShareEventInput(action="completed", anonymous_id=guest), ctx.db, None)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_missing_share_configuration_does_not_create_fake_sessions(ctx):
    ctx.config.share_base_url = "http://192.168.1.2"
    with pytest.raises(HTTPException) as exc:
        await app_sharing.create_share_session("works", ctx.work.id, app_sharing.ShareInput(), ctx.db, ctx.user)
    assert exc.value.status_code == 503
    assert ctx.session.scalar(select(func.count()).select_from(ShareSession)) == 0


@pytest.mark.asyncio
async def test_reconciliation_only_rewrites_real_counts(ctx):
    await engagement.initialize_target(ctx.db, "work", ctx.work.id)
    baseline = await engagement.baseline_for(ctx.db, "work", ctx.work.id)
    original = engagement.counts(baseline)
    stats = await engagement.lock_stats(ctx.db, "work", ctx.work.id)
    stats.like_count, stats.favorite_count, stats.share_count = 800, 700, 600
    ctx.session.add(EngagementMaintenance(key="reconcile", cursor=0, updated_at=engagement.utcnow() - timedelta(hours=1)))
    await ctx.db.flush()
    await engagement.reconcile_batch(ctx.db)
    assert engagement.counts(stats) == dict.fromkeys(engagement.COUNT_KEYS, 0)
    assert engagement.counts(baseline) == original


@pytest.mark.asyncio
async def test_first_maintenance_creates_and_persists_reconciliation_state(ctx):
    stats = await engagement.lock_stats(ctx.db, "work", ctx.work.id)
    stats.like_count = 40
    await ctx.db.flush()
    await engagement.reconcile_batch(ctx.db)
    assert stats.like_count == 0
    assert ctx.session.scalar(select(EngagementMaintenance.id)) is not None


@pytest.mark.asyncio
async def test_initialization_job_restarts_from_saved_progress_without_reseeding(ctx):
    job = MetricsInitializationJob(operator_id=1, reason="测试补齐", status="running", lease_until=engagement.utcnow() - timedelta(seconds=1),
        targets=[{"target_type": "work", "target_id": ctx.work.id}, {"target_type": "work", "target_id": ctx.work.id}], total=2)
    ctx.session.add(job)
    await ctx.db.commit()
    assert await engagement.run_initialization_batch(ctx.db, batch_size=1)
    assert job.processed == 1 and job.initialized == 1
    original = engagement.counts(await engagement.baseline_for(ctx.db, "work", ctx.work.id))
    assert await engagement.run_initialization_batch(ctx.db, batch_size=1)
    assert job.status == "done" and job.processed == 2 and job.skipped == 1
    assert engagement.counts(await engagement.baseline_for(ctx.db, "work", ctx.work.id)) == original


@pytest.mark.asyncio
async def test_automatic_initialization_skips_app_closed_and_copyright_only_works(ctx, monkeypatch):
    monkeypatch.setattr("app.marketplace.app_access.app_open", lambda: False)
    assert not await engagement.initialize_target(ctx.db, "work", ctx.work.id, automatic=True)
    monkeypatch.setattr("app.marketplace.app_access.app_open", lambda: True)

    async def copyright_only(*args, **kwargs):
        raise HTTPException(404, {"code": "MARKETPLACE_CONTENT_UNAVAILABLE", "message": "版权出售不收录App"})

    monkeypatch.setattr(engagement, "current_content", copyright_only)
    assert not await engagement.initialize_target(ctx.db, "work", ctx.work.id, automatic=True)
    assert await engagement.baseline_for(ctx.db, "work", ctx.work.id) is None
    with pytest.raises(HTTPException):
        await engagement.initialize_target(ctx.db, "work", ctx.work.id)


def http_app(ctx):
    from app.database import get_db
    from app.deps import get_current_admin
    from app.marketplace.dependencies import optional_user
    from app.marketplace import metrics_admin
    app = FastAPI()
    app.include_router(app_sharing.router, prefix="/api/marketplace/app/v1")
    app.include_router(app_sharing.public_router)
    app.include_router(metrics_admin.router, prefix="/api/admin/marketplace/app")

    async def db_override(): yield ctx.db
    async def visitor(): return getattr(ctx, "http_user", None)
    async def admin():
        actor = getattr(ctx, "http_user", None)
        if actor is None:
            raise HTTPException(401, "请登录")
        if getattr(actor, "role", "user") != "admin":
            raise HTTPException(403, "仅管理员可操作")
        return actor

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[optional_user] = visitor
    app.dependency_overrides[get_current_admin] = admin
    return app


@pytest.mark.asyncio
async def test_http_guest_sharing_admin_permissions_and_cancel(ctx):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app(ctx)), base_url="https://share.example.com") as client:
        missing = await client.post(f"/api/marketplace/app/v1/works/{ctx.work.id}/share-sessions", json={})
        assert missing.status_code == 422
        created = await client.post(f"/api/marketplace/app/v1/works/{ctx.work.id}/share-sessions", json={"anonymous_id": "guest_installation_123"})
        assert created.status_code == 200
        token = created.json()["token"]
        cancelled = await client.post(f"/api/marketplace/app/v1/share-sessions/{token}/events", json={"anonymous_id": "guest_installation_123", "action": "cancelled"})
        assert cancelled.status_code == 200 and cancelled.json()["counted"] is False
        assert ctx.session.scalar(select(func.count()).select_from(ShareEvent)) == 0
        anon = await client.get("/api/admin/marketplace/app/social/metrics")
        assert anon.status_code == 401
        ctx.http_user = SimpleNamespace(id=9, role="user")
        denied = await client.patch(f"/api/admin/marketplace/app/social/metrics/work/{ctx.work.id}", json={"version": 0, "reason": "越权", "like_count": 100})
        assert denied.status_code == 403
        ctx.http_user = SimpleNamespace(id=1, role="admin")
        allowed = await client.patch(f"/api/admin/marketplace/app/social/metrics/work/{ctx.work.id}", json={"version": 0, "reason": "运营设置", "like_count": 100})
        assert allowed.status_code == 200 and allowed.json()["display"]["like_count"] == 100
        malformed = await client.patch(f"/api/admin/marketplace/app/social/metrics/work/{ctx.work.id}", json={"version": 1, "reason": "非法小数", "like_count": 1.2})
        assert malformed.status_code == 422


@pytest.mark.asyncio
async def test_http_link_opens_exact_episode_and_aasa_never_exposes_media(ctx, monkeypatch):
    episode = SimpleNamespace(id=321, series_id=123)

    async def episode_content(*args, **kwargs): return episode, None, None, None, True

    monkeypatch.setattr(app_sharing, "current_content", episode_content)
    ctx.session.add(ShareLink(public_id="episode_link", target_type="episode", target_id=321))
    await ctx.db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=http_app(ctx)), base_url="https://share.example.com") as client:
        opened = await client.get("/s/episode_link", follow_redirects=False)
        assert opened.status_code == 302
        assert opened.headers["location"] == "https://share.example.com/marketplace/series/123?episode_id=321"
        assert opened.headers["cache-control"] == "no-store"
        association = await client.get("/.well-known/apple-app-site-association")
        assert association.status_code == 200
        assert association.json()["applinks"]["details"] == [{"appID": "ABCDE12345.com.deep.printfilm", "paths": ["/s/*"]}]
        assert "manifest" not in association.text and "object_key" not in association.text
