"""公开目录和作者工作台；只操作 marketplace_ 表。"""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, literal, select, union_all

from app.models import User
from .categories import category_fields, category_filter, normalize_category_input
from .dependencies import Actor, DB, Visitor
from .curation import join_curation, ordering_columns
from .previews import cancel_work_previews, prepare_preview, preview_ready, requires_preview
from .models import Asset, Handoff, PlaybackJob, Publication, Recruit, RegistrationCase, RevenueConfig, Rights, Series, SeriesEpisode, Submission, Work
from .schemas import CaseInput, RecruitInput, RecruitUpdate, RightsInput, Version, WorkInput, WorkUpdate
from .service import (asset_owned, asset_owned_for_draft, check_version, data, ensure_kept, event, fail, get_target, is_public_work, now,
                      notify, owned, page, public_recruit_filters, public_work_filters, recruit_data,
                      recruit_open, rights_for, rights_valid, submission_data, validate_rights, work_data)

router = APIRouter()


async def _pause_work_sales(db, work_id: int) -> None:
    publications = list((await db.execute(select(Publication).where(
        Publication.content_type == "work", Publication.content_id == work_id,
    ).with_for_update())).scalars().all())
    for publication in publications:
        publication.listed = False


async def _ensure_work_idle(db, work_id: int) -> None:
    active = (await db.execute(select(Handoff.id).where(
        Handoff.target_kind == "work", Handoff.target_id == work_id,
        Handoff.status.in_(("pending", "running")),
    ).limit(1))).scalar_one_or_none()
    if active:
        fail("MARKETPLACE_SYNC_IN_PROGRESS", 409)


@router.get(
    "/categories", response_model=dict,
    summary='获取市场分类',
    description='返回市场当前可使用的分类名称及配置版本，允许访客访问。',
    response_description='分类名称列表 names 与配置版本 version。',
)
async def get_categories(db: DB):
    from .categories import category_config
    return await category_config(db)


async def catalog_item(db, kind: str, item_id: int) -> dict:
    """把单视频和短剧收成广场卡片；短剧不展开分集正文。"""
    if kind == "work":
        payload = await work_data(db, await db.get(Work, item_id))
        payload["kind"] = "work"
        return payload
    from .series import _series_data
    series = await db.get(Series, item_id)
    detail = await _series_data(db, series)
    owner = await db.get(User, series.owner_id)
    return {"is_featured": detail["is_featured"], "is_pinned": detail["is_pinned"], "kind": "series", "id": series.id, "title": series.title, "description": series.description,
            **await category_fields(db, series), "category": series.category, "sale_type": series.sale_type, "price_fen": series.copyright_price_fen,
            "author": owner.nickname if owner else "创作者", "episode_count": detail["episode_count"],
            "free_episode_count": series.free_episode_count,
            "cover_asset_id": series.cover_asset_id, "created_at": series.created_at}


@router.get(
    "/works", response_model=dict,
    summary='分页查询作品广场',
    description='合并单视频与短剧系列后筛选、排序并分页；仅展示满足公开条件的内容。q 搜索标题，category 按分类筛选，价格单位为人民币分；sort 支持 recommended（默认）、latest、price_asc、price_desc。',
    response_description='作品卡片 items 与分页信息 meta，kind 区分 work 和 series。',
)
async def works(db: DB, q: str = Query("", max_length=100), category: str = Query("", max_length=60), category_code: str = Query("", max_length=80),
                min_price: int | None = Query(None, ge=0), max_price: int | None = Query(None, ge=0),
                sort: str = "recommended", page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100)):
    """单视频和短剧共用作品广场，筛选后再分页。"""
    from .series import public_series_filters
    if sort not in {"recommended", "latest", "price_asc", "price_desc"}:
        fail("排序参数无效")
    work_query = select(Work.id.label("item_id"), literal("work").label("kind"), Work.created_at.label("sort_at"),
                        Work.price_fen.label("price")).join(Asset, Asset.id == Work.asset_id).join(Rights, Rights.asset_id == Asset.id).where(*public_work_filters())
    series_query = select(Series.id.label("item_id"), literal("series").label("kind"), Series.created_at.label("sort_at"),
                          Series.copyright_price_fen.label("price")).where(*public_series_filters())
    if q:
        work_query = work_query.where(Work.title.ilike(f"%{q}%"))
        series_query = series_query.where(Series.title.ilike(f"%{q}%"))
    if category or category_code:
        work_query = work_query.where(await category_filter(db, Work, category, category_code))
        series_query = series_query.where(await category_filter(db, Series, category, category_code))
    if min_price is not None:
        work_query = work_query.where(Work.price_fen >= min_price)
        series_query = series_query.where(Series.copyright_price_fen >= min_price)
    if max_price is not None:
        work_query = work_query.where(Work.price_fen <= max_price)
        series_query = series_query.where(Series.copyright_price_fen <= max_price)
    work_query = join_curation(work_query, Work, "work").add_columns(*ordering_columns())
    series_query = join_curation(series_query, Series, "series").add_columns(*ordering_columns())
    combined = union_all(work_query, series_query).subquery()
    total = (await db.execute(select(func.count()).select_from(combined))).scalar_one()
    chronological = [combined.c.sort_at.desc(), combined.c.kind.desc(), combined.c.item_id.desc()]
    ordering = {"recommended": [combined.c.pin.desc(), combined.c.priority.desc(), combined.c.feature.desc(), *chronological],
                "latest": chronological, "price_asc": [combined.c.price.asc(), *chronological], "price_desc": [combined.c.price.desc(), *chronological]}
    rows = (await db.execute(select(combined).order_by(*ordering[sort])
                             .offset((page_number - 1) * page_size).limit(page_size))).all()
    return {"items": [await catalog_item(db, row.kind, row.item_id) for row in rows],
            "meta": {"page": page_number, "page_size": page_size, "total": total}}


@router.get(
    "/works/{work_id}", response_model=dict,
    summary='获取单视频作品详情',
    description='访客仅可读取已公开作品；作者和管理员可读取未删除的草稿及审核状态。不存在、已删除或无权查看时返回 404。',
    response_description='作品详情；有管理权限时包含草稿和审核信息。',
)
async def work_detail(work_id: int, db: DB, user: Visitor):
    """作者和管理员可看草稿，公众仅可看满足全部条件的作品。"""
    item = await db.get(Work, work_id)
    private = bool(item and user and not item.deleted_at and (item.owner_id == user.id or user.role == "admin"))
    if not item or item.deleted_at or (not private and not await is_public_work(db, work_id)):
        fail("作品不存在或未公开", 404)
    return await work_data(db, item, private)


@router.post(
    "/works", response_model=dict,
    summary='创建单视频作品草稿',
    description='登录后创建自己的作品草稿。纯文字草稿可不绑定媒体；绑定的视频与封面须为本人可用的资产，分类须有效。',
    response_description='新建作品的完整草稿信息。',
)
async def create_work(body: WorkInput, db: DB, user: Actor):
    """文字草稿无需 OSS，绑定媒体时只能选择本人的 ready 资产。"""
    await normalize_category_input(db, body)
    if body.asset_id:
        await asset_owned_for_draft(db, body.asset_id, user)
    if body.cover_asset_id:
        await asset_owned(db, body.cover_asset_id, user, ("image",))
    values = body.model_dump()
    item = Work(owner_id=user.id, **values)
    db.add(item)
    await db.commit()
    return await work_data(db, item, True)


@router.put(
    "/works/{work_id}", response_model=dict,
    summary='更新单视频作品草稿',
    description='仅作者可操作，须提交当前 version。保存后递增版本、重置为草稿并下架；授权用途或来源变化还会重置相应权属核验。存在进行中的同步任务或版本冲突时返回 409。',
    response_description='更新后的作品草稿及版本信息。',
)
async def update_work(work_id: int, body: WorkUpdate, db: DB, user: Actor):
    """更新即撤下旧公开内容；权利范围变化重置完整核验。"""
    item = await owned(db, Work, work_id, user)
    ensure_kept(item)
    check_version(item, body.version)
    await _ensure_work_idle(db, item.id)
    await normalize_category_input(db, body, item)
    if body.asset_id:
        await asset_owned_for_draft(db, body.asset_id, user)
    if body.cover_asset_id:
        await asset_owned(db, body.cover_asset_id, user, ("image",))
    if item.license_scope != body.license_scope or item.source != body.source:
        rights = await rights_for(db, body.asset_id, lock=True)
        if rights:
            rights.full_status = "draft"
            rights.version += 1
    values = body.model_dump(exclude={"version"})
    from .distribution import keep_editions
    keep_editions(body, values)
    for key, value in values.items():
        setattr(item, key, value)
    item.version += 1
    item.audit_status, item.listed, item.reason = "draft", False, ""
    await cancel_work_previews(db, item)
    await _pause_work_sales(db, item.id)
    event(db, user.id, "work", item.id, "updated", version=item.version)
    await db.commit()
    return await work_data(db, item, True)


@router.post(
    "/works/{work_id}/submit", response_model=dict,
    summary='提交单视频作品与版权审核',
    description='仅作者可操作，须提交当前 version。校验媒体、授权用途和完整版权材料后统一送审；收费作品的短试看未就绪时先进入 processing，完成后进入待审核。平台解锁作品还须配置分成与解锁价格。',
    response_description='提交后的作品详情及审核、试看处理状态。',
)
async def submit_work(work_id: int, body: Version, db: DB, user: Actor):
    """作品资料和版权信息一次提交，进入统一管理员审核。"""
    item = await owned(db, Work, work_id, user)
    ensure_kept(item)
    check_version(item, body.version)
    await _ensure_work_idle(db, item.id)
    if item.blocked:
        fail("作品已被管理员封禁")
    if item.audit_status in ("pending", "processing", "approved"):
        return await work_data(db, item, True)
    await asset_owned(db, item.asset_id or 0, user)
    rights = await rights_for(db, item.asset_id, lock=True)
    if not item.license_scope.strip():
        fail("请在作品草稿中填写“拟授权用途及限制”后再提交审核")
    if not rights or rights.blocked or rights.details.get("source") != item.source:
        fail("请先填写版权信息和授权意向")
    validate_rights(rights.details, full=True, certificate=bool(rights.certificate_asset_id))
    if rights.valid_until and rights.valid_until <= now():
        fail("版权授权已过期")
    # 新版合格短片仅按同一资产复用，免费作品不创建任何试看任务。
    if requires_preview(item.sale_type):
        if not await preview_ready(db, item):
            from .dependencies import storage_ready
            await storage_ready()
        preview = await prepare_preview(db, item)
    else:
        await cancel_work_previews(db, item)
        preview = None
    clip_ready = await preview_ready(db, item)
    if requires_preview(item.sale_type) and not clip_ready:
        item.audit_status, item.listed, item.reason = "processing", False, "正在生成短试看"
    else:
        item.audit_status, item.listed, item.reason = "pending", False, ""
    config = None
    if item.sale_type == "platform_unlock":
        config = await db.get(RevenueConfig, 1)
        if not config or not config.enabled:
            fail("MARKETPLACE_REVENUE_CONFIG_REQUIRED", 409)
        if item.unlock_price_fen <= 0:
            fail("平台投放作品必须设置解锁价", 409)
    if item.audit_status in ("pending", "processing"):
        await _pause_work_sales(db, item.id)
        publication = (await db.execute(select(Publication).where(
            Publication.content_type == "work", Publication.content_id == item.id,
            Publication.version == item.version).with_for_update())).scalar_one_or_none()
        if publication and publication.audit_status == "approved":
            item.version += 1
            publication = None
        values = dict(owner_id=user.id, version=item.version, asset_id=item.asset_id,
                      cover_asset_id=item.cover_asset_id, sale_type=item.sale_type,
                      copyright_price_fen=item.price_fen, unlock_price_fen=item.unlock_price_fen,
                      share_bps=item.share_bps if item.share_bps is not None else (config.platform_share_bps if config else None), rights_snapshot={"details": rights.details,
                      "certificate_asset_id": rights.certificate_asset_id, "evidence_ids": rights.evidence_ids},
                      audit_status=item.audit_status if item.audit_status == "pending" else "draft",
                      preview_status=("done" if clip_ready else "pending") if requires_preview(item.sale_type) else "none",
                      preview_key=preview.object_key if preview and clip_ready else None,
                      preview_error="",
                      playback_status="done" if item.sale_type != "platform_unlock" else "pending")
        if publication is None:
            publication = Publication(content_type="work", content_id=item.id, **values)
            db.add(publication)
        else:
            for key, value in values.items():
                setattr(publication, key, value)
        # A durable playback job gives the market Worker a lease and restart
        # recovery point.  It is intentionally created only for platform
        # content; free/contact works never need HLS packaging.
        if item.sale_type == "platform_unlock":
            playback_job = (await db.execute(select(PlaybackJob).where(
                PlaybackJob.publication_id == publication.id
            ).with_for_update())).scalar_one_or_none() if publication.id else None
            if playback_job is None:
                # New publications have no database id until flush; the FK is
                # populated after the explicit flush below.
                await db.flush()
                playback_job = (await db.execute(select(PlaybackJob).where(
                    PlaybackJob.publication_id == publication.id
                ).with_for_update())).scalar_one_or_none()
            if playback_job is None:
                db.add(PlaybackJob(publication_id=publication.id, status="pending"))
            else:
                # Re-submitting the same draft version invalidates any prior
                # package attempt; never leave a done job paired with a pending
                # publication snapshot.
                playback_job.status, playback_job.error = "pending", ""
                playback_job.attempts = 0
                playback_job.lease_token, playback_job.lease_until = None, None
            publication.playback_manifest_key = None
            publication.playback_error = ""
    rights.basic_status = rights.full_status = "pending"
    if item.audit_status == "pending":
        event(db, user.id, "work", item.id, "submitted", version=item.version)
    await db.commit()
    return await work_data(db, item, True)


@router.post(
    "/works/{work_id}/listing", response_model=dict,
    summary='设置单视频作品上下架状态',
    description='仅作者可操作，须提交当前 version；listed 默认为 true，传 false 下架。上架要求内容与完整权属审核通过、媒体和必要试看就绪；平台解锁作品还须完成播放打包，封禁内容不能上架。',
    response_description='更新上下架状态后的作品详情。',
)
async def listing(work_id: int, body: Version, db: DB, user: Actor, listed: bool = True):
    """作者主动上下架，不允许自行解除管理员封禁。"""
    item = await owned(db, Work, work_id, user)
    ensure_kept(item)
    check_version(item, body.version)
    if listed:
        if requires_preview(item.sale_type) and not await preview_ready(db, item):
            fail("短试看尚未生成，请重新提交审核", 409)
        rights = await rights_for(db, item.asset_id, lock=True)
        asset = await db.get(Asset, item.asset_id) if item.asset_id else None
        if item.blocked or item.audit_status != "approved" or not asset or asset.status != "ready" or not rights_valid(rights, full=True) or rights.details.get("source") != item.source:
            fail("媒体、内容或权属尚未通过，不能上架")
        if item.sale_type == "platform_unlock":
            publication = (await db.execute(select(Publication).where(Publication.content_type == "work", Publication.content_id == item.id, Publication.version == item.version).with_for_update())).scalar_one_or_none()
            if not publication or publication.playback_status != "done":
                fail("平台播放版本尚未就绪，请稍后再上架", 409)
    item.listed = listed
    await _pause_work_sales(db, item.id)
    publication = (await db.execute(select(Publication).where(Publication.content_type == "work", Publication.content_id == item.id, Publication.version == item.version).with_for_update())).scalar_one_or_none()
    if publication:
        publication.listed = listed and publication.audit_status == "approved" and (item.sale_type != "platform_unlock" or publication.playback_status == "done")
    event(db, user.id, "work", item.id, "listed" if listed else "unlisted", version=item.version)
    if listed:
        await db.flush()
        from .app_engagement import initialize_target
        await initialize_target(db, "work", item.id, automatic=True)
    await db.commit()
    return await work_data(db, item, True)


@router.post(
    "/works/{work_id}/preview/retry", response_model=dict,
    summary='重试单视频作品短试看',
    description='仅作者可操作，须提交当前 version，且作品已提交过审核、媒体与版权材料仍有效。为需要试看的当前作品重新准备衍生短片任务；已审核发布版本及已购播放文件保持原样。',
    response_description='当前作品详情与最新试看处理状态。',
)
async def retry_work_preview(work_id: int, body: Version, db: DB, user: Actor):
    """仅重试当前作品的衍生短片，已审核版本和购买播放文件保持原样。"""
    item = await owned(db, Work, work_id, user)
    ensure_kept(item)
    check_version(item, body.version)
    await _ensure_work_idle(db, item.id)
    from .previews import work_submission_ready
    if item.audit_status not in ("approved", "pending", "processing", "preview_failed"):
        fail("请先提交作品审核", 409)
    if not await work_submission_ready(db, item):
        fail("作品媒体或版权资料已变化，请编辑后重新提交审核", 409)
    if requires_preview(item.sale_type):
        from .dependencies import storage_ready
        await storage_ready()
        preview = await prepare_preview(db, item)
        if item.audit_status != "approved":
            item.audit_status, item.reason = ("pending", "") if preview.status == "done" else ("processing", "正在生成短试看")
    else:
        await cancel_work_previews(db, item)
        if item.audit_status != "approved":
            item.audit_status, item.reason = "pending", ""
    await db.commit()
    return await work_data(db, item, True)


@router.delete(
    "/works/{work_id}", response_model=dict,
    summary='删除自己的单视频作品',
    description='仅作者可操作。软删除作品并退出公开展示与个人作品列表，保留原始媒体和审核记录。',
    response_description='操作成功时返回 ok=true。',
)
async def delete_work(work_id: int, db: DB, user: Actor):
    """作者软删单视频。广场和我的作品不再展示，原片与审核记录保留。"""
    item = await owned(db, Work, work_id, user)
    from .service import retire_owned
    await retire_owned(db, item, user, "work")
    await db.commit()
    return {"ok": True}


@router.get(
    "/assets/{asset_id}/rights", response_model=dict,
    summary='获取视频资产权属档案',
    description='仅资产所有者或管理员可查看，读取已有档案时记录访问事件。尚未建立档案时返回 version=0 与初始来源信息。',
    response_description='权属材料、审核状态和版本；无档案时返回初始信息。',
)
async def get_rights(asset_id: int, db: DB, user: Actor):
    """权属材料只允许本人或管理员读取，并保留访问记录。"""
    await owned(db, Asset, asset_id, user, admin=True)
    rights = await rights_for(db, asset_id)
    if not rights:
        source = (await db.execute(select(Work.source).where(Work.asset_id == asset_id, Work.owner_id == user.id).order_by(Work.id.desc()).limit(1))).scalar_one_or_none()
        return {"asset_id": asset_id, "version": 0, "details": {"source": source or "external"}}
    event(db, user.id, "rights", rights.id, "read")
    await db.commit()
    return data(rights, "id", "asset_id", "version", "details", "certificate_asset_id", "evidence_ids", "basic_status", "full_status", "valid_until", "blocked", "reason")


@router.put(
    "/assets/{asset_id}/rights", response_model=dict,
    summary='保存视频资产权属档案',
    description='仅资产所有者可操作。首次保存 version 为 0，修改须匹配当前版本；证明材料须属于本人且已就绪。PRINTFILM 来源须先签署授权函。保存后重置权属核验，并将关联作品、分集与系列撤回草稿和下架。',
    response_description='权属档案 ID 与保存后的 version。',
)
async def save_rights(asset_id: int, body: RightsInput, db: DB, user: Actor):
    """任何材料变动都重置核验结论，绑定不可变视频文件。"""
    # 与提交、Worker 一致：先锁父内容，再锁分集和权属，避免 Rights→Series 反向等待。
    related = list((await db.execute(select(Work).where(Work.asset_id == asset_id)
        .order_by(Work.id).with_for_update())).scalars().all())
    series_ids = select(SeriesEpisode.series_id).where(SeriesEpisode.asset_id == asset_id).distinct()
    related_series = list((await db.execute(select(Series).where(Series.id.in_(series_ids))
        .order_by(Series.id).with_for_update())).scalars().all())
    related_episodes = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.asset_id == asset_id)
        .order_by(SeriesEpisode.id).with_for_update())).scalars().all())
    await asset_owned(db, asset_id, user)
    for document_id in [*body.evidence_ids, *([body.certificate_asset_id] if body.certificate_asset_id else [])]:
        await asset_owned(db, document_id, user, ("document", "image"))
    if body.valid_until and body.valid_until <= now():
        fail("授权截止时间必须晚于当前时间")
    authorization = None
    if body.details.source == "printfilm":
        from .authorization import current
        authorization = await current(db, user.id)
        if not authorization:
            fail("请先签署 PRINTFILM 授权函")
    item = await rights_for(db, asset_id, lock=True)
    if item:
        check_version(item, body.version)
        item.version += 1
    else:
        if body.version != 0:
            fail("权属档案版本无效", 409)
        item = Rights(asset_id=asset_id, owner_id=user.id, version=1)
        db.add(item)
    item.details = body.details.model_dump()
    if body.details.source == "printfilm":
        from .authorization import current
        authorization = await current(db, user.id)
        if authorization:
            item.details = {**item.details, "authorization_id": str(authorization.id),
                            "authorization_version": authorization.template_version,
                            "authorization_signer": authorization.signer_name}
        if not authorization:
            fail("请先签署 PRINTFILM 授权函")
    item.certificate_asset_id, item.evidence_ids, item.valid_until = body.certificate_asset_id, body.evidence_ids, body.valid_until
    item.basic_status, item.full_status = "draft", "draft"
    for work in related:
        await _ensure_work_idle(db, work.id)
        work.audit_status, work.listed = "draft", False
        work.version += 1
        await cancel_work_previews(db, work)
        await _pause_work_sales(db, work.id)
    if related_episodes:
        from .series import ensure_series_idle, pause_series_sales
        for episode in related_episodes:
            episode.version += 1
            episode.audit_status, episode.listed = "draft", False
            episode.preview_status, episode.preview_key, episode.preview_attempts = "none", None, 0
            from .previews import cancel_episode_previews
            await cancel_episode_previews(db, episode)
        for series in related_series:
            await ensure_series_idle(db, series.id)
            series.version += 1
            series.audit_status, series.listed = "draft", False
            await pause_series_sales(db, series)
    await db.flush()
    event(db, user.id, "rights", item.id, "updated", version=item.version)
    await db.commit()
    return {"id": item.id, "version": item.version}


@router.post(
    "/rights/{rights_id}/submit", response_model=dict,
    summary='提交独立权属档案审核',
    description='仅档案所有者可操作，须提交当前 version。校验材料后统一进入待核验状态；full 参数用于兼容旧客户端并决定材料完整性检查。关联单视频作品的档案须通过作品统一审核入口提交。',
    response_description='操作成功时返回 ok=true。',
)
async def submit_rights(rights_id: int, body: Version, db: DB, user: Actor, full: bool = False):
    """用户只提交一次版权审核；保留 full 参数兼容旧客户端。"""
    item = await owned(db, Rights, rights_id, user)
    if (await db.execute(select(Work.id).where(Work.asset_id == item.asset_id).limit(1))).scalar_one_or_none():
        fail("请提交作品审核，版权信息将一并提交", 409)
    check_version(item, body.version)
    if item.blocked:
        fail("权属档案处于争议或封禁中")
    validate_rights(item.details, full=full, certificate=bool(item.certificate_asset_id))
    if not item.evidence_ids and item.details.get("source") not in ("printfilm", "external"):
        fail("请上传创作或授权证明材料")
    if item.details.get("source") == "external" and not item.evidence_ids and not item.certificate_asset_id:
        fail("请上传基础权属证明；没有证明可先联系客服协办")
    item.basic_status = item.full_status = "pending"
    event(db, user.id, "rights", item.id, "submitted", version=item.version)
    await db.commit()
    return {"ok": True}


@router.put(
    "/rights/{rights_id}/case", response_model=dict,
    summary='保存版权登记案件',
    description='仅权属档案所有者可操作。首次创建案件 version 为 0，修改须匹配案件当前版本；保存后案件进入待补材料状态，登记进度不会自动改变权属审核结果。',
    response_description='案件 ID、版本、办理方式、状态和参考编号。',
)
async def save_case(rights_id: int, body: CaseInput, db: DB, user: Actor):
    """申请回执和案件办结从不修改权属核验结论。"""
    await owned(db, Rights, rights_id, user)
    item = (await db.execute(select(RegistrationCase).where(RegistrationCase.rights_id == rights_id).with_for_update())).scalar_one_or_none()
    if item:
        check_version(item, body.version)
        item.version += 1
        item.status = "pending_materials"
    else:
        if body.version != 0:
            fail("案件版本无效", 409)
        item = RegistrationCase(rights_id=rights_id, owner_id=user.id)
        db.add(item)
    item.route, item.official_reference, item.note = body.route, body.official_reference, body.note
    await db.commit()
    return data(item, "id", "rights_id", "version", "route", "status", "official_reference", "note")


@router.post(
    "/assets/{asset_id}/assistance", response_model=dict,
    summary='申请版权材料客服协办',
    description='仅视频资产所有者可操作。可在尚无证明材料时建立外部来源权属档案及客服协办案件；已有协办案件直接复用。PRINTFILM 来源须先走授权函流程。',
    response_description='当前客服协办案件信息。',
)
async def start_assistance(asset_id: int, db: DB, user: Actor):
    """无证明即可建协办案；不生成虚假权属信息或审核结论。"""
    await asset_owned(db, asset_id, user)
    rights = await rights_for(db, asset_id, lock=True)
    if rights and rights.details.get("source") == "printfilm":
        fail("PRINTFILM 作品请先签署授权函；更正来源请保存权属档案")
    if not rights:
        rights = Rights(asset_id=asset_id, owner_id=user.id, details={"source": "external"})
        db.add(rights)
        await db.flush()
    item = (await db.execute(select(RegistrationCase).where(RegistrationCase.rights_id == rights.id).with_for_update())).scalar_one_or_none()
    if item and item.route != "assisted":
        fail("已有其他办理方式，请在案件表单中改为客服协办", 409)
    if not item:
        item = RegistrationCase(rights_id=rights.id, owner_id=user.id, route="assisted")
        db.add(item)
        await db.flush()
        event(db, user.id, "case", item.id, "created_assistance")
        notify(db, user.id, f"权属协办案件 #{item.id} 已建立，请联系客服补充材料")
    await db.commit()
    return data(item, "id", "rights_id", "version", "route", "status", "official_reference", "note")


@router.get(
    "/rights/{rights_id}/case", response_model=dict,
    summary='获取权属档案对应的登记案件',
    description='仅权属档案所有者可查看。按档案读取当前登记案件，尚未创建案件时返回 item=null。',
    response_description='item 为案件详情或 null。',
)
async def get_case(rights_id: int, db: DB, user: Actor):
    """按当前档案读取案件，避免个人案件分页截断导致重复创建。"""
    await owned(db, Rights, rights_id, user)
    item = (await db.execute(select(RegistrationCase).where(RegistrationCase.rights_id == rights_id))).scalar_one_or_none()
    return {"item": data(item, "id", "rights_id", "version", "route", "status", "official_reference", "note") if item else None}


@router.get(
    "/recruits", response_model=dict,
    summary='分页查询公开招募需求',
    description='仅展示审核通过且仍开放的需求。支持标题、分类和预算范围筛选，预算单位为人民币分；sort 支持 latest 和 deadline。',
    response_description='招募需求 items 与分页信息 meta。',
)
async def recruits(db: DB, q: str = Query("", max_length=100), category: str = Query("", max_length=60), category_code: str = Query("", max_length=80),
                   min_budget: int | None = Query(None, ge=0), max_budget: int | None = Query(None, ge=0),
                   sort: str = "latest", page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100)):
    """只展示审核通过且仍开放的需求。"""
    query = select(Recruit).where(*public_recruit_filters())
    if q:
        query = query.where(Recruit.title.ilike(f"%{q}%"))
    if category or category_code:
        query = query.where(await category_filter(db, Recruit, category, category_code))
    if min_budget is not None:
        query = query.where(Recruit.budget_fen >= min_budget)
    if max_budget is not None:
        query = query.where(Recruit.budget_fen <= max_budget)
    if sort not in ("latest", "deadline"):
        fail("排序参数无效")
    records, meta = await page(db, query.order_by(Recruit.deadline_at if sort == "deadline" else Recruit.id.desc(), Recruit.id.desc()), page_number, page_size)
    return {"items": [await recruit_data(db, item) for item in records], "meta": meta}


@router.get(
    "/recruits/{post_id}", response_model=dict,
    summary='获取招募需求详情',
    description='访客可读取公开需求；需求发布者、管理员及历史投稿人可按权限读取相关非公开需求。返回是否为发布者、是否开放及可联系状态；当前投稿入口已停用。',
    response_description='需求详情与 is_owner、is_open、can_submit、can_contact 状态。',
)
async def recruit_detail(post_id: int, db: DB, user: Visitor):
    """相关投稿人可看已关闭需求，但不能借此看他人的投稿。"""
    item = await db.get(Recruit, post_id)
    private = bool(item and user and (user.id == item.owner_id or user.role == "admin"))
    related = bool(user and (await db.execute(select(Submission.id).where(Submission.recruit_id == post_id, Submission.owner_id == user.id).limit(1))).scalar_one_or_none())
    if not item or (not private and not related and not recruit_open(item)):
        fail("需求不存在或未公开", 404)
    result = await recruit_data(db, item, private)
    result.update(is_owner=bool(user and user.id == item.owner_id), is_open=recruit_open(item),
                  can_submit=False,
                  can_contact=bool(user and user.id != item.owner_id and recruit_open(item)))
    return result


@router.post(
    "/recruits", response_model=dict,
    summary='创建招募需求草稿',
    description='登录后创建自己的招募需求。截止时间须晚于当前时间；参考图片须属于本人且已就绪，纯文字需求无需上传图片。',
    response_description='新建招募需求的草稿详情。',
)
async def create_recruit(body: RecruitInput, db: DB, user: Actor):
    """没有参考图的文字需求不依赖 OSS。"""
    await normalize_category_input(db, body)
    if body.deadline_at <= now():
        fail("截止时间必须晚于当前时间")
    for image in body.image_ids:
        await asset_owned(db, image, user, ("image",))
    item = Recruit(owner_id=user.id, **body.model_dump())
    db.add(item)
    await db.commit()
    return await recruit_data(db, item, True)


@router.put(
    "/recruits/{post_id}", response_model=dict,
    summary='更新招募需求草稿',
    description='仅需求发布者可操作，须提交当前 version。已关闭或过期的需求不可编辑；有历史投稿后预算、用途、交付和截止时间等实质条款锁定。保存后回到草稿并重新审核。',
    response_description='更新后的招募需求详情与版本。',
)
async def update_recruit(post_id: int, body: RecruitUpdate, db: DB, user: Actor):
    """曾有投稿后锁定实质条款；其他修改撤下并重新审核。"""
    item = await owned(db, Recruit, post_id, user)
    check_version(item, body.version)
    await normalize_category_input(db, body, item)
    if item.state in ("closed", "expired"):
        fail("需求已结束，请重新发布")
    if body.deadline_at <= now():
        fail("截止时间必须晚于当前时间")
    exists = (await db.execute(select(Submission.id).where(Submission.recruit_id == post_id).limit(1))).scalar_one_or_none()
    locked = ("budget_fen", "wanted_count", "license_scope", "requirements", "deadline_at", "description")
    if exists and any(getattr(item, field) != getattr(body, field) for field in locked):
        fail("已有投稿，预算、用途、授权、交付及截止条件已锁定，请关闭后重新发布")
    for image in body.image_ids:
        await asset_owned(db, image, user, ("image",))
    for key, value in body.model_dump(exclude={"version"}).items():
        setattr(item, key, value)
    item.version += 1
    item.audit_status, item.state = "draft", "draft"
    await db.commit()
    return await recruit_data(db, item, True)


@router.post(
    "/recruits/{post_id}/submit", response_model=dict,
    summary='提交招募需求审核',
    description='仅需求发布者可操作，须提交当前 version；需求须未关闭、未过期且未封禁。提交后进入待审核状态。',
    response_description='操作成功时返回 ok=true。',
)
async def submit_recruit(post_id: int, body: Version, db: DB, user: Actor):
    """需求审核独立于原项目发布流程。"""
    item = await owned(db, Recruit, post_id, user)
    check_version(item, body.version)
    from .categories import resolve_category
    await resolve_category(db, item.category, item.category_code, item.category, item.category_code)
    if item.blocked or item.state in ("closed", "expired") or item.deadline_at <= now():
        fail("需求已结束或被封禁")
    item.audit_status = "pending"
    event(db, user.id, "recruit", item.id, "submitted", version=item.version)
    await db.commit()
    return {"ok": True}


@router.post(
    "/recruits/{post_id}/close", response_model=dict,
    summary='关闭招募需求',
    description='仅需求发布者可操作。关闭后退出公开需求列表并停止新的接单咨询，保留历史记录并递增版本。',
    response_description='操作成功时返回 ok=true。',
)
async def close_recruit(post_id: int, db: DB, user: Actor):
    """关闭后退出广场并停止创作者的新接单咨询，历史记录保留。"""
    item = await owned(db, Recruit, post_id, user)
    item.state = "closed"
    item.version += 1
    event(db, user.id, "recruit", item.id, "closed", version=item.version)
    await db.commit()
    return {"ok": True}


@router.post(
    "/recruits/{post_id}/submissions", response_model=dict, include_in_schema=False,
    summary='旧版投稿入口（已停用）',
    description='兼容旧客户端，固定返回 410，提示改为客服撮合；此接口不在公开 OpenAPI 文档中展示。',
    response_description='固定返回已停用错误 MARKETPLACE_SUBMISSIONS_DISABLED。',
)
async def create_submission(post_id: int, user: Actor):
    """兼容旧客户端并明确拒绝投稿；不创建媒体任务或修改资产。"""
    raise HTTPException(410, detail={"code": "MARKETPLACE_SUBMISSIONS_DISABLED",
                                     "message": "招募已改为客服撮合，请在招募详情中联系客服接单"})


@router.get(
    "/recruits/{post_id}/submissions", response_model=dict,
    summary='分页查看需求收到的历史投稿',
    description='仅需求发布者或管理员可查看对应需求的历史投稿，按投稿 ID 倒序分页。',
    response_description='历史投稿 items 与分页信息 meta。',
)
async def received_submissions(post_id: int, db: DB, user: Actor, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100)):
    """收到的投稿只有需求方和管理员可列出。"""
    await owned(db, Recruit, post_id, user, admin=True)
    records, meta = await page(db, select(Submission).where(Submission.recruit_id == post_id).order_by(Submission.id.desc()), page_number, page_size)
    return {"items": [await submission_data(db, item, user) for item in records], "meta": meta}


@router.post(
    "/submissions/{submission_id}/withdraw", response_model=dict,
    summary='撤回自己的历史投稿',
    description='仅投稿者可操作。标记投稿已撤回并停止为新访问签发链接，保留历史记录。',
    response_description='操作成功时返回 ok=true。',
)
async def withdraw(submission_id: int, db: DB, user: Actor):
    """撤回即停止新签名，历史留痕不删除。"""
    item = await owned(db, Submission, submission_id, user)
    item.withdrawn = True
    event(db, user.id, "submission", item.id, "withdrawn")
    await db.commit()
    return {"ok": True}


@router.post(
    "/submissions/{submission_id}/selection", response_model=dict, include_in_schema=False,
    summary='旧版选稿入口（已停用）',
    description='兼容旧客户端，固定返回 410，提示联系客服确认合作；此接口不在公开 OpenAPI 文档中展示。',
    response_description='固定返回已停用错误 MARKETPLACE_SUBMISSIONS_DISABLED。',
)
async def select_submission(submission_id: int, user: Actor):
    """停止线上选稿；历史标记只读保留。"""
    raise HTTPException(410, detail={"code": "MARKETPLACE_SUBMISSIONS_DISABLED",
                                     "message": "招募已改为客服撮合，请联系客服确认合作"})
