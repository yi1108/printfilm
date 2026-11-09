"""发布版本永久权益与付款回调：独立测试库、随机 schema、事务回滚。"""
from types import SimpleNamespace
import uuid

from fastapi import FastAPI
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.marketplace import api, commerce, series as series_api, storage
from app.marketplace.dependencies import optional_user
from app.marketplace.models import (
    Asset, Authorization, ContentOrder, Entitlement, EpisodePreview, Event, Handoff, MarketBase, Publication,
    RevenueConfig, RevenueLedger, Rights, Series, SeriesEpisode, Work, WorkPreview,
)
from conftest import _ensure_test_database, _resolve_test_database_url


@pytest_asyncio.fixture
async def publication_ctx(monkeypatch):
    """完全隔离于已有 _test 表；commit 只提交 savepoint，最终回滚 schema。"""
    url, name = _resolve_test_database_url(get_settings().database_url)
    await _ensure_test_database(url, name)
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        outer = await connection.begin()
        schema = f"publication_test_{uuid.uuid4().hex}"
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection = await connection.execution_options(schema_translate_map={None: schema})
        await connection.run_sync(lambda sync: User.__table__.create(sync))
        await connection.run_sync(MarketBase.metadata.create_all)
        db = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        owner = User(email="creator@test.invalid", hashed_password="unused")
        buyer = User(email="viewer@test.invalid", hashed_password="unused")
        db.add_all([owner, buyer])
        await db.flush()
        state = SimpleNamespace(db=db, owner=owner, buyer=buyer, user=buyer, signed=[], manifests=[])

        async def session_override():
            yield db

        async def user_override():
            return state.user

        app = FastAPI()
        app.include_router(commerce.router, prefix="/api/marketplace")
        app.include_router(series_api.router, prefix="/api/marketplace")
        app.include_router(api.router, prefix="/api/marketplace")
        app.dependency_overrides[get_db] = session_override
        app.dependency_overrides[get_current_user] = user_override
        app.dependency_overrides[optional_user] = user_override
        monkeypatch.setattr(commerce, "_payment_ready", lambda: True)
        monkeypatch.setattr(commerce.epay, "verify", lambda _params: True)
        monkeypatch.setattr(storage, "bucket", lambda: object())

        def read_manifest(key):
            state.manifests.append(key)
            return b"#EXTM3U\n#EXTINF:5,\nsegment-000.ts\n#EXT-X-ENDLIST\n"

        def sign(key, content_type):
            state.signed.append(key)
            return f"https://private.invalid/{key}?expires=300"

        monkeypatch.setattr(storage, "read", read_manifest)
        monkeypatch.setattr(storage, "signed", sign)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                state.client = client
                yield state
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


async def make_publication(ctx, *, episode=True):
    asset = Asset(owner_id=ctx.owner.id, kind="video", filename="original.mp4", content_type="video/mp4",
                  size_bytes=100, object_key=f"marketplace/originals/{uuid.uuid4().hex}.mp4", status="ready")
    ctx.db.add(asset)
    await ctx.db.flush()
    proof = Rights(owner_id=ctx.owner.id, asset_id=asset.id, basic_status="approved", full_status="approved",
                   certificate_asset_id=asset.id, details={"source": "external"})
    ctx.db.add(proof)
    series = None
    if episode:
        series = Series(owner_id=ctx.owner.id, title="series", sale_type="platform_unlock", audit_status="approved", listed=True)
        ctx.db.add(series)
        await ctx.db.flush()
        item = SeriesEpisode(owner_id=ctx.owner.id, series_id=series.id, episode_no=1, title="episode",
                             asset_id=asset.id, unlock_price_fen=999, audit_status="approved", listed=True)
    else:
        item = Work(owner_id=ctx.owner.id, title="work", sale_type="platform_unlock", asset_id=asset.id,
                    price_fen=1000, unlock_price_fen=999, audit_status="approved", listed=True)
    ctx.db.add(item)
    await ctx.db.flush()
    publication = Publication(content_type="series_episode" if episode else "work", content_id=item.id,
                              owner_id=ctx.owner.id, version=1, asset_id=asset.id, sale_type="platform_unlock",
                              unlock_price_fen=999, share_bps=2345, audit_status="approved", listed=True,
                              playback_status="done", playback_manifest_key="marketplace/hls/old/index.m3u8")
    ctx.db.add(publication)
    await ctx.db.flush()
    return SimpleNamespace(asset=asset, proof=proof, item=item, series=series, publication=publication)


async def grant(ctx, content):
    entitlement = Entitlement(user_id=ctx.buyer.id, publication_id=content.publication.id,
                              episode_id=content.item.id if content.series else None)
    ctx.db.add(entitlement)
    await ctx.db.flush()
    return entitlement


async def pending_order(ctx, content, *, key=None):
    order = ContentOrder(out_trade_no=f"MKT-{uuid.uuid4().hex}", user_id=ctx.buyer.id,
                         publication_id=content.publication.id, episode_id=content.item.id if content.series else None,
                         amount_fen=999, pay_type="alipay", idempotency_key=key or uuid.uuid4().hex)
    ctx.db.add(order)
    await ctx.db.flush()
    return order


def payment_params(order, money="9.99"):
    return {"out_trade_no": order.out_trade_no, "money": money, "trade_status": "TRADE_SUCCESS", "trade_no": "gateway-123"}


@pytest.mark.parametrize("episode", [True, False])
async def test_owned_old_publication_plays_original_purchased_hls_after_edit(publication_ctx, episode):
    ctx = publication_ctx
    content = await make_publication(ctx, episode=episode)
    await grant(ctx, content)
    content.item.version = 2
    content.item.audit_status = "draft"
    content.item.listed = False
    content.publication.listed = False
    if content.series:
        content.series.audit_status, content.series.listed = "draft", False
    await ctx.db.flush()
    response = await ctx.client.get(f"/api/marketplace/platform/publications/{content.publication.id}/playback")
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "hls" and "url" not in response.json()
    assert ctx.manifests == ["marketplace/hls/old/index.m3u8"]
    assert ctx.signed == ["marketplace/hls/old/segment-000.ts"]
    assert content.asset.object_key not in response.text


@pytest.mark.parametrize("restriction", ["episode", "series", "rights", "inactive", "missing"])
async def test_old_publication_enforces_live_restrictions_before_signing(publication_ctx, restriction):
    ctx = publication_ctx
    content = await make_publication(ctx)
    entitlement = await grant(ctx, content) if restriction != "missing" else None
    if restriction == "episode":
        content.item.blocked = True
    elif restriction == "series":
        content.series.blocked = True
    elif restriction == "rights":
        content.proof.blocked = True
    elif restriction == "inactive":
        entitlement.active = False
    await ctx.db.flush()
    response = await ctx.client.get(f"/api/marketplace/platform/publications/{content.publication.id}/playback")
    assert response.status_code == 403
    assert ctx.signed == [] and ctx.manifests == []


@pytest.mark.parametrize("change", ["version", "draft", "unlisted", "series_draft", "series_unlisted", "blocked", "rights"])
async def test_new_order_cannot_buy_stale_or_hidden_publication(publication_ctx, change):
    ctx = publication_ctx
    content = await make_publication(ctx)
    if change == "version":
        content.item.version = 2
    elif change == "draft":
        content.item.audit_status = "draft"
    elif change == "unlisted":
        content.item.listed = False
    elif change == "series_draft":
        content.series.audit_status = "draft"
    elif change == "series_unlisted":
        content.series.listed = False
    elif change == "blocked":
        content.series.blocked = True
    else:
        content.proof.blocked = True
    await ctx.db.flush()
    response = await ctx.client.post("/api/marketplace/content-orders", json={
        "publication_id": content.publication.id, "pay_type": "alipay", "idempotency_key": uuid.uuid4().hex})
    assert response.status_code == 409, response.text
    assert await ctx.db.scalar(select(func.count()).select_from(ContentOrder)) == 0


@pytest.mark.parametrize("whole_series", [False, True])
async def test_legacy_priced_free_episode_cannot_create_new_order(publication_ctx, whole_series):
    ctx = publication_ctx
    content = await make_publication(ctx)
    if whole_series:
        content.series.sale_type = "free"
    else:
        content.series.free_episode_count = 1
    await ctx.db.flush()
    # 历史快照可能仍有价格；免费集不能因此被收费，旧购买权益仍可播放。
    response = await ctx.client.post("/api/marketplace/content-orders", json={
        "publication_id": content.publication.id, "pay_type": "alipay", "idempotency_key": uuid.uuid4().hex})
    assert response.status_code == 409, response.text
    assert await ctx.db.scalar(select(func.count()).select_from(ContentOrder)) == 0
    await grant(ctx, content)
    playback = await ctx.client.get(f"/api/marketplace/platform/publications/{content.publication.id}/playback")
    assert playback.status_code == 200, playback.text


async def test_pending_payment_survives_update_and_duplicate_notification(publication_ctx):
    ctx = publication_ctx
    content = await make_publication(ctx)
    order = await pending_order(ctx, content)
    ctx.db.add(RevenueConfig(id=1, platform_share_bps=9999))
    content.item.version, content.item.listed, content.item.audit_status = 2, False, "draft"
    content.series.listed, content.series.audit_status = False, "draft"
    content.publication.listed = False
    await ctx.db.flush()
    for _ in range(2):
        response = await ctx.client.get("/api/marketplace/payments/epay/notify", params=payment_params(order))
        assert response.status_code == 200 and response.text == "success"
    assert order.status == "paid"
    entitlement = (await ctx.db.execute(select(Entitlement))).scalar_one()
    ledger = (await ctx.db.execute(select(RevenueLedger))).scalar_one()
    assert entitlement.publication_id == content.publication.id and entitlement.active
    assert ledger.gross_fen == 999 and ledger.share_bps == 2345
    assert ledger.platform_fen == 234 and ledger.creator_fen == 765


async def test_payment_while_blocked_is_recorded_and_playback_remains_blocked(publication_ctx):
    ctx = publication_ctx
    content = await make_publication(ctx)
    order = await pending_order(ctx, content)
    content.proof.blocked = True
    await ctx.db.flush()
    response = await ctx.client.get("/api/marketplace/payments/epay/notify", params=payment_params(order))
    assert response.status_code == 200 and response.text == "success"
    assert order.status == "paid"
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueLedger)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(Event).where(Event.action == "paid_restricted_review")) == 1
    response = await ctx.client.get(f"/api/marketplace/platform/publications/{content.publication.id}/playback")
    assert response.status_code == 403 and ctx.signed == []


async def test_second_checkout_payment_does_not_duplicate_entitlement_or_income(publication_ctx):
    ctx = publication_ctx
    content = await make_publication(ctx)
    for _ in range(2):
        order = await pending_order(ctx, content)
        response = await ctx.client.get("/api/marketplace/payments/epay/notify", params=payment_params(order))
        assert response.text == "success"
    assert await ctx.db.scalar(select(func.count()).select_from(Entitlement)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueLedger)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(ContentOrder).where(ContentOrder.status == "paid")) == 2
    assert await ctx.db.scalar(select(func.count()).select_from(Event).where(Event.action == "duplicate_purchase_paid")) == 1


@pytest.mark.parametrize("money", ["invalid", "", "9.991", "9.98", "NaN", "Infinity"])
async def test_invalid_payment_amount_never_creates_access(publication_ctx, money):
    ctx = publication_ctx
    content = await make_publication(ctx)
    order = await pending_order(ctx, content)
    response = await ctx.client.get("/api/marketplace/payments/epay/notify", params=payment_params(order, money))
    assert response.status_code == 400
    assert order.status == "pending"
    assert await ctx.db.scalar(select(func.count()).select_from(Entitlement)) == 0


async def test_retry_idempotency_key_is_bound_to_original_request(publication_ctx):
    ctx = publication_ctx
    content = await make_publication(ctx)
    original = await pending_order(ctx, content)
    other = await make_publication(ctx, episode=False)
    response = await ctx.client.post("/api/marketplace/content-orders", json={
        "publication_id": other.publication.id, "pay_type": "alipay", "idempotency_key": original.idempotency_key})
    assert response.status_code == 409
    content.publication.listed = False
    await ctx.db.flush()
    response = await ctx.client.post("/api/marketplace/content-orders", json={
        "publication_id": content.publication.id, "pay_type": "alipay", "idempotency_key": original.idempotency_key})
    assert response.status_code == 200 and response.json()["out_trade_no"] == original.out_trade_no


async def test_new_order_freezes_amount_and_idempotent_retry_uses_same_order(publication_ctx, monkeypatch):
    ctx = publication_ctx
    content = await make_publication(ctx)
    calls = []

    async def payment(**kwargs):
        calls.append(kwargs)
        return {"payurl": "https://payment.invalid/checkout"}

    monkeypatch.setattr(commerce.epay, "create_mapi_payment", payment)
    monkeypatch.setattr(commerce.epay, "build_submit_fields", lambda **kwargs: {})
    monkeypatch.setattr(commerce.epay, "submit_url", lambda _fields: "https://payment.invalid/submit")
    body = {"publication_id": content.publication.id, "pay_type": "alipay", "idempotency_key": uuid.uuid4().hex}
    first = await ctx.client.post("/api/marketplace/content-orders", json=body)
    assert first.status_code == 200, first.text
    second = await ctx.client.post("/api/marketplace/content-orders", json=body)
    assert second.status_code == 200 and second.json()["out_trade_no"] == first.json()["out_trade_no"]
    assert len(calls) == 1 and calls[0]["money_yuan"] == "9.99"
    assert await ctx.db.scalar(select(func.count()).select_from(ContentOrder)) == 1


async def test_series_metadata_edit_creates_new_episode_version_and_preserves_purchase(publication_ctx):
    ctx = publication_ctx
    content = await make_publication(ctx)
    await grant(ctx, content)
    ctx.user = ctx.owner
    content.series.share_bps = 3200
    response = await ctx.client.patch(f"/api/marketplace/series/{content.series.id}", json={
        "title": "new title", "version": content.series.version, "sale_type": "platform_unlock"})
    assert response.status_code == 200, response.text
    assert response.json()["episodes"][0]["version"] == 2
    assert content.series.share_bps == 3200
    assert content.item.version == 2 and content.series.audit_status == "draft"
    assert not content.item.listed and not content.publication.listed
    assert content.publication.version == 1 and content.publication.share_bps == 2345
    assert content.publication.playback_manifest_key == "marketplace/hls/old/index.m3u8"
    ctx.user = ctx.buyer
    assert (await ctx.client.get(f"/api/marketplace/platform/publications/{content.publication.id}/playback")).status_code == 200


@pytest.mark.parametrize("state", ["pending", "running", "failed"])
async def test_sync_state_blocks_submission_and_is_exposed_in_editor(publication_ctx, state):
    ctx = publication_ctx
    content = await make_publication(ctx)
    ctx.user = ctx.owner
    content.series.audit_status = "draft"
    ctx.db.add(Handoff(owner_id=ctx.owner.id, idempotency_key=uuid.uuid4().hex, source_kind="drama_episode",
                       source_id=99, target_kind="series_episode", target_id=content.item.id,
                       series_id=content.series.id, status=state, error="copy failed" if state == "failed" else ""))
    await ctx.db.flush()
    detail = await ctx.client.get(f"/api/marketplace/series/{content.series.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["sync_in_progress"] == (state != "failed")
    assert detail.json()["pending_handoffs"][0]["status"] == state
    response = await ctx.client.post(f"/api/marketplace/series/{content.series.id}/submit", json={"version": 1})
    assert response.status_code == 409
    assert response.json()["detail"] == ("MARKETPLACE_EPISODE_NOT_READY" if state == "failed" else "MARKETPLACE_SYNC_IN_PROGRESS")


async def test_episode_with_pending_order_cannot_be_deleted(publication_ctx):
    ctx = publication_ctx
    content = await make_publication(ctx)
    await pending_order(ctx, content)
    ctx.user = ctx.owner
    response = await ctx.client.delete(f"/api/marketplace/series/{content.series.id}/episodes/{content.item.id}")
    assert response.status_code == 409 and "订单或购买权益" in response.json()["detail"]
    assert await ctx.db.get(SeriesEpisode, content.item.id) is not None


@pytest.mark.parametrize("override, expected", [(None, 2100), (0, 0), (3500, 3500)])
async def test_series_submission_freezes_effective_revenue_share(publication_ctx, override, expected):
    ctx = publication_ctx
    content = await make_publication(ctx)
    ctx.user = ctx.owner
    content.series.audit_status = "draft"
    content.item.share_bps = override
    content.proof.details = {"source": "external", "certificate_number": "CP-123", "dispute_ack": True}
    cover = Asset(owner_id=ctx.owner.id, kind="image", filename="cover.png", content_type="image/png",
                  size_bytes=10, object_key="marketplace/covers/test.png", status="ready")
    ctx.db.add_all([cover, RevenueConfig(id=1, platform_share_bps=2100)])
    await ctx.db.flush()
    content.item.cover_asset_id = cover.id
    ctx.db.add(EpisodePreview(episode_id=content.item.id, asset_id=content.asset.id, version=1,
                             status="done", object_key="marketplace/previews-v2/episodes/test.mp4"))
    await ctx.db.flush()
    response = await ctx.client.post(f"/api/marketplace/series/{content.series.id}/submit", json={"version": 1})
    assert response.status_code == 200, response.text
    publications = list((await ctx.db.execute(select(Publication).order_by(Publication.version))).scalars().all())
    assert len(publications) == 2 and publications[1].version == 2
    assert publications[0].share_bps == 2345 and publications[0].playback_manifest_key
    assert publications[1].share_bps == expected
    assert not publications[0].listed and not publications[1].listed


async def test_work_submission_freezes_default_share_and_never_rewrites_approved_snapshot(publication_ctx):
    ctx = publication_ctx
    content = await make_publication(ctx, episode=False)
    ctx.user = ctx.owner
    content.item.audit_status, content.item.source, content.item.license_scope = "draft", "external", "商业展示"
    content.proof.details = {"source": "external", "certificate_number": "CP-123", "dispute_ack": True}
    ctx.db.add_all([RevenueConfig(id=1, platform_share_bps=2100), WorkPreview(
        work_id=content.item.id, asset_id=content.asset.id, version=1,
        status="done", object_key="marketplace/previews-v2/works/test.mp4")])
    await ctx.db.flush()
    response = await ctx.client.post(f"/api/marketplace/works/{content.item.id}/submit", json={"version": 1})
    assert response.status_code == 200, response.text
    publications = list((await ctx.db.execute(select(Publication).order_by(Publication.version))).scalars().all())
    assert len(publications) == 2 and publications[1].version == 2
    assert publications[0].share_bps == 2345 and publications[0].playback_manifest_key
    assert publications[1].share_bps == 2100


async def test_replacing_imported_printfilm_video_detaches_source_and_reuses_account_authorization(publication_ctx):
    from app.marketplace.authorization import VERSION

    ctx = publication_ctx
    content = await make_publication(ctx)
    ctx.user = ctx.owner
    old_handoff = Handoff(owner_id=ctx.owner.id, idempotency_key=uuid.uuid4().hex,
        source_kind="drama_episode", source_id=123, source_version="original-source-version",
        target_kind="series_episode", target_id=content.item.id, series_id=content.series.id,
        asset_id=content.asset.id, status="ready")
    new_video = Asset(owner_id=ctx.owner.id, kind="video", filename="replacement.mp4", content_type="video/mp4",
        size_bytes=200, object_key="marketplace/manual/replacement.mp4", status="ready")
    cover = Asset(owner_id=ctx.owner.id, kind="image", filename="cover.png", content_type="image/png",
        size_bytes=10, object_key="marketplace/manual/cover.png", status="ready")
    authorization = Authorization(owner_id=ctx.owner.id, template_version=VERSION, signer_name="测试签署人",
        body="test authorization", body_hash="a" * 64, letter_key="marketplace/auth/letter.png",
        signature_key="marketplace/auth/signature.png", client_ip="127.0.0.1", user_agent="test")
    ctx.db.add_all([old_handoff, new_video, cover, authorization, RevenueConfig(id=1, platform_share_bps=2100)])
    await ctx.db.flush()
    content.item.source, content.item.source_type = "printfilm", "drama_import"
    content.item.source_snapshot = {"source_kind": "drama_episode", "drama_episode_id": 123,
        "last_handoff_id": old_handoff.id, "imported_source_version": "original-source-version"}
    content.item.preview_status, content.item.preview_key = "done", "marketplace/old/preview.mp4"
    content.item.playback_status, content.item.playback_manifest_key = "done", "marketplace/hls/old/index.m3u8"
    await ctx.db.flush()
    response = await ctx.client.patch(f"/api/marketplace/series/{content.series.id}/episodes/{content.item.id}", json={
        "episode_no": 1, "title": "替换后的PrintFilm视频", "version": 1, "source": "printfilm",
        "asset_id": new_video.id, "cover_asset_id": cover.id, "unlock_price_fen": 999})
    assert response.status_code == 200, response.text
    assert content.item.source_type == "upload" and content.item.source_snapshot == {}
    assert content.item.preview_status == "none" and content.item.preview_key is None
    assert content.item.playback_status == "none" and content.item.playback_manifest_key is None
    assert old_handoff.status == "ready" and old_handoff.asset_id == content.asset.id
    response = await ctx.client.post(f"/api/marketplace/series/{content.series.id}/submit", json={"version": content.series.version})
    assert response.status_code == 200, response.text
    proof = (await ctx.db.execute(select(Rights).where(Rights.asset_id == new_video.id))).scalar_one()
    assert proof.details["source"] == "printfilm" and proof.details["authorization_id"] == str(authorization.id)
    assert proof.details["authorization_version"] == VERSION and not proof.certificate_asset_id
    assert proof.basic_status == "pending" and proof.full_status == "pending"
    assert content.publication.asset_id == content.asset.id and content.publication.version == 1
    assert content.publication.share_bps == 2345 and content.publication.audit_status == "approved"
    assert content.publication.playback_manifest_key == "marketplace/hls/old/index.m3u8"


@pytest.mark.parametrize("kind", ["work", "series", "series_episode"])
async def test_content_share_is_admin_only_and_preserves_frozen_publication(publication_ctx, kind):
    from app.marketplace import admin as admin_api
    ctx = publication_ctx
    content = await make_publication(ctx, episode=kind != "work")
    target = content.series if kind == "series" else content.item
    ctx.client._transport.app.include_router(admin_api.router, prefix="/api/admin/marketplace")
    path = f"/api/admin/marketplace/content-revenue/{kind}/{target.id}"
    body = {"version": target.version, "previous_share_bps": None, "share_bps": 3100, "reason": "运营调整"}
    ctx.user = ctx.owner
    assert (await ctx.client.patch(path, json=body)).status_code == 403
    ctx.owner.role = "admin"
    response = await ctx.client.patch(path, json=body)
    assert response.status_code == 200, response.text
    assert target.share_bps == 3100
    assert content.publication.share_bps == 2345
    assert content.item.version == content.publication.version == 1
    assert content.item.listed and content.publication.listed
    assert (await ctx.client.patch(path, json=body)).status_code == 409
    reset = {**body, "previous_share_bps": 3100, "share_bps": None}
    assert (await ctx.client.patch(path, json=reset)).status_code == 200
    assert target.share_bps is None
    audit = (await ctx.db.scalars(select(Event).where(Event.action == "revenue_share_updated"))).all()
    assert len(audit) == 2 and all(row.actor_id == ctx.owner.id for row in audit)

    listing = await ctx.client.get("/api/admin/marketplace/records/series" if kind != "work" else "/api/admin/marketplace/records/works")
    assert listing.status_code == 200, listing.text
    record = listing.json()["items"][0]
    if kind == "series_episode":
        assert "share_bps" in record["episodes"][0]
