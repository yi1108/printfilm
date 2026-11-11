"""短剧系列市场 API。

系列数据只使用 marketplace_ 表；原 drama 项目仅在用户明确导入时读取一次快照。
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import and_, not_, or_, select

from app.models_drama import DramaProject
from app.models_teams import TeamMember
from .categories import category_fields, category_filter, normalize_category_input
from .dependencies import Actor, DB, Visitor, storage_ready
from .models import Asset, ContentOrder, Entitlement, EpisodePreview, Handoff, PlaybackJob, Publication, RevenueConfig, Rights, Series, SeriesEpisode
from .schemas import EpisodeInput, EpisodeUpdate, ImportEpisodesInput, SeriesInput, SeriesUpdate, Version
from .service import asset_owned, asset_owned_for_draft, check_version, data, event, fail, now, notify, owned, page, validate_rights
from .previews import (CLIP_EPISODE_PREFIX, cancel_episode_previews, episode_is_free,
                       episode_preview_for, episode_preview_ready, is_preview_key, prepare_episode_preview)

router = APIRouter()


async def ensure_series_idle(db, series_id: int, *, submitting: bool = False) -> None:
    active = (await db.execute(select(Handoff.id).where(
        Handoff.series_id == series_id, Handoff.status.in_(("pending", "running"))
    ).limit(1))).scalar_one_or_none()
    if active:
        fail("MARKETPLACE_SYNC_IN_PROGRESS", 409)
    if submitting:
        latest = await _latest_series_handoffs(db, series_id)
        if any(item.status == "failed" for item in latest):
            fail("MARKETPLACE_EPISODE_NOT_READY", 409)


async def _latest_series_handoffs(db, series_id: int) -> list[Handoff]:
    handoffs = list((await db.execute(select(Handoff).where(
        Handoff.series_id == series_id, Handoff.target_kind == "series_episode",
        Handoff.target_id.in_(select(SeriesEpisode.id).where(SeriesEpisode.series_id == series_id)),
    ).order_by(Handoff.id.desc()))).scalars().all())
    latest = {}
    for handoff in handoffs:
        latest.setdefault(handoff.target_id, handoff)
    return list(latest.values())


async def pause_series_sales(db, series: Series, *, bump_episode_versions: bool = False) -> list[SeriesEpisode]:
    """保留旧媒体及购买快照，仅关闭销售；系列资料更新时产生新的逐集版本。"""
    episodes = list((await db.execute(select(SeriesEpisode).where(
        SeriesEpisode.series_id == series.id).with_for_update())).scalars().all())
    series.listed = False
    for episode in episodes:
        episode.listed = False
        if bump_episode_versions:
            episode.version += 1
            episode.audit_status, episode.reason = "draft", ""
            episode.preview_status, episode.preview_key, episode.preview_attempts = "none", None, 0
            await cancel_episode_previews(db, episode)
    if episodes:
        publications = list((await db.execute(select(Publication).where(
            Publication.content_type == "series_episode",
            Publication.content_id.in_([item.id for item in episodes]),
        ).with_for_update())).scalars().all())
        for publication in publications:
            publication.listed = False
    return episodes


def _sale_type(value: str, copyright_price: int) -> str:
    # 收费类型由用户明确选择；参考价为0仍可以先联系客服询价。
    return value


async def _series(db, series_id: int, user, *, lock: bool = False) -> Series:
    query = select(Series).where(Series.id == series_id)
    if lock:
        query = query.with_for_update()
    item = (await db.execute(query)).scalar_one_or_none()
    if not item or (item.owner_id != user.id and user.role != "admin"):
        fail("系列不存在或无权访问", 404)
    return item


async def _episode(db, episode_id: int, user, *, lock: bool = False) -> SeriesEpisode:
    query = select(SeriesEpisode).where(SeriesEpisode.id == episode_id)
    if lock:
        query = query.with_for_update()
    item = (await db.execute(query)).scalar_one_or_none()
    if not item or (item.owner_id != user.id and user.role != "admin"):
        fail("分集不存在或无权访问", 404)
    return item


async def _episode_data(db, item: SeriesEpisode, *, private: bool = False) -> dict:
    asset = await db.get(Asset, item.asset_id) if item.asset_id else None
    result = data(item, "id", "series_id", "episode_no", "title", "description", "copyright_price_fen", "unlock_price_fen", "share_bps", "source", "source_type", "version", "preview_status", "playback_status", "created_at")
    result.update(media_status=asset.status if asset else "missing", duration_seconds=asset.duration_seconds if asset else None)
    series = await db.get(Series, item.series_id)
    if series and episode_is_free(series, item):
        result["preview_status"] = "none"
    else:
        preview = await episode_preview_for(db, item)
        usable = preview and preview.status != "cancelled" and (preview.status != "done" or is_preview_key(preview.object_key, episode=True))
        result["preview_status"] = preview.status if usable else "none"
        result["preview_error"] = preview.error if usable else ""
    if private:
        result.update(data(item, "owner_id", "asset_id", "cover_asset_id", "audit_status", "listed", "blocked", "reason", "source_snapshot"))
        rights = (await db.execute(select(Rights).where(Rights.asset_id == item.asset_id))).scalar_one_or_none() if item.asset_id else None
        result.update(rights_ready=bool(rights and rights.basic_status == "approved" and rights.full_status == "approved"), rights_source=rights.details.get("source") if rights else None)
    return result


async def _series_data(db, item: Series, *, private: bool = False) -> dict:
    episodes = (await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == item.id).order_by(SeriesEpisode.episode_no))).scalars().all()
    result = data(item, "id", "title", "description", "category", "tags", "app_editions", "cover_asset_id", "sale_type", "copyright_price_fen", "free_episode_count", "created_at")
    result.update(await category_fields(db, item))
    from .curation import flags as curation_flags
    result.update(await curation_flags(db, "series", item.id))
    result["episode_count"] = len(episodes)
    result["episodes"] = [await _episode_data(db, episode, private=private) for episode in episodes]
    if private:
        result.update(data(item, "owner_id", "version", "audit_status", "listed", "blocked", "reason", "share_bps"))
        from .authorization import current, summary
        from .handoff import _view
        authorization = await current(db, item.owner_id)
        handoffs = await _latest_series_handoffs(db, item.id)
        result.update(authorization_ready=bool(authorization), authorization=summary(authorization),
                      sync_in_progress=any(handoff.status in ("pending", "running") for handoff in handoffs),
                      pending_handoffs=[await _view(db, handoff) for handoff in handoffs])
    return result


def public_series_filters():
    """免费集检查原片，收费集检查当前版本短试看，实时校验权属限制。"""
    from .letter_template import PUBLISHED_VERSIONS
    proof = or_(and_(Rights.details["source"].as_string() == "printfilm",
                     Rights.details["authorization_id"].as_string().is_not(None),
                     Rights.details["authorization_version"].as_string().in_(PUBLISHED_VERSIONS)),
                and_(Rights.details["source"].as_string() != "printfilm", Rights.certificate_asset_id.is_not(None)))
    asset_ready = select(Asset.id).join(Rights, Rights.asset_id == Asset.id).where(
        Asset.id == SeriesEpisode.asset_id, Asset.status == "ready", Asset.owner_id == Series.owner_id,
        Rights.basic_status == "approved", Rights.full_status == "approved", Rights.blocked.is_(False),
        Rights.details["source"].as_string() == SeriesEpisode.source, proof,
        or_(Rights.valid_until.is_(None), Rights.valid_until > now()),
    ).correlate(Series, SeriesEpisode).exists()
    preview_ready = select(EpisodePreview.id).where(
        EpisodePreview.episode_id == SeriesEpisode.id, EpisodePreview.asset_id == SeriesEpisode.asset_id,
        EpisodePreview.version == SeriesEpisode.version, EpisodePreview.status == "done",
        EpisodePreview.object_key.startswith(CLIP_EPISODE_PREFIX),
    ).correlate(SeriesEpisode).exists()
    free = or_(Series.sale_type == "free", SeriesEpisode.episode_no <= Series.free_episode_count)
    missing = select(SeriesEpisode.id).where(
        SeriesEpisode.series_id == Series.id,
        or_(SeriesEpisode.blocked.is_(True), SeriesEpisode.listed.is_(False),
            SeriesEpisode.audit_status != "approved", not_(asset_ready), and_(not_(free), not_(preview_ready))),
    ).correlate(Series).exists()
    has_episode = select(SeriesEpisode.id).where(SeriesEpisode.series_id == Series.id).correlate(Series).exists()
    return (Series.listed.is_(True), Series.blocked.is_(False), Series.deleted_at.is_(None), Series.audit_status == "approved", has_episode, not_(missing))


@router.get(
    "/series", response_model=dict,
    summary='分页查询公开短剧系列',
    description='允许访客访问。按标题 q、分类 category 筛选已公开系列，按 ID 倒序分页；仅返回满足系列及分集公开条件的内容。',
    response_description='系列详情 items 与分页信息 meta。',
)
async def list_series(db: DB, q: str = Query("", max_length=100), category: str = Query("", max_length=60), category_code: str = Query("", max_length=80), page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100)):
    query = select(Series).where(*public_series_filters())
    if q:
        query = query.where(Series.title.ilike(f"%{q}%"))
    if category or category_code:
        query = query.where(await category_filter(db, Series, category, category_code))
    records, meta = await page(db, query.order_by(Series.id.desc()), page_number, page_size)
    return {"items": [await _series_data(db, row) for row in records], "meta": meta}


@router.get(
    "/series/import-sources", response_model=dict,
    summary='获取可导入的漫剧项目与分集',
    description='登录后列出本人有权导入的漫剧项目及分集发布上下文，供明确选择导入内容。',
    response_description='items 列表，包含项目 ID、标题及分集信息。',
)
async def import_sources(db: DB, user: Actor):
    """列出当前用户可明确选择导入的漫剧项目和已生成分集。"""
    from .drama_publish import publish_context
    active_teams = select(TeamMember.team_id).where(
        TeamMember.user_id == user.id, TeamMember.active.is_(True),
    )
    projects = list((await db.execute(select(DramaProject).where(
        DramaProject.user_id == user.id,
        or_(DramaProject.team_id.is_(None), DramaProject.team_id.in_(active_teams)),
    ).order_by(DramaProject.id.desc()))).scalars().all())
    result = []
    for project in projects:
        context = await publish_context(project.id, db, user)
        result.append({"id": project.id, "title": project.title, "episodes": context["episodes"]})
    return {"items": result}


@router.get(
    "/series/{series_id}", response_model=dict,
    summary='获取短剧系列详情',
    description='访客仅可读取公开系列；作者和管理员可查看未删除的草稿及审核信息。不存在或无权访问时返回 404。',
    response_description='系列详情及按权限返回的分集信息。',
)
async def get_series(series_id: int, db: DB, user: Visitor):
    item = await db.get(Series, series_id)
    private = bool(item and user and not item.deleted_at and (item.owner_id == user.id or user.role == "admin"))
    if not item or item.deleted_at or (not private and item.blocked):
        fail("系列不存在或未公开", 404)
    if not private:
        visible = (await db.execute(select(Series.id).where(Series.id == series_id, *public_series_filters()))).scalar_one_or_none()
        if not visible:
            fail("系列不存在或未公开", 404)
    return await _series_data(db, item, private=private)


@router.post(
    "/series", response_model=dict,
    summary='创建短剧系列草稿',
    description='登录后创建自己的短剧系列。分类须有效，绑定封面须为本人已就绪的图片资产。',
    response_description='新建系列的草稿详情。',
)
async def create_series(body: SeriesInput, db: DB, user: Actor):
    await normalize_category_input(db, body)
    if body.cover_asset_id:
        await asset_owned(db, body.cover_asset_id, user, ("image",))
    values = body.model_dump()
    item = Series(owner_id=user.id, **values)
    item.sale_type = _sale_type(item.sale_type, item.copyright_price_fen)
    db.add(item)
    await db.commit()
    return await _series_data(db, item, private=True)


@router.patch(
    "/series/{series_id}", response_model=dict,
    summary='更新短剧系列草稿',
    description='系列作者或管理员可操作，须提交当前 version。保存后递增系列版本、重置草稿并暂停系列销售；同步重置当前分集发布状态，进行中的同步任务或版本冲突返回 409。',
    response_description='更新后的系列草稿详情。',
)
async def update_series(series_id: int, body: SeriesUpdate, db: DB, user: Actor):
    item = await _series(db, series_id, user, lock=True)
    from .service import ensure_kept
    ensure_kept(item)
    check_version(item, body.version)
    await ensure_series_idle(db, item.id)
    await normalize_category_input(db, body, item)
    if body.cover_asset_id:
        await asset_owned(db, body.cover_asset_id, user, ("image",))
    values = body.model_dump(exclude={"version"})
    from .distribution import keep_editions
    keep_editions(body, values)
    values["sale_type"] = _sale_type(values["sale_type"], values["copyright_price_fen"])
    for key, value in values.items():
        setattr(item, key, value)
    item.version += 1
    item.audit_status, item.listed, item.reason = "draft", False, ""
    await pause_series_sales(db, item, bump_episode_versions=True)
    await db.commit()
    return await _series_data(db, item, private=True)


@router.post(
    "/series/{series_id}/episodes", response_model=dict,
    summary='添加短剧分集草稿',
    description='系列作者或管理员可操作。分集编号在系列内须唯一，媒体和封面须为当前操作者本人的资产；平台解锁系列的非免费集须设置正数解锁价。新增后系列回到草稿并暂停销售。',
    response_description='新建分集草稿详情。',
)
async def create_episode(series_id: int, body: EpisodeInput, db: DB, user: Actor):
    series = await _series(db, series_id, user, lock=True)
    from .service import ensure_kept
    ensure_kept(series)
    await ensure_series_idle(db, series.id)
    duplicate = (await db.execute(select(SeriesEpisode.id).where(SeriesEpisode.series_id == series.id, SeriesEpisode.episode_no == body.episode_no))).scalar_one_or_none()
    if duplicate:
        fail("该集数已经存在", 409)
    if body.asset_id:
        await asset_owned_for_draft(db, body.asset_id, user)
    if body.cover_asset_id:
        await asset_owned(db, body.cover_asset_id, user, ("image",))
    item = SeriesEpisode(series_id=series.id, owner_id=user.id, source_type="upload", **body.model_dump())
    if series.sale_type == "platform_unlock" and not episode_is_free(series, item) and item.unlock_price_fen <= 0:
        fail("平台投放系列必须为每集设置解锁价")
    db.add(item)
    series.version += 1
    series.audit_status, series.listed = "draft", False
    await pause_series_sales(db, series)
    await db.commit()
    return await _episode_data(db, item, private=True)


@router.patch(
    "/series/{series_id}/episodes/{episode_id}", response_model=dict,
    summary='更新短剧分集草稿',
    description='系列作者或管理员可操作，须匹配分集当前 version，并确认分集属于路径中的系列。保存后系列和分集回到草稿并暂停销售；手动替换媒体会解除原导入来源映射。',
    response_description='更新后的分集草稿详情。',
)
async def update_episode(series_id: int, episode_id: int, body: EpisodeUpdate, db: DB, user: Actor):
    series = await _series(db, series_id, user, lock=True)
    from .service import ensure_kept
    ensure_kept(series)
    await ensure_series_idle(db, series.id)
    item = await _episode(db, episode_id, user, lock=True)
    if item.series_id != series.id:
        fail("分集不属于该系列", 404)
    check_version(item, body.version)
    if body.asset_id:
        await asset_owned_for_draft(db, body.asset_id, user)
    if body.cover_asset_id:
        await asset_owned(db, body.cover_asset_id, user, ("image",))
    asset_changed = body.asset_id != item.asset_id
    for key, value in body.model_dump(exclude={"version"}).items():
        setattr(item, key, value)
    if asset_changed:
        # A manually replaced video no longer represents the frozen imported
        # source. Keep historical tasks/publications, but detach the live mapping.
        item.source_type, item.source_snapshot = "upload", {}
        item.preview_status, item.preview_key, item.preview_attempts = "none", None, 0
        item.playback_status, item.playback_manifest_key, item.playback_attempts = "none", None, 0
    item.version += 1
    item.audit_status, item.listed, item.reason = "draft", False, ""
    item.preview_status, item.preview_key, item.preview_attempts = "none", None, 0
    await cancel_episode_previews(db, item)
    series.version += 1
    series.audit_status, series.listed = "draft", False
    await pause_series_sales(db, series)
    await db.commit()
    return await _episode_data(db, item, private=True)


@router.delete(
    "/series/{series_id}/episodes/{episode_id}", response_model=dict,
    summary='删除短剧分集草稿',
    description='系列作者或管理员可操作。已有订单或购买权益的分集不可删除，返回 409；删除后系列递增版本、回到草稿并暂停销售。',
    response_description='操作成功时返回 ok=true。',
)
async def delete_episode(series_id: int, episode_id: int, db: DB, user: Actor):
    series = await _series(db, series_id, user, lock=True)
    from .service import ensure_kept
    ensure_kept(series)
    await ensure_series_idle(db, series.id)
    item = await _episode(db, episode_id, user, lock=True)
    if item.series_id != series.id:
        fail("分集不属于该系列", 404)
    has_order = (await db.execute(select(ContentOrder.id).where(ContentOrder.episode_id == item.id).limit(1))).scalar_one_or_none()
    has_entitlement = (await db.execute(select(Entitlement.id).where(Entitlement.episode_id == item.id).limit(1))).scalar_one_or_none()
    if has_order or has_entitlement:
        fail("该分集已有订单或购买权益，不能删除；请下架系列并保留记录", 409)
    await pause_series_sales(db, series)
    await db.delete(item)
    series.version += 1
    series.audit_status, series.listed = "draft", False
    await db.commit()
    return {"ok": True}


@router.post(
    "/series/{series_id}/episodes/import", response_model=dict,
    summary='导入选中的漫剧分集',
    description='仅系列作者可操作。将明确选中的漫剧分集登记为系列分集草稿，冻结来源版本并排队异步转存；请求返回后通过 handoffs 查询进度。',
    response_description='目标系列、分集草稿 items 与异步转存记录 handoffs。',
)
async def import_episodes(series_id: int, body: ImportEpisodesInput, db: DB, user: Actor):
    """只导入用户明确选择的漫剧分集。复制交给市场 Worker，请求本身不等待长视频。"""
    from .handoff import enqueue_series_import
    from .schemas import PrintfilmEpisodeInput

    payload = PrintfilmEpisodeInput(drama_project_id=body.drama_project_id, episode_ids=list(body.episode_ids))
    return await enqueue_series_import(series_id, payload, db, user)


@router.delete(
    "/series/{series_id}", response_model=dict,
    summary='删除自己的短剧系列',
    description='仅作者可操作。软删除系列，使其退出公开目录与个人作品列表；保留分集、媒体和历史发布记录。',
    response_description='操作成功时返回 ok=true。',
)
async def delete_series(series_id: int, db: DB, user: Actor):
    """作者软删整部短剧。分集记录保留，但不再出现在广场和我的作品。"""
    item = await _series(db, series_id, user, lock=True)
    from .service import retire_owned
    await retire_owned(db, item, user, "series")
    await db.commit()
    return {"ok": True}


@router.post(
    "/series/{series_id}/submit", response_model=dict,
    summary='提交短剧系列与各集版权审核',
    description='仅作者可操作，须提交当前系列 version。至少包含一集且从第 1 集连续编号；逐集检查媒体、封面和完整版权，收费分集先准备短试看。未完成试看时进入 processing，就绪后进入 pending。',
    response_description='提交后的系列详情及分集处理状态。',
)
async def submit_series(series_id: int, body: Version, db: DB, user: Actor):
    series = await _series(db, series_id, user, lock=True)
    from .service import ensure_kept
    ensure_kept(series)
    check_version(series, body.version)
    await ensure_series_idle(db, series.id, submitting=True)
    if series.blocked:
        fail("系列已被管理员封禁")
    if series.audit_status in ("pending", "processing", "approved"):
        return await _series_data(db, series, private=True)
    episodes = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == series.id).order_by(SeriesEpisode.episode_no).with_for_update())).scalars().all())
    if not episodes:
        fail("至少添加一集后才能提交审核")
    if [episode.episode_no for episode in episodes] != list(range(1, len(episodes) + 1)):
        fail("分集编号必须从1开始连续排列")
    config = await db.get(RevenueConfig, 1)
    if series.sale_type == "platform_unlock" and (not config or not config.enabled):
        fail("MARKETPLACE_REVENUE_CONFIG_REQUIRED", 409)
    # 只有收费分集需要短试看。免费系列/免费集不依赖生成任务。
    if any(not episode_is_free(series, episode) for episode in episodes):
        await storage_ready()
    pending_preview = False
    await pause_series_sales(db, series)
    for episode in episodes:
        if episode.blocked:
            fail(f"第{episode.episode_no}集已被限制发布", 409)
        asset = await asset_owned(db, episode.asset_id or 0, user)
        if not episode.cover_asset_id and not series.cover_asset_id:
            fail(f"第{episode.episode_no}集缺少封面，请上传分集封面或系列封面", 409)
        if episode.source == "printfilm":
            from .drama_publish import ensure_import_rights
            await ensure_import_rights(db, episode)
        rights = (await db.execute(select(Rights).where(Rights.asset_id == asset.id).with_for_update())).scalar_one_or_none()
        if not rights or rights.blocked:
            fail("请完成每集版权信息后再提交", 409)
        if rights.details.get("source") != episode.source:
            fail(f"第{episode.episode_no}集版权来源与分集来源不匹配", 409)
        validate_rights(rights.details, full=True, certificate=bool(rights.certificate_asset_id))
        if rights.valid_until and rights.valid_until <= now():
            fail(f"第{episode.episode_no}集版权授权已过期", 409)
        free = episode_is_free(series, episode)
        if series.sale_type == "platform_unlock" and not free and episode.unlock_price_fen <= 0:
            fail(f"第{episode.episode_no}集必须设置解锁价")
        publication = (await db.execute(select(Publication).where(
            Publication.content_type == "series_episode", Publication.content_id == episode.id,
            Publication.version == episode.version).with_for_update())).scalar_one_or_none()
        if publication and publication.audit_status == "approved":
            # The series may be re-reviewed because another episode changed.
            # Never reset an approved version's media, financial or rights snapshot.
            episode.version += 1
            publication = None
        if free:
            await cancel_episode_previews(db, episode)
            preview, preview_status = None, "none"
        else:
            preview = await prepare_episode_preview(db, episode)
            preview_status = "done" if preview.status == "done" and is_preview_key(preview.object_key, episode=True) else "pending"
        pending_preview = pending_preview or (not free and preview_status != "done")
        share = episode.share_bps if episode.share_bps is not None else (
            series.share_bps if series.share_bps is not None else (config.platform_share_bps if config else None))
        values = dict(owner_id=user.id, version=episode.version, asset_id=asset.id,
                      cover_asset_id=episode.cover_asset_id or series.cover_asset_id, sale_type=series.sale_type,
                      copyright_price_fen=episode.copyright_price_fen or series.copyright_price_fen,
                      unlock_price_fen=0 if free else episode.unlock_price_fen, share_bps=share,
                      rights_snapshot={"details": rights.details, "certificate_asset_id": rights.certificate_asset_id,
                                       "evidence_ids": rights.evidence_ids}, audit_status="pending", listed=False,
                      preview_status=preview_status, preview_key=preview.object_key if preview and preview_status == "done" else None,
                      preview_error="", playback_status="done" if free or series.sale_type != "platform_unlock" else "pending")
        episode.preview_status = preview_status
        episode.preview_key = preview.object_key if preview and preview_status == "done" else None
        episode.playback_status = "done" if free or series.sale_type != "platform_unlock" else "pending"
        if publication is None:
            publication = Publication(content_type="series_episode", content_id=episode.id, **values)
            db.add(publication)
        else:
            for key, value in values.items():
                setattr(publication, key, value)
        if series.sale_type == "platform_unlock" and not free:
            await db.flush()
            playback_job = (await db.execute(select(PlaybackJob).where(
                PlaybackJob.publication_id == publication.id
            ).with_for_update())).scalar_one_or_none()
            if playback_job is None:
                db.add(PlaybackJob(publication_id=publication.id, status="pending"))
            else:
                playback_job.status, playback_job.error = "pending", ""
                playback_job.attempts = 0
                playback_job.lease_token, playback_job.lease_until = None, None
            publication.playback_manifest_key = None
            publication.playback_error = ""
        episode.audit_status = "pending"
        episode.listed = False
        rights.basic_status = rights.full_status = "pending"
    series.audit_status = "processing" if pending_preview else "pending"
    series.listed, series.reason = False, "正在生成短试看" if pending_preview else ""
    event(db, user.id, "series", series.id, "submitted", version=series.version)
    await db.commit()
    return await _series_data(db, series, private=True)


@router.post(
    "/series/{series_id}/preview/retry", response_model=dict,
    summary='重试短剧收费分集的短试看',
    description='仅系列作者可操作，须提交当前 version，且系列已提交审核、媒体与版权仍有效。重试当前收费分集的衍生短片；免费集跳过，已审核发布版本与已购 HLS 播放文件保持原样。',
    response_description='系列详情及最新分集试看状态。',
)
async def retry_series_preview(series_id: int, body: Version, db: DB, user: Actor):
    """仅重试当前分集的衍生短片，不更改已审核版本、权益或 HLS。"""
    series = await _series(db, series_id, user, lock=True)
    if series.owner_id != user.id:
        fail("系列不存在或无权操作", 404)
    from .service import ensure_kept
    from .previews import series_submission_ready
    ensure_kept(series)
    check_version(series, body.version)
    await ensure_series_idle(db, series.id, submitting=True)
    if series.audit_status not in ("approved", "pending", "processing", "preview_failed"):
        fail("请先提交系列审核", 409)
    if not await series_submission_ready(db, series):
        fail("系列媒体或版权资料已变化，请编辑后重新提交审核", 409)
    episodes = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == series.id)
        .order_by(SeriesEpisode.id).with_for_update())).scalars().all())
    if any(not episode_is_free(series, episode) for episode in episodes):
        await storage_ready()
    pending = False
    for episode in episodes:
        if episode_is_free(series, episode):
            await cancel_episode_previews(db, episode)
            episode.preview_status, episode.preview_key = "none", None
            continue
        preview = await prepare_episode_preview(db, episode)
        episode.preview_status, episode.preview_key = preview.status, preview.object_key
        pending = pending or preview.status != "done"
    if series.audit_status != "approved":
        series.audit_status, series.reason = ("processing", "正在生成短试看") if pending else ("pending", "")
    await db.commit()
    return await _series_data(db, series, private=True)


@router.post(
    "/series/{series_id}/listing", response_model=dict,
    summary='设置短剧系列上下架状态',
    description='系列作者或管理员可操作，须提交当前 version；listed 默认为 true，false 表示下架。上架要求系列与各集通过审核、版权材料及必要试看有效，平台收费集还须完成播放打包。仅当前发布版本参与本次上下架。',
    response_description='更新上下架状态后的系列详情。',
)
async def listing_series(series_id: int, body: Version, db: DB, user: Actor, listed: bool = True):
    series = await _series(db, series_id, user, lock=True)
    from .service import ensure_kept
    ensure_kept(series)
    check_version(series, body.version)
    # Lock and snapshot the current episode versions once.  Historical
    # publications are kept for entitlements but must never be relisted when a
    # newer episode version is approved.
    episodes = list((await db.execute(
        select(SeriesEpisode).where(SeriesEpisode.series_id == series.id)
        .order_by(SeriesEpisode.id).with_for_update()
    )).scalars().all())
    if listed:
        if series.blocked or series.audit_status != "approved":
            fail("系列内容或权属尚未通过，不能上架")
        if not episodes:
            fail("系列没有可上架的分集")
        from .previews import series_submission_ready
        if not await series_submission_ready(db, series):
            fail("媒体、版权材料或授权已变化，请重新提交审核", 409)
        for episode in episodes:
            if episode.blocked or episode.audit_status != "approved":
                fail(f"第{episode.episode_no}集尚未审核通过")
            if not await episode_preview_ready(db, series, episode):
                fail(f"第{episode.episode_no}集短试看尚未生成", 409)
            if series.sale_type == "platform_unlock" and not episode_is_free(series, episode):
                publication = (await db.execute(select(Publication).where(Publication.content_type == "series_episode", Publication.content_id == episode.id, Publication.version == episode.version))).scalar_one_or_none()
                if not publication or publication.playback_status != "done":
                    fail(f"第{episode.episode_no}集播放版本尚未就绪", 409)
    series.listed = listed
    episode_ids = [episode.id for episode in episodes]
    publications = []
    if episode_ids:
        publications = list((await db.execute(
            select(Publication).where(
                Publication.content_type == "series_episode",
                Publication.content_id.in_(episode_ids),
            ).with_for_update()
        )).scalars().all())
    for publication in publications:
        is_current = any(
            episode.id == publication.content_id and episode.version == publication.version
            for episode in episodes
        )
        publication.listed = listed and is_current and publication.audit_status == "approved" and (
            series.sale_type != "platform_unlock" or publication.playback_status == "done"
            or any(episode.id == publication.content_id and episode_is_free(series, episode) for episode in episodes)
        )
    for episode in episodes:
        episode.listed = listed and episode.audit_status == "approved" and not episode.blocked
    if listed:
        await db.flush()
        from .app_engagement import initialize_target
        for episode in episodes:
            await initialize_target(db, "series_episode", episode.id, automatic=True)
    await db.commit()
    return await _series_data(db, series, private=True)

