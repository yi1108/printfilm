"""Curation permissions, business filtering and cursor transitions on an isolated DB schema."""
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import select

from app.marketplace import api, app_social_models, curation_admin
from app.marketplace.curation import decode_feed_cursor, encode_feed_cursor, feed_fingerprint, revision
from app.marketplace.curation_admin import CurationInput, save_curation
from app.marketplace.curation_models import ContentCuration, CurationEvent
from app.marketplace.models import Series, SeriesEpisode
from test_marketplace_app_content import app_ctx, make_work


def values(version=0, *, featured=False, pinned=False, priority=100):
    return CurationInput(version=version, is_featured=featured, is_pinned=pinned, pin_priority=priority, reason="运营选品")


def test_curation_cursor_is_signed_bound_to_filter_and_revision():
    row = SimpleNamespace(timestamp=datetime.now(timezone.utc), kind="work", record_id=12, pin=1, priority=200, feature=1)
    fingerprint = feed_fingerprint(q="作品", category="", category_code="animation", content_type="all", sort="recommended", user_id=None)
    token = encode_feed_cursor(row, sort="recommended", fingerprint=fingerprint, revision=3)
    assert decode_feed_cursor(token, sort="recommended", fingerprint=fingerprint, revision=3) == (1, 200, 1, row.timestamp, "work", 12)
    with pytest.raises(HTTPException) as updated:
        decode_feed_cursor(token, sort="recommended", fingerprint=fingerprint, revision=4)
    assert updated.value.status_code == 409
    assert updated.value.detail["code"] == "MARKETPLACE_FEED_UPDATED"
    for invalid, fingerprint_value in ((token[:-4] + "AAAA", fingerprint), (token, "different-filter")):
        with pytest.raises(HTTPException) as wrong:
            decode_feed_cursor(invalid, sort="recommended", fingerprint=fingerprint_value, revision=3)
        assert wrong.value.status_code == 422


def test_old_time_cursor_only_works_for_latest_and_latest_survives_curation_change():
    from app.marketplace.app_content import encode_cursor
    stamp = datetime.now(timezone.utc)
    old = encode_cursor(stamp, "series", 8)
    assert decode_feed_cursor(old, sort="latest", fingerprint="filter", revision=99) == (stamp, "series", 8)
    with pytest.raises(HTTPException) as outdated:
        decode_feed_cursor(old, sort="recommended", fingerprint="filter", revision=0)
    assert outdated.value.status_code == 409
    row = SimpleNamespace(timestamp=stamp, kind="work", record_id=4)
    token = encode_feed_cursor(row, sort="latest", fingerprint="filter", revision=0)
    assert decode_feed_cursor(token, sort="latest", fingerprint="filter", revision=42) == (stamp, "work", 4)


@pytest.mark.asyncio
async def test_admin_routes_reject_creator_and_keep_partial_batch_audit(app_ctx):
    from app.database import get_db
    from app.deps import get_current_user

    ctx = app_ctx
    video = await make_work(ctx)
    another = await make_work(ctx)
    app = FastAPI()
    app.include_router(curation_admin.router, prefix="/api/admin/marketplace")

    async def database():
        yield ctx.db

    async def user():
        if ctx.user is None:
            raise HTTPException(401, "请登录")
        return ctx.user

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = user
    path = f"/api/admin/marketplace/curation/work/{video.work.id}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        ctx.user = ctx.owner
        assert (await client.patch(path, json=values(featured=True).model_dump())).status_code == 403
        ctx.user = ctx.buyer
        ctx.user.role = "admin"
        assert (await client.get(path)).json()["version"] == 0
        payload = values(featured=True).model_dump()
        assert (await client.patch(path, json={**payload, "pin_priority": 1.5})).status_code == 422
        response = await client.patch(path, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 1
        batch = await client.post("/api/admin/marketplace/curation/batch", json={"reason": "批量选品", "items": [
            {"target_type": "work", "target_id": video.work.id, **values(pinned=True).model_dump(exclude={"reason"})},
            {"target_type": "work", "target_id": another.work.id, **values(pinned=True).model_dump(exclude={"reason"})},
        ]})
        assert batch.status_code == 200, batch.text
        result = batch.json()["items"]
        assert result[0]["ok"] is False and result[0]["status"] == 409
        assert result[1]["ok"] is True and result[1]["is_pinned"] is True
        logs = (await client.get("/api/admin/marketplace/curation/events")).json()
        assert logs["meta"]["total"] == 2


@pytest.mark.asyncio
async def test_admin_update_is_versioned_audited_and_does_not_touch_publication(app_ctx):
    ctx = app_ctx
    original = await make_work(ctx)
    content_version = original.work.version
    first = await save_curation(ctx.db, "work", original.work.id, values(featured=True), ctx.owner.id, "首次精选")
    assert first["version"] == 1
    assert await revision(ctx.db) == 1
    assert original.work.version == content_version
    assert original.work.audit_status == "approved" and original.work.listed
    with pytest.raises(HTTPException) as conflict:
        await save_curation(ctx.db, "work", original.work.id, values(pinned=True), ctx.owner.id, "过期更新")
    assert conflict.value.status_code == 409
    await save_curation(ctx.db, "work", original.work.id, values(1, featured=True, pinned=True, priority=300), ctx.owner.id, "置顶")
    events = list((await ctx.db.scalars(select(CurationEvent).order_by(CurationEvent.id))).all())
    assert len(events) == 2
    assert events[1].before["is_pinned"] is False and events[1].after["is_pinned"] is True
    assert events[1].reason == "置顶"
    detail = (await ctx.client.get(f"/api/marketplace/app/v1/works/{original.work.id}")).json()
    assert detail["is_featured"] and detail["is_pinned"]
    assert "pin_priority" not in detail and "curation_version" not in detail


@pytest.mark.asyncio
async def test_feed_recommendation_filters_and_cursor_changes(app_ctx):
    ctx = app_ctx
    old = await make_work(ctx, title="动画旧作")
    middle = await make_work(ctx, title="动画精选")
    newest = await make_work(ctx, title="广告新作")
    for obj in (old, middle):
        obj.work.category, obj.work.category_code = "动画", "animation"
    newest.work.category, newest.work.category_code = "广告", "advertising"
    await ctx.db.flush()
    await save_curation(ctx.db, "work", old.work.id, values(pinned=True, priority=300), ctx.owner.id, "置顶")
    await save_curation(ctx.db, "work", middle.work.id, values(featured=True), ctx.owner.id, "精选")
    await save_curation(ctx.db, "work", newest.work.id, values(pinned=True, priority=9999), ctx.owner.id, "其他分类")
    prefix = "/api/marketplace/app/v1/feed"
    result = await ctx.client.get(prefix, params={"category_code": "animation", "limit": 1})
    assert result.status_code == 200, result.text
    first = result.json()
    assert [row["id"] for row in first["items"]] == [old.work.id]
    second = (await ctx.client.get(prefix, params={"category_code": "animation", "limit": 1, "cursor": first["next_cursor"]})).json()
    assert [row["id"] for row in second["items"]] == [middle.work.id]
    await save_curation(ctx.db, "work", middle.work.id, values(1, pinned=True, priority=500), ctx.owner.id, "调整顺序")
    updated = await ctx.client.get(prefix, params={"category_code": "animation", "cursor": first["next_cursor"]})
    assert updated.status_code == 409
    assert updated.json()["detail"]["code"] == "MARKETPLACE_FEED_UPDATED"
    latest = (await ctx.client.get(prefix, params={"category_code": "animation", "sort": "latest"})).json()
    assert [row["id"] for row in latest["items"]] == [middle.work.id, old.work.id]
    old.work.listed = False
    await ctx.db.flush()
    visible = (await ctx.client.get(prefix, params={"category_code": "animation"})).json()
    assert [row["id"] for row in visible["items"]] == [middle.work.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("sort, expected_status", [("recommended", 409), ("latest", 200)])
async def test_feed_detects_curation_change_during_item_serialization(app_ctx, monkeypatch, sort, expected_status):
    from app.marketplace import app_content

    ctx = app_ctx
    older = await make_work(ctx, title="旧作")
    await make_work(ctx, title="新作")
    original = app_content.content_data
    changed = False

    async def change_curation_after_read(*args, **kwargs):
        nonlocal changed
        result = await original(*args, **kwargs)
        if not changed:
            changed = True
            # Persist a real revision change in the isolated PostgreSQL schema
            # after the page order has been read, before the response is built.
            await save_curation(ctx.db, "work", older.work.id, values(pinned=True), ctx.owner.id, "请求期间调整置顶")
        return result

    monkeypatch.setattr(app_content, "content_data", change_curation_after_read)
    response = await ctx.client.get("/api/marketplace/app/v1/feed", params={"sort": sort, "limit": 1})
    assert changed
    assert response.status_code == expected_status, response.text
    if sort == "recommended":
        assert response.json()["detail"]["code"] == "MARKETPLACE_FEED_UPDATED"
    else:
        assert len(response.json()["items"]) == 1


@pytest.mark.asyncio
async def test_web_mixed_ids_explicit_price_sort_and_admin_filter(app_ctx):
    ctx = app_ctx
    video = await make_work(ctx, title="单视频")
    second = await make_work(ctx, title="另一个单视频")
    video.work.price_fen, second.work.price_fen = 1000, 100
    series = Series(owner_id=ctx.owner.id, title="系列", sale_type="free", audit_status="approved", listed=True, copyright_price_fen=500)
    ctx.db.add(series)
    await ctx.db.flush()
    ctx.db.add(SeriesEpisode(series_id=series.id, owner_id=ctx.owner.id, episode_no=1, title="第一集", asset_id=video.asset.id,
                             source="external", audit_status="approved", listed=True))
    await ctx.db.flush()
    assert video.work.id == series.id  # independently numbered tables must not collapse.
    await save_curation(ctx.db, "series", series.id, values(pinned=True), ctx.owner.id, "系列置顶")

    async def catalog(sort):
        return await api.works(ctx.db, q="", category="", category_code="", min_price=None, max_price=None, sort=sort, page_number=1, page_size=10)

    recommended = await catalog("recommended")
    assert recommended["items"][0]["kind"] == "series"
    assert recommended["items"][0]["is_pinned"]
    assert len({(row["kind"], row["id"]) for row in recommended["items"]}) == 3
    priced = await catalog("price_asc")
    assert [row["price_fen"] for row in priced["items"]] == [100, 500, 1000]
    from app.marketplace.curation import filter_curation
    assert await ctx.db.scalar(filter_curation(select(Series.id), Series, "series", "pinned")) == series.id
    assert await ctx.db.scalar(filter_curation(select(Series.id), Series, "series", "normal")) is None
