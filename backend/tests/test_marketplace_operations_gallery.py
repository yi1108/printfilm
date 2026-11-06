"""合并运营卡片的管理员权限、混合类型与筛选；使用回滚的独立PG schema。"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
import httpx
import pytest

from app.database import get_db
from app.deps import get_current_user
from app.marketplace import metrics_admin
from app.marketplace.app_engagement import adjust_metrics
from app.marketplace.app_social_models import AppContentStats
from app.marketplace.curation_admin import CurationInput, save_curation
from app.marketplace.models import Series, SeriesEpisode
from test_marketplace_app_content import app_ctx, make_work


@asynccontextmanager
async def gallery_client(ctx):
    app = FastAPI()
    app.include_router(metrics_admin.router, prefix="/api/admin/marketplace/app")

    async def database():
        yield ctx.db

    async def user():
        if ctx.user is None:
            raise HTTPException(401, "请登录")
        return ctx.user

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def make_cards(ctx):
    content = await make_work(ctx, title="海边单视频")
    content.work.cover_asset_id = content.asset.id
    ctx.owner.nickname = "示例创作者"
    series = Series(owner_id=ctx.owner.id, title="山间故事", category="短剧", sale_type="free",
        cover_asset_id=content.asset.id, audit_status="approved", listed=True)
    ctx.db.add(series)
    await ctx.db.flush()
    episode = SeriesEpisode(series_id=series.id, owner_id=ctx.owner.id, episode_no=1, title="第一集",
        asset_id=content.asset.id, audit_status="approved", listed=True)
    ctx.db.add(episode)
    await ctx.db.flush()
    await adjust_metrics(ctx.db, "work", content.work.id, version=0, reason="运营展示",
        desired={"like_count": 6000, "favorite_count": 3000, "share_count": 1000}, clear=False, operator_id=ctx.buyer.id)
    await save_curation(ctx.db, "work", content.work.id, CurationInput(version=0, is_featured=True, is_pinned=False, reason="精选"), ctx.buyer.id, "精选")
    await save_curation(ctx.db, "work", content.work.id, CurationInput(version=1, is_featured=True, is_pinned=True, reason="置顶"), ctx.buyer.id, "置顶")
    await save_curation(ctx.db, "series", series.id, CurationInput(version=0, is_featured=True, is_pinned=False, reason="精选"), ctx.buyer.id, "精选")
    ctx.db.add(AppContentStats(target_type="episode", target_id=episode.id, like_count=12, favorite_count=3, share_count=2))
    await ctx.db.flush()
    return content.work, series, episode


@pytest.mark.asyncio
async def test_merged_cards_require_admin_and_keep_distinct_versions_and_targets(app_ctx):
    ctx = app_ctx
    work, series, episode = await make_cards(ctx)
    assert work.id == series.id  # 分表编号相同仍必须返回不同卡片。
    path = "/api/admin/marketplace/app/social/metrics"
    async with gallery_client(ctx) as client:
        assert (await client.get(path)).status_code == 401
        ctx.user = ctx.owner
        assert (await client.get(path)).status_code == 403
        ctx.user = ctx.buyer
        ctx.user.role = "admin"
        response = await client.get(path)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 3
        cards = {(row["target_type"], row["target_id"]): row for row in payload["items"]}
        video = cards[("work", work.id)]
        assert video["author"] == "示例创作者" and video["cover_asset_id"] == work.cover_asset_id
        assert video["asset_id"] == work.asset_id
        assert video["version"] == 1 and video["curation_version"] == 2
        assert video["display"] == {"like_count": 6000, "favorite_count": 3000, "share_count": 1000}
        assert video["is_featured"] and video["is_pinned"]
        segment = cards[("series_episode", episode.id)]
        assert segment["cover_asset_id"] == series.cover_asset_id  # 分集无独立封面，带入系列封面。
        assert segment["series_title"] == series.title and segment["episode_no"] == 1
        assert segment["real"]["like_count"] == segment["display"]["like_count"] == 12
        assert not segment["is_pinned"] and segment["curation_version"] == 0
        assert "email" not in response.text and "object_key" not in response.text


@pytest.mark.asyncio
async def test_merged_filters_are_applied_before_mixed_pagination(app_ctx):
    ctx = app_ctx
    work, series, episode = await make_cards(ctx)
    removed = await make_work(ctx, title="已删除作品")
    removed.work.deleted_at = datetime.now(timezone.utc)
    await ctx.db.flush()
    ctx.user = ctx.buyer
    ctx.user.role = "admin"
    path = "/api/admin/marketplace/app/social/metrics"
    async with gallery_client(ctx) as client:
        pinned = (await client.get(path, params={"curation": "pinned"})).json()
        assert [(row["target_type"], row["target_id"]) for row in pinned["items"]] == [("work", work.id)]
        featured = (await client.get(path, params={"curation": "featured", "page_size": 1})).json()
        assert featured["total"] == 2 and len(featured["items"]) == 1
        second = (await client.get(path, params={"curation": "featured", "page_size": 1, "page": 2})).json()
        assert {(featured["items"][0]["target_type"], featured["items"][0]["target_id"]),
                (second["items"][0]["target_type"], second["items"][0]["target_id"])} == {("work", work.id), ("series", series.id)}
        normal = (await client.get(path, params={"curation": "normal"})).json()
        assert [(row["target_type"], row["target_id"]) for row in normal["items"]] == [("series_episode", episode.id)]
        searched = (await client.get(path, params={"q": series.title})).json()
        assert {row["target_type"] for row in searched["items"]} == {"series", "series_episode"}
        episodes = (await client.get(path, params={"target_type": "series_episode", "curation": "pinned"})).json()
        assert episodes["total"] == 0
        assert (await client.get(path, params={"curation": "unsupported"})).status_code == 422
