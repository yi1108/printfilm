"""真实 PostgreSQL 多连接互动测试；只提交到派生测试库中的随机隔离 schema。"""
import asyncio
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import User
from app.marketplace import app_engagement as engagement, app_sharing, app_social
from app.marketplace.app_engagement_models import MetricsAudit, MetricsBaseline, ShareCredit, ShareEvent, ShareSession
from app.marketplace.app_schema import register_models
from app.marketplace.app_social_models import AppContentStats, AppLike
from app.marketplace.models import MarketBase
from conftest import _ensure_test_database, _resolve_test_database_url
from test_marketplace_app_content import make_work


@pytest_asyncio.fixture
async def engagement_pg(monkeypatch):
    """每个会话使用独立 PostgreSQL 连接，提交对其他会话真实可见。"""
    url, name = _resolve_test_database_url(get_settings().database_url)
    assert "test" in name
    await _ensure_test_database(url, name)
    schema = f"engagement_test_{uuid.uuid4().hex}"
    engine = create_async_engine(url, pool_size=16, max_overflow=0)
    register_models()
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with scoped.begin() as connection:
            await connection.run_sync(User.__table__.create)
            await connection.run_sync(MarketBase.metadata.create_all)
        factory = async_sessionmaker(scoped, expire_on_commit=False)
        config = SimpleNamespace(sharing_enabled=True, social_initialization_enabled=True, comments_enabled=True,
            share_base_url="https://share.example.com", share_apple_team_id="ABCDE12345", share_bundle_id="com.deep.printfilm")
        monkeypatch.setattr("app.marketplace.app_access.app_open", lambda: True)
        monkeypatch.setattr("app.marketplace.app_settings.get_app_settings", lambda: config)
        monkeypatch.setattr(app_sharing, "get_app_settings", lambda: config)
        async with factory() as db:
            owner = User(email=f"author-{uuid.uuid4().hex}@test.invalid", hashed_password="unused")
            user = User(email=f"viewer-{uuid.uuid4().hex}@test.invalid", hashed_password="unused")
            db.add_all([owner, user])
            await db.flush()
            ctx = SimpleNamespace(db=db, owner=owner, user=user, factory=factory, schema=schema)
            content = await make_work(ctx)
            ctx.work_id = content.work.id
            await db.commit()
            yield ctx
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def parallel(ctx, callbacks):
    """真实并发开始，保留 PostgreSQL 锁并设置明确超时防止挂住测试。"""
    barrier, pids = asyncio.Barrier(len(callbacks)), []

    async def execute(callback):
        async with ctx.factory() as db:
            await db.execute(text("SET LOCAL lock_timeout = '4s'"))
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))
            pids.append(await db.scalar(text("SELECT pg_backend_pid()")))
            await barrier.wait()
            result = await callback(db)
            await db.commit()
            return result

    tasks = [asyncio.create_task(execute(callback)) for callback in callbacks]
    try:
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=12)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert len(set(pids)) == len(callbacks), "必须使用不同 PostgreSQL backend PID，不能把同一连接当成并发"
    return results


@pytest.mark.asyncio
async def test_pg_simultaneous_initialization_creates_one_baseline_and_audit(engagement_pg, monkeypatch):
    ctx = engagement_pg
    # 让两连接都先读到无初始值，再争用真实统计锁/唯一约束。
    barrier, original = asyncio.Barrier(2), engagement.baseline_for
    seen = set()

    async def read_missing_before_lock(db, kind, target_id):
        result = await original(db, kind, target_id)
        if db not in seen:
            seen.add(db)
            assert result is None
            await barrier.wait()
        return result

    monkeypatch.setattr(engagement, "baseline_for", read_missing_before_lock)

    async def initialize(db):
        return await engagement.initialize_target(db, "work", ctx.work_id)

    results = await parallel(ctx, [initialize, initialize])
    assert sorted(results) == [False, True]
    async with ctx.factory() as db:
        assert await db.scalar(select(func.count()).select_from(MetricsBaseline)) == 1
        assert await db.scalar(select(func.count()).select_from(MetricsAudit)) == 1
        stats = await db.scalar(select(AppContentStats))
        assert engagement.counts(stats) == dict.fromkeys(engagement.COUNT_KEYS, 0)
        baseline = await db.scalar(select(MetricsBaseline))
        assert baseline.share_count < baseline.favorite_count < baseline.like_count


@pytest.mark.asyncio
async def test_pg_same_user_concurrent_likes_are_one_real_record_and_same_total(engagement_pg, monkeypatch):
    ctx = engagement_pg
    await engagement.initialize_target(ctx.db, "work", ctx.work_id)
    initial = await engagement.totals(ctx.db, "work", ctx.work_id)
    await ctx.db.commit()
    barrier, original = asyncio.Barrier(2), app_social.lock_stats

    async def simultaneous_lock(db, kind, target_id):
        await barrier.wait()
        return await original(db, kind, target_id)

    monkeypatch.setattr(app_social, "lock_stats", simultaneous_lock)

    async def like(db):
        return await app_social._mutate(db, ctx.user, "works", ctx.work_id, AppLike, True)

    results = await parallel(ctx, [like, like])
    assert all(result["liked_by_me"] is True for result in results)
    assert [result["like_count"] for result in results] == [initial["like_count"] + 1] * 2
    async with ctx.factory() as db:
        assert await db.scalar(select(func.count()).select_from(AppLike)) == 1
        stats = await db.scalar(select(AppContentStats))
        assert stats.like_count == 1
        assert (await engagement.totals(db, "work", ctx.work_id))["like_count"] == initial["like_count"] + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("same_session", [True, False])
async def test_pg_share_callbacks_dedupe_same_session_and_distinct_sessions_in_24h(engagement_pg, monkeypatch, same_session):
    ctx = engagement_pg
    await engagement.initialize_target(ctx.db, "work", ctx.work_id)
    initial = (await engagement.totals(ctx.db, "work", ctx.work_id))["share_count"]
    first = await app_sharing.create_share_session("works", ctx.work_id, app_sharing.ShareInput(), ctx.db, ctx.user)
    second = first if same_session else await app_sharing.create_share_session("works", ctx.work_id, app_sharing.ShareInput(), ctx.db, ctx.user)
    barrier, original = asyncio.Barrier(2), app_sharing.lock_stats

    async def simultaneous_lock(db, kind, target_id):
        await barrier.wait()
        return await original(db, kind, target_id)

    monkeypatch.setattr(app_sharing, "lock_stats", simultaneous_lock)

    def complete(token):
        async def callback(db):
            return await app_sharing.finish_share_session(token, app_sharing.ShareEventInput(action="completed"), db, ctx.user)
        return callback

    results = await parallel(ctx, [complete(first["token"]), complete(second["token"])])
    assert [result["share_count"] for result in results] == [initial + 1] * 2
    if not same_session:
        assert sorted(result["counted"] for result in results) == [False, True]
    async with ctx.factory() as db:
        assert await db.scalar(select(func.count()).select_from(ShareEvent)) == 1
        assert await db.scalar(select(func.count()).select_from(ShareCredit)) == 1
        assert (await db.scalar(select(AppContentStats))).share_count == 1


@pytest.mark.asyncio
async def test_pg_same_identity_concurrent_session_creation_enforces_exact_minute_limit(engagement_pg):
    ctx = engagement_pg

    async def create(db):
        try:
            result = await app_sharing.create_share_session("works", ctx.work_id, app_sharing.ShareInput(), db, ctx.user)
            return {"status": 200, "token": result["token"]}
        except HTTPException as exc:
            return {"status": exc.status_code, "code": exc.detail["code"]}

    # Twelve requests really start on twelve separate PostgreSQL connections.
    # The identity advisory lock must make quota check + insert indivisible.
    results = await parallel(ctx, [create] * 12)
    assert [result["status"] for result in results].count(200) == 10
    rejected = [result for result in results if result["status"] != 200]
    assert len(rejected) == 2
    assert all(result == {"status": 429, "code": "MARKETPLACE_SHARE_RATE_LIMITED"} for result in rejected)
    assert len({result["token"] for result in results if result["status"] == 200}) == 10
    async with ctx.factory() as db:
        assert await db.scalar(select(func.count()).select_from(ShareSession)) == 10


@pytest.mark.asyncio
async def test_pg_series_cannot_receive_initial_metrics_even_without_a_series_row(engagement_pg):
    ctx = engagement_pg
    async with ctx.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await engagement.adjust_metrics(db, "series", 987654321, version=0, reason="系列不应具有初始值",
                desired=dict.fromkeys(engagement.COUNT_KEYS, 1000), clear=False, operator_id=ctx.owner.id)
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "MARKETPLACE_METRICS_TARGET_INVALID"
        assert await db.scalar(select(func.count()).select_from(MetricsBaseline)) == 0
        assert await db.scalar(select(func.count()).select_from(MetricsAudit)) == 0
        assert await db.scalar(select(func.count()).select_from(AppContentStats)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("first_writer", ["adjust", "like"])
async def test_pg_admin_adjustment_and_real_like_use_same_lock_order(engagement_pg, monkeypatch, first_writer):
    ctx = engagement_pg
    await engagement.initialize_target(ctx.db, "work", ctx.work_id)
    before = await engagement.metrics_record(ctx.db, "work", ctx.work_id)
    await ctx.db.commit()
    locked, release, attempted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = engagement.lock_stats
    pids = {}

    async def inspect_lock(db, kind, target_id):
        name = db.info["writer"]
        if name != first_writer:
            attempted.set()
        row = await original(db, kind, target_id)
        if name == first_writer:
            locked.set()
            await release.wait()
        return row

    monkeypatch.setattr(engagement, "lock_stats", inspect_lock)
    monkeypatch.setattr(app_social, "lock_stats", inspect_lock)

    async def write(name):
        async with ctx.factory() as db:
            db.info["writer"] = name
            await db.execute(text("SET LOCAL lock_timeout = '4s'"))
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))
            pids[name] = await db.scalar(text("SELECT pg_backend_pid()"))
            if name == "like":
                result = await app_social._mutate(db, ctx.user, "work", ctx.work_id, AppLike, True)
            else:
                result = await engagement.adjust_metrics(db, "work", ctx.work_id, version=before["version"], reason="并发运营调数",
                    desired=dict.fromkeys(engagement.COUNT_KEYS, 20000), clear=False, operator_id=ctx.owner.id)
            await db.commit()
            return result

    second_writer = "like" if first_writer == "adjust" else "adjust"
    tasks = [asyncio.create_task(write(first_writer))]
    try:
        await asyncio.wait_for(locked.wait(), timeout=5)
        tasks.append(asyncio.create_task(write(second_writer)))
        await asyncio.wait_for(attempted.wait(), timeout=5)
        # PostgreSQL confirms the second connection is waiting on the first;
        # then both complete with no reverse lock order or deadlock.
        async with ctx.factory() as observer:
            blocked = False
            for _ in range(50):
                blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[second_writer]})
                if pids[first_writer] in blockers:
                    blocked = True
                    break
                await asyncio.sleep(.01)
            assert blocked, "应真实观察到同一统计锁上的等待，而非仅顺序运行两个请求"
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=12)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert len(set(pids.values())) == 2
    async with ctx.factory() as db:
        real = await db.scalar(select(AppContentStats))
        assert real.like_count == 1
        assert await db.scalar(select(func.count()).select_from(AppLike)) == 1
        record = await engagement.metrics_record(db, "work", ctx.work_id)
        assert record["version"] == before["version"] + 1
        assert record["display"]["like_count"] == (20001 if first_writer == "adjust" else 20000)
        assert record["initial"]["like_count"] == (20000 if first_writer == "adjust" else 19999)
