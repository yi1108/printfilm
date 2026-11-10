"""App版本先筛选再分页；作者选择持久化且旧客户端不能覆盖。"""
import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.marketplace import api, series as series_api
from app.marketplace.models import Series, SeriesEpisode, Work
from app.marketplace.schemas import SeriesInput, SeriesUpdate, WorkInput, WorkUpdate
from test_marketplace_app_content import app_ctx, make_work  # noqa: F401
from test_marketplace_coins import coin_ctx  # noqa: F401

pytestmark = pytest.mark.asyncio
PREFIX = "/api/marketplace/app/v1"


async def test_feed_filters_editions_before_pagination_and_preserves_free_policy(app_ctx):
    ctx = app_ctx
    domestic = await make_work(ctx, "platform_unlock", title="国内")
    overseas = await make_work(ctx, "platform_unlock", title="国际")
    both = await make_work(ctx, "platform_unlock", title="两版")
    free = await make_work(ctx, title="免费")
    await make_work(ctx, "copyright_contact", title="版权出售")
    overseas.work.app_editions = ["international"]
    both.work.app_editions = ["domestic", "international"]
    await ctx.db.flush()
    for edition, expected in (("domestic", {domestic.work.id, both.work.id, free.work.id}),
                              ("international", {overseas.work.id, both.work.id, free.work.id})):
        result, cursor = [], ""
        while True:
            response = await ctx.client.get(f"{PREFIX}/feed", params={"app_edition": edition, "limit": 1, "cursor": cursor})
            assert response.status_code == 200, response.text
            page = response.json()
            result.extend(row["id"] for row in page["items"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        assert len(result) == len(expected)
        assert set(result) == expected
    default = (await ctx.client.get(f"{PREFIX}/feed", headers={"Accept-Language": "en-US"})).json()
    assert {row["id"] for row in default["items"]} == {domestic.work.id, both.work.id, free.work.id}
    assert (await ctx.client.get(f"{PREFIX}/works/{overseas.work.id}")).status_code == 200
    assert (await ctx.client.get(f"{PREFIX}/works/{overseas.work.id}?app_edition=international")).status_code == 200
    assert (await ctx.client.get(f"{PREFIX}/works/{domestic.work.id}?app_edition=international")).status_code == 200
    overseas.work.blocked = True
    await ctx.db.flush()
    assert (await ctx.client.get(f"{PREFIX}/works/{overseas.work.id}")).status_code == 404
    first = (await ctx.client.get(f"{PREFIX}/feed?limit=1")).json()
    changed = await ctx.client.get(f"{PREFIX}/feed", params={"app_edition": "international", "cursor": first["next_cursor"]})
    assert changed.status_code == 422


async def test_series_edition_filters_feed_but_not_detail_or_episode_directory(app_ctx):
    ctx = app_ctx
    media = await make_work(ctx)
    parent = Series(owner_id=ctx.owner.id, title="国际短剧", sale_type="platform_unlock", free_episode_count=1,
                    app_editions=["international"], audit_status="approved", listed=True)
    ctx.db.add(parent)
    await ctx.db.flush()
    episode = SeriesEpisode(owner_id=ctx.owner.id, series_id=parent.id, episode_no=1, title="免费集",
                            source="external", asset_id=media.asset.id, audit_status="approved", listed=True)
    ctx.db.add(episode)
    await ctx.db.flush()
    for suffix in (f"/series/{parent.id}", f"/series/{parent.id}/episodes"):
        assert (await ctx.client.get(PREFIX + suffix)).status_code == 200
        response = await ctx.client.get(PREFIX + suffix, params={"app_edition": "international"})
        assert response.status_code == 200, response.text
        assert (await ctx.client.get(PREFIX + suffix, params={"app_edition": "domestic"})).status_code == 200
    rows = (await ctx.client.get(f"{PREFIX}/series/{parent.id}/episodes?app_edition=international")).json()["items"]
    assert rows[0]["is_free"] is True
    assert (await ctx.client.get(f"{PREFIX}/feed?app_edition=all")).status_code == 422
    domestic = (await ctx.client.get(f"{PREFIX}/feed?app_edition=domestic")).json()["items"]
    international = (await ctx.client.get(f"{PREFIX}/feed?app_edition=international")).json()["items"]
    assert not any(row["content_type"] == "series" for row in domestic)
    assert any(row["content_type"] == "series" and row["id"] == parent.id for row in international)
    parent.blocked = True
    await ctx.db.flush()
    for suffix in (f"/series/{parent.id}", f"/series/{parent.id}/episodes"):
        assert (await ctx.client.get(PREFIX + suffix)).status_code == 404


async def test_author_save_readback_and_legacy_updates_preserve_distribution(app_ctx):
    ctx = app_ctx
    selected = ["domestic", "international"]
    work = await api.create_work(WorkInput(title="作品", price_fen=0, app_editions=selected), ctx.db, ctx.owner)
    assert work["app_editions"] == selected
    updated = await api.update_work(work["id"], WorkUpdate(title="旧客户端修改", price_fen=0, version=work["version"]), ctx.db, ctx.owner)
    assert updated["app_editions"] == selected
    updated = await api.update_work(work["id"], WorkUpdate(title="修改投放", price_fen=0, version=updated["version"], app_editions=["international"]), ctx.db, ctx.owner)
    assert updated["app_editions"] == ["international"]
    parent = await series_api.create_series(SeriesInput(title="系列", app_editions=selected), ctx.db, ctx.owner)
    assert parent["app_editions"] == selected
    updated = await series_api.update_series(parent["id"], SeriesUpdate(title="旧客户端修改", version=parent["version"]), ctx.db, ctx.owner)
    assert updated["app_editions"] == selected


@pytest.mark.parametrize("model,fields", [(WorkInput, {"title": "作品", "price_fen": 0}), (SeriesInput, {"title": "系列"})])
async def test_distribution_request_validation(model, fields):
    assert model(**fields).app_editions == ["domestic"]
    for invalid in ([], ["all"], ["domestic", "invalid"], None, "international"):
        with pytest.raises(ValidationError):
            model(**fields, app_editions=invalid)


async def test_startup_adds_edition_columns_idempotently_and_defaults_legacy_to_domestic(coin_ctx):
    from app.marketplace.app_schema import apply_schema, check_schema
    ctx = coin_ctx
    old_work = Work(owner_id=ctx.owner.id, title="历史作品", price_fen=0, sale_type="platform_unlock", version=7)
    old_series = Series(owner_id=ctx.owner.id, title="历史系列", sale_type="platform_unlock", version=3)
    ctx.db.add_all([old_work, old_series])
    await ctx.db.flush()
    await ctx.db.execute(text(f'SET LOCAL search_path TO "{ctx.schema}"'))
    await ctx.db.execute(text("ALTER TABLE marketplace_works DROP COLUMN app_editions"))
    await ctx.db.execute(text("ALTER TABLE marketplace_series DROP COLUMN app_editions"))
    connection = await ctx.db.connection()
    assert "marketplace_works.app_editions" in await connection.run_sync(check_schema)
    await connection.run_sync(apply_schema)
    await connection.run_sync(apply_schema)
    assert await connection.run_sync(check_schema) == []
    await ctx.db.refresh(old_work)
    await ctx.db.refresh(old_series)
    assert (old_work.app_editions, old_work.version) == (["domestic"], 7)
    assert (old_series.app_editions, old_series.version) == (["domestic"], 3)
