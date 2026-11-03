"""下游运营 API；审核只操作独立记录，并强制版本匹配。"""
from fastapi import APIRouter, Query
from sqlalchemy import and_, func, select

from .dependencies import Admin, DB
from .models import Asset, EpisodePreview, Entitlement, Event, MediaJob, Publication, Recruit, RegistrationCase, Report, RevenueConfig, RevenueLedger, Payout, Rights, Series, SeriesEpisode, Submission, Support, Work, WorkPreview
from .schemas import BlockInput, CaseReview, CategoryInput, PayoutInput, ResolutionInput, ReviewInput, RevenueConfigInput, SupportInput, Version
from .service import (asset_owned, check_version, data, event, fail, now, notify, page, recruit_data,
                      rights_for, rights_valid, submission_data, validate_rights, work_data)

router = APIRouter()


def _notification_note(message: str, note: str) -> str:
    """省略空说明，避免向用户展示内部枚举或空分隔符。"""
    from .notification_locale import note_notice
    return note_notice(message, note)


def _review_notification(kind: str, title: str, decision: str, reason: str, approved_next: str) -> str:
    from .notification_locale import review_notice
    return review_notice(kind, title, decision, reason, approved_next)


@router.get(
    "/categories", response_model=dict,
    summary='获取市场分类管理配置',
    description='仅管理员可访问。读取可用分类名称及当前配置版本，供编辑前确认。',
    response_description='分类名称 names 与配置版本 version。',
)
async def get_categories(db: DB, user: Admin):
    from .categories import category_config
    return await category_config(db, include_disabled=True)


@router.put(
    "/categories", response_model=dict,
    summary='更新市场分类配置',
    description='仅管理员可操作。提交完整分类列表及读取到的 version，首次保存版本为 0；并发修改导致版本不匹配时返回 409。',
    response_description='保存后的分类名称列表与新版本。',
)
async def save_categories(body: CategoryInput, db: DB, user: Admin):
    from sqlalchemy import text
    from .models import CategoryConfig
    # 首次保存也串行化，避免两个管理员同时创建配置。
    await db.execute(text("SELECT pg_advisory_xact_lock(18427, 73103)"))
    item = await db.get(CategoryConfig, 1, with_for_update=True)
    if body.version != (item.version if item else 0):
        fail("分类配置已被修改，请重新加载后保存", 409)
    from .categories import category_config, entries, merge_config
    previous = entries(item)
    if item is None:
        item = CategoryConfig(id=1, version=0, names=[])
        db.add(item)
    item.items = merge_config(previous,
                              [entry.model_dump() for entry in body.items] if body.items is not None else None, body.names)
    item.names = [entry["name_zh"] for entry in item.items if entry["enabled"]]
    item.version += 1
    event(db, user.id, "categories", 1, "updated", version=item.version)
    await db.commit()
    return await category_config(db, include_disabled=True)


MODELS = {"works": Work, "rights": Rights, "cases": RegistrationCase, "recruits": Recruit,
          "submissions": Submission, "reports": Report, "jobs": MediaJob, "events": Event, "previews": WorkPreview,
          "series": Series, "episodes": SeriesEpisode, "orders": __import__("app.marketplace.models", fromlist=["ContentOrder"]).ContentOrder,
          "ledger": RevenueLedger, "payouts": Payout, "entitlements": Entitlement}


@router.get(
    "/overview", response_model=dict,
    summary='获取市场运营概览',
    description='仅管理员可访问。汇总待审作品、权属与需求、失败媒体任务、待处理举报、存储字节数及咨询次数；咨询计数不代表成交。',
    response_description='各项运营计数与 storage_bytes 存储用量。',
)
async def overview(db: DB, user: Admin):
    """运营计数不把咨询、候选或扫码计为成交。"""
    counts = {}
    for name, model, condition in (("works_pending", Work, and_(Work.audit_status == "pending", Work.deleted_at.is_(None))),
                                    ("rights_pending", Rights, (Rights.basic_status == "pending") | (Rights.full_status == "pending")),
                                    ("recruits_pending", Recruit, Recruit.audit_status == "pending"),
                                    ("jobs_failed", MediaJob, MediaJob.status == "failed"),
                                    ("reports_pending", Report, Report.status == "pending")):
        counts[name] = (await db.execute(select(func.count()).select_from(model).where(condition))).scalar_one()
    counts["storage_bytes"] = (await db.execute(select(func.coalesce(func.sum(Asset.size_bytes), 0)))).scalar_one()
    counts["consultations"] = (await db.execute(select(func.count()).select_from(Event).where(Event.action == "consultation"))).scalar_one()
    return counts


@router.get(
    "/records/{kind}", response_model=dict,
    summary='分页查询市场运营记录',
    description='仅管理员可访问。kind 支持 works、rights、cases、recruits、submissions、reports、jobs、events、previews、series、episodes、orders、ledger、payouts、entitlements。支持按适用的状态筛选；权益记录还可按 user_id、owner_id 筛选。',
    response_description='运营记录 items 与分页信息 meta。',
)
async def records(kind: str, db: DB, user: Admin, status: str = "", user_id: int | None = Query(None, ge=1), owner_id: int | None = Query(None, ge=1), page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100)):
    """管理员分页工作台；敏感材料在单独鉴权接口读取。"""
    model = MODELS.get(kind)
    if not model:
        fail("记录类型无效", 404)
    query = select(model)
    if kind in ("works", "series"):
        query = query.where(model.deleted_at.is_(None))
    field = getattr(model, "audit_status", None) if kind in ("works", "recruits", "series") else getattr(model, "status", None)
    if status and field is not None:
        query = query.where(field == status)
    if kind == "rights" and status:
        query = query.where((Rights.basic_status == status) | (Rights.full_status == status))
    if kind == "rights":
        # 作品版权随作品统一审核，这里只保留独立投稿的审核记录。
        query = query.where(~select(Work.id).where(Work.asset_id == Rights.asset_id).exists())
    if kind == "entitlements":
        if user_id is not None:
            query = query.where(Entitlement.user_id == user_id)
        if status in ("active", "inactive"):
            query = query.where(Entitlement.active.is_(status == "active"))
        if owner_id is not None:
            query = query.join(Publication, Publication.id == Entitlement.publication_id).where(Publication.owner_id == owner_id)
    rows, meta = await page(db, query.order_by(model.id.desc()), page_number, page_size)
    items = []
    for item in rows:
        if kind == "works":
            result = await work_data(db, item, True)
            rights = await rights_for(db, item.asset_id)
            if rights:
                result.update(details=rights.details, certificate_asset_id=rights.certificate_asset_id,
                              evidence_ids=rights.evidence_ids)
        elif kind == "recruits":
            result = await recruit_data(db, item, True)
            images = result.get("image_ids") or []
            if images:
                result["cover_asset_id"] = int(images[0])
        elif kind == "series":
            result = data(item, *[column.name for column in model.__table__.columns])
            episodes = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == item.id).order_by(SeriesEpisode.episode_no))).scalars().all())
            from app.models import User
            owner = await db.get(User, item.owner_id)
            result["author"] = owner.nickname if owner and owner.nickname else "创作者"
            result["episode_count"] = len(episodes)
            result["episodes"] = []
            for episode in episodes:
                rights = (await db.execute(select(Rights).where(Rights.asset_id == episode.asset_id))).scalar_one_or_none() if episode.asset_id else None
                result["episodes"].append({**data(episode, "id", "episode_no", "title", "description", "asset_id", "cover_asset_id", "source", "source_type", "version", "audit_status", "listed", "preview_status", "playback_status"), **({"details": rights.details, "certificate_asset_id": rights.certificate_asset_id, "evidence_ids": rights.evidence_ids} if rights else {})})
        elif kind == "submissions":
            result = await submission_data(db, item, user)
        elif kind == "entitlements":
            publication = await db.get(Publication, item.publication_id)
            result = data(item, "id", "user_id", "publication_id", "episode_id", "order_id", "active", "created_at")
            if publication:
                result.update(content_type=publication.content_type, content_id=publication.content_id,
                              publication_version=publication.version, publication_owner_id=publication.owner_id,
                              sale_type=publication.sale_type, unlock_price_fen=publication.unlock_price_fen)
        else:
            fields = [column.name for column in model.__table__.columns]
            result = data(item, *fields)
        items.append(result)
    if kind in ("rights", "cases", "reports", "entitlements"):
        event(db, user.id, kind, 0, "admin_list_read")
        await db.commit()
    return {"items": items, "meta": meta}


@router.post(
    "/works/{work_id}/review", response_model=dict,
    summary='审核单视频作品与版权',
    description='仅管理员可操作，须匹配当前 version 且作品处于 pending。通过时须确认 content 和 copyright 检查项，并验证媒体、试看、授权与证明材料；审核通过后仍保持下架，由作者主动上架。',
    response_description='操作成功时返回 ok=true。',
)
async def review_work(work_id: int, body: ReviewInput, db: DB, user: Admin):
    """一次审核同时检查作品内容和版权信息。"""
    item = await db.get(Work, work_id, with_for_update=True)
    if not item:
        fail("作品不存在", 404)
    check_version(item, body.version)
    if item.audit_status != "pending":
        fail("该版本不在待审核状态", 409)
    rights = await rights_for(db, item.asset_id, lock=True)
    asset = await db.get(Asset, item.asset_id)
    if body.decision == "approved":
        from .previews import preview_ready
        if item.sale_type != "free" and not await preview_ready(db, item):
            fail("短试看尚未就绪，不能通过审核", 409)
        if item.blocked or not asset or asset.status != "ready" or not rights or rights.blocked:
            fail("版权、媒体或封禁状态不允许通过")
        if rights.details.get("source") != item.source or (rights.valid_until and rights.valid_until <= now()):
            fail("版权来源不匹配或已过期")
        if item.source == "printfilm":
            from .authorization import current
            authorization = await current(db, item.owner_id)
            if not authorization or str(authorization.id) != rights.details.get("authorization_id"):
                fail("授权函不存在或已更新，请重新提交")
        if not {"content", "copyright"}.issubset(body.checks):
            fail("请确认作品内容与版权信息均已检查")
        validate_rights(rights.details, full=True, certificate=bool(rights.certificate_asset_id))
        if rights.certificate_asset_id:
            proof = await db.get(Asset, rights.certificate_asset_id)
            if not proof or proof.owner_id != item.owner_id or proof.status != "ready":
                fail("版权证明不存在或未就绪")
        rights.basic_status = rights.full_status = "approved"
        publication = (await db.execute(select(Publication).where(Publication.content_type == "work", Publication.content_id == item.id, Publication.version == item.version).with_for_update())).scalar_one_or_none()
        if publication:
            publication.audit_status = "approved"
            publication.listed = False
    item.audit_status, item.reason, item.listed = body.decision, body.reason, False
    if body.decision == "rejected" and rights:
        rights.basic_status = rights.full_status = "rejected"
    event(db, user.id, "work", item.id, f"review_{body.decision}", body.reason, item.version)
    notify(db, item.owner_id, _review_notification("作品", item.title, body.decision, body.reason,
                                                  "可前往作品管理页查看播放准备状态并上架"))
    await db.commit()
    return {"ok": True}


@router.get(
    "/revenue-config", response_model=dict,
    summary='获取平台分成配置',
    description='仅管理员可访问。读取平台分成比例、启用状态与版本；尚未设置时返回 version=0、enabled=false。',
    response_description='当前分成配置；platform_share_bps 使用基点，10000 表示 100%。',
)
async def get_revenue_config(db: DB, user: Admin):
    item = await db.get(RevenueConfig, 1)
    return data(item, "id", "version", "platform_share_bps", "enabled") if item else {"version": 0, "enabled": False}


@router.put(
    "/revenue-config", response_model=dict,
    summary='保存平台分成配置',
    description='仅管理员可操作。提交当前 version，首次保存为 0；版本不匹配返回 409。platform_share_bps 使用基点，10000 表示 100%。',
    response_description='保存后的平台分成比例、启用状态与配置版本。',
)
async def save_revenue_config(body: RevenueConfigInput, db: DB, user: Admin):
    item = await db.get(RevenueConfig, 1, with_for_update=True)
    current = item.version if item else 0
    if body.version != current:
        fail("分成配置已被修改，请刷新后重试", 409)
    if not item:
        item = RevenueConfig(id=1, version=0, platform_share_bps=body.platform_share_bps, enabled=body.enabled)
        db.add(item)
    else:
        item.platform_share_bps, item.enabled, item.version = body.platform_share_bps, body.enabled, item.version + 1
    event(db, user.id, "revenue_config", 1, "updated", version=item.version)
    await db.commit()
    return data(item, "id", "version", "platform_share_bps", "enabled")


@router.post(
    "/payouts", response_model=dict,
    summary='登记创作者人工打款',
    description='仅管理员可操作。记录收款作者、金额、状态和备注；金额单位为人民币分。仅登记人工打款记录，不触发自动转账。',
    response_description='新建打款记录及完成时间、操作人信息。',
)
async def create_payout(body: PayoutInput, db: DB, user: Admin):
    """记录人工打款；不触发任何自动转账。"""
    item = Payout(owner_id=body.owner_id, amount_fen=body.amount_fen, status=body.status,
                  note=body.note, paid_at=now() if body.status == "paid" else None,
                  operator_id=user.id if body.status == "paid" else None)
    db.add(item)
    await db.flush()
    event(db, user.id, "payout", item.id, "created", body.note)
    await db.commit()
    return data(item, "id", "owner_id", "amount_fen", "status", "note", "paid_at", "operator_id", "created_at")


@router.patch(
    "/payouts/{payout_id}", response_model=dict,
    summary='更新创作者打款记录',
    description='仅管理员可操作。更新收款作者、金额、状态和备注；金额单位为人民币分。已完成打款不可回退为其他状态，冲突时返回 409。',
    response_description='更新后的打款记录。',
)
async def update_payout(payout_id: int, body: PayoutInput, db: DB, user: Admin):
    item = await db.get(Payout, payout_id, with_for_update=True)
    if not item:
        fail("打款记录不存在", 404)
    if item.status == "paid" and body.status != "paid":
        fail("已完成的打款记录不可回退", 409)
    item.owner_id, item.amount_fen, item.note, item.status = body.owner_id, body.amount_fen, body.note, body.status
    if body.status == "paid":
        item.paid_at, item.operator_id = now(), user.id
    event(db, user.id, "payout", item.id, "updated", body.note)
    await db.commit()
    return data(item, "id", "owner_id", "amount_fen", "status", "note", "paid_at", "operator_id", "created_at")


@router.post(
    "/series/{series_id}/review", response_model=dict,
    summary='审核短剧系列与各集版权',
    description='仅管理员可操作，须匹配系列当前 version 且处于 pending。通过时须确认 content、copyright，检查分集连续性、媒体、封面、版权和必要试看；结果同步到各集与发布版本，通过后由作者另行上架。',
    response_description='操作成功时返回 ok=true。',
)
async def review_series(series_id: int, body: ReviewInput, db: DB, user: Admin):
    series = await db.get(Series, series_id, with_for_update=True)
    if not series:
        fail("系列不存在", 404)
    check_version(series, body.version)
    if series.audit_status != "pending":
        fail("该系列不在待审核状态", 409)
    episodes = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == series.id).order_by(SeriesEpisode.episode_no).with_for_update())).scalars().all())
    if body.decision == "approved":
        # Series review is the single content + rights decision for all
        # episodes.  Require the same explicit confirmations as a single work;
        # the separate legacy rights review endpoint is not used for new series.
        if not {"content", "copyright"}.issubset(body.checks):
            fail("请确认系列内容与各集版权信息均已检查")
        if not episodes or [item.episode_no for item in episodes] != list(range(1, len(episodes) + 1)):
            fail("系列分集必须从1开始连续排列")
        from .previews import episode_is_free, episode_preview_ready, series_submission_ready
        if not await series_submission_ready(db, series):
            fail("系列媒体、版权材料或授权未就绪，请重新检查", 409)
        config = await db.get(RevenueConfig, 1)
        if series.sale_type == "platform_unlock" and (not config or not config.enabled):
            fail("MARKETPLACE_REVENUE_CONFIG_REQUIRED", 409)
        for episode in episodes:
            asset = await db.get(Asset, episode.asset_id) if episode.asset_id else None
            rights = (await db.execute(select(Rights).where(Rights.asset_id == episode.asset_id))).scalar_one_or_none() if episode.asset_id else None
            if not asset or asset.status != "ready" or not rights or rights.blocked:
                fail(f"第{episode.episode_no}集媒体或权属未就绪")
            if not episode.cover_asset_id and not series.cover_asset_id:
                fail(f"第{episode.episode_no}集缺少封面")
            if rights.details.get("source") != episode.source:
                fail(f"第{episode.episode_no}集版权来源与分集来源不匹配")
            validate_rights(rights.details, full=True, certificate=bool(rights.certificate_asset_id))
            if episode.source == "printfilm":
                from .authorization import current
                authorization = await current(db, series.owner_id)
                if not authorization or str(authorization.id) != rights.details.get("authorization_id"):
                    fail(f"第{episode.episode_no}集 PrintFilm 授权函不存在或已更新")
            elif episode.source == "external":
                if not rights.certificate_asset_id or not rights.details.get("certificate_number") or not rights.details.get("dispute_ack"):
                    fail(f"第{episode.episode_no}集缺少版权证书编号、证明材料或纠纷声明")
            if not await episode_preview_ready(db, series, episode):
                fail(f"第{episode.episode_no}集短试看尚未就绪", 409)
            if series.sale_type == "platform_unlock" and not episode_is_free(series, episode) and episode.unlock_price_fen <= 0:
                fail(f"第{episode.episode_no}集必须设置解锁价")
            publication = (await db.execute(select(Publication).where(Publication.content_type == "series_episode", Publication.content_id == episode.id, Publication.version == episode.version).with_for_update())).scalar_one_or_none()
            if not publication:
                fail(f"第{episode.episode_no}集缺少发布版本，请让作者重新提交", 409)
            publication.audit_status, publication.listed = "approved", False
            rights.basic_status = rights.full_status = "approved"
            episode.audit_status = "approved"
            episode.listed = False
        series.audit_status, series.reason, series.listed = "approved", body.reason, False
    else:
        series.audit_status, series.reason = "rejected", body.reason
        for episode in episodes:
            episode.audit_status = "rejected"
            rights = (await db.execute(select(Rights).where(Rights.asset_id == episode.asset_id))).scalar_one_or_none() if episode.asset_id else None
            if rights:
                rights.basic_status = rights.full_status = "rejected"
    event(db, user.id, "series", series.id, f"review_{body.decision}", body.reason, series.version)
    notify(db, series.owner_id, _review_notification("短剧", series.title, body.decision, body.reason,
                                                    "可前往短剧编辑页查看各集播放准备状态并上架"))
    await db.commit()
    return {"ok": True}


@router.post(
    "/rights/{rights_id}/review", response_model=dict,
    summary='审核独立权属档案',
    description='仅管理员可操作，须匹配当前 version 且档案待核验。full 控制完整材料与逐项确认检查；通过或拒绝结果同步至档案基础、完整核验状态。关联单视频作品须通过作品统一审核处理。',
    response_description='操作成功时返回 ok=true。',
)
async def review_rights(rights_id: int, body: ReviewInput, db: DB, user: Admin, full: bool = False):
    """必须逐项确认核验结果；证书上传与登记案件办结不能自动放行。"""
    item = await db.get(Rights, rights_id, with_for_update=True)
    if not item:
        fail("权属档案不存在", 404)
    if (await db.execute(select(Work.id).where(Work.asset_id == item.asset_id).limit(1))).scalar_one_or_none():
        fail("请在作品统一审核中处理该作品", 409)
    check_version(item, body.version)
    if item.basic_status != "pending" and item.full_status != "pending":
        fail("该版本不在待核验状态", 409)
    if body.decision == "approved":
        if item.blocked or (item.valid_until and item.valid_until <= now()):
            fail("权属已封禁或授权到期")
        validate_rights(item.details, full=full, certificate=bool(item.certificate_asset_id))
        source = item.details.get("source")
        if not item.evidence_ids and source not in ("printfilm", "external"):
            fail("缺少基础证明材料")
        if source == "external" and not item.evidence_ids and not item.certificate_asset_id:
            fail("缺少基础权属证明材料")
        if source == "printfilm":
            from .authorization import current
            authorization = await current(db, item.owner_id)
            if not authorization or str(authorization.id) != item.details.get("authorization_id"):
                fail("授权函不存在或版本已更新，请重新关联并提交")
        checks = {"identity", "ownership", "third_party", "scope"}
        if full:
            checks.update({"authorization" if source == "printfilm" else "ownership_proof" if source == "external" else "certificate", "sample_match", "sales_authority"})
        if source in ("ai", "printfilm", "external"):
            checks.add("ai_evidence")
        if not checks.issubset(body.checks):
            fail("请逐项确认身份、作品匹配、素材、授权范围和证书核验")
        for document_id in [*item.evidence_ids, *([item.certificate_asset_id] if item.certificate_asset_id else [])]:
            document = await db.get(Asset, document_id)
            if not document or document.owner_id != item.owner_id or document.status != "ready":
                fail("核验材料不存在或未处理完成")
    item.basic_status = item.full_status = body.decision
    item.reason = body.reason
    event(db, user.id, "rights", item.id, f"{'full' if full else 'basic'}_{body.decision}", body.reason + "；核验项：" + ",".join(body.checks), item.version)
    result = "版权材料已核验" if body.decision == "approved" else "版权材料未通过核验，请补充材料后重新提交"
    notify(db, item.owner_id, _notification_note(f"视频 #{item.asset_id} {result}。", body.reason))
    await db.commit()
    return {"ok": True}


@router.post(
    "/recruits/{post_id}/review", response_model=dict,
    summary='审核招募需求',
    description='仅管理员可操作，须匹配当前 version 且需求待审。已关闭、过期或被封禁的需求不能通过；审核通过后需求进入 open 状态。',
    response_description='操作成功时返回 ok=true。',
)
async def review_recruit(post_id: int, body: ReviewInput, db: DB, user: Admin):
    """需求公开审核，过期、关闭、封禁不能被过期审核重新开启。"""
    item = await db.get(Recruit, post_id, with_for_update=True)
    if not item:
        fail("需求不存在", 404)
    check_version(item, body.version)
    if item.audit_status != "pending" or item.state in ("closed", "expired"):
        fail("需求不在待审核状态", 409)
    if body.decision == "approved" and (item.blocked or item.deadline_at <= now()):
        fail("需求已到期或被封禁")
    item.audit_status, item.reason = body.decision, body.reason
    item.state = "open" if body.decision == "approved" else "draft"
    event(db, user.id, "recruit", item.id, f"content_{body.decision}", body.reason, item.version)
    notify(db, item.owner_id, _review_notification("招募需求", item.title, body.decision, body.reason,
                                                  "已进入招募广场，创作者将通过客服表达接单意向"))
    await db.commit()
    return {"ok": True}


@router.post(
    "/cases/{case_id}/status", response_model=dict,
    summary='更新版权登记案件进度',
    description='仅管理员可操作，须匹配当前案件 version。标记已取证前须有证书编号和证明材料；保存后递增案件版本并通知申请人，案件办结不自动通过权属审核。',
    response_description='操作成功时返回 ok=true。',
)
async def case_status(case_id: int, body: CaseReview, db: DB, user: Admin):
    """办理进度独立于权属审核；录入已取证仍不解锁销售。"""
    item = await db.get(RegistrationCase, case_id, with_for_update=True)
    if not item:
        fail("案件不存在", 404)
    check_version(item, body.version)
    if body.status == "certificated":
        rights = await db.get(Rights, item.rights_id)
        if not rights.certificate_asset_id or not rights.details.get("certificate_number"):
            fail("请先由用户补充证书号和证书材料")
    item.status, item.note = body.status, body.note
    item.version += 1
    event(db, user.id, "case", item.id, body.status, body.note, item.version)
    case_status_names = {"pending_materials": "待补充材料", "reviewing": "材料核验中", "supplement": "待补正", "rejected": "已驳回",
                         "applying": "办理中", "certificated": "已取得证书", "cancelled": "已取消"}
    notify(db, item.owner_id, _notification_note(f"历史版权登记记录 #{item.id} 已更新为{case_status_names[body.status]}。", body.note))
    await db.commit()
    return {"ok": True}


@router.post(
    "/block/{kind}/{record_id}", response_model=dict,
    summary='设置市场记录封禁状态',
    description='仅管理员可操作。kind 支持 work、rights、recruit、submission，按 blocked 标记限制或解除限制并记录原因；作品被操作时下架且递增版本，解除封禁不会自动上架。',
    response_description='操作成功时返回 ok=true。',
)
async def block(kind: str, record_id: int, body: BlockInput, db: DB, user: Admin):
    """争议处理可暂停播放和咨询；解除封禁不自动重新上架。"""
    model = {"work": Work, "rights": Rights, "recruit": Recruit, "submission": Submission}.get(kind)
    if not model:
        fail("封禁类型无效")
    item = await db.get(model, record_id, with_for_update=True)
    if not item:
        fail("记录不存在", 404)
    item.blocked = body.blocked
    if isinstance(item, Work):
        item.listed = False
        item.version += 1
    if isinstance(item, (Work, Recruit, Rights)):
        item.reason = body.reason
    event(db, user.id, kind, item.id, "blocked" if body.blocked else "unblocked", body.reason)
    kind_name = {"work": "作品", "rights": "版权材料", "recruit": "招募需求", "submission": "历史投稿"}[kind]
    title = f"《{item.title}》" if getattr(item, "title", None) else f" #{item.id}"
    if body.blocked:
        message = f"{kind_name}{title}已被限制，请查看处理说明并联系客服。"
    elif isinstance(item, Work):
        message = f"{kind_name}{title}已解除限制，请前往作品管理页查看审核与上架状态。"
    else:
        message = f"{kind_name}{title}已解除限制，请前往我的发布查看当前状态。"
    notify(db, item.owner_id, _notification_note(message, body.reason))
    await db.commit()
    return {"ok": True}


@router.post(
    "/reports/{report_id}/resolve", response_model=dict,
    summary='登记举报处理结论',
    description='仅管理员可操作。将举报标记为 resolved，保存处理说明并通知举报人；需要限制内容时另行调用封禁接口。',
    response_description='操作成功时返回 ok=true。',
)
async def resolve_report(report_id: int, body: ResolutionInput, db: DB, user: Admin):
    """投诉处理结论留痕，限制内容须使用明确的封禁操作。"""
    item = await db.get(Report, report_id, with_for_update=True)
    if not item:
        fail("举报不存在", 404)
    item.status, item.resolution = "resolved", body.resolution
    event(db, user.id, "report", item.id, "resolved", body.resolution)
    notify(db, item.owner_id, f"举报 #{item.id} 已处理：{body.resolution}")
    await db.commit()
    return {"ok": True}


@router.get(
    "/support", response_model=dict,
    summary='获取市场客服管理配置',
    description='仅管理员可访问。读取客服名称、微信、服务时间、二维码资产 ID 与启用状态；尚未配置时返回 enabled=false。',
    response_description='客服配置，不包含私有存储对象地址。',
)
async def get_support(db: DB, user: Admin):
    """管理配置不返回 OSS 对象位置。"""
    item = await db.get(Support, 1)
    return data(item, "name", "name_en", "wechat", "hours", "hours_en", "qr_asset_id", "enabled") if item else {"enabled": False}


@router.put(
    "/support", response_model=dict,
    summary='保存市场客服配置',
    description='仅管理员可操作。二维码须为本人已就绪的 qr 类型资产；启用客服时必须同时填写微信号与有效二维码。',
    response_description='操作成功时返回 ok=true。',
)
async def save_support(body: SupportInput, db: DB, user: Admin):
    """仅使用已处理完成的真实二维码资产。"""
    if body.qr_asset_id:
        await asset_owned(db, body.qr_asset_id, user, ("qr",))
    if body.enabled and (not body.wechat or not body.qr_asset_id):
        fail("启用客服必须设置微信号及真实二维码")
    item = await db.get(Support, 1, with_for_update=True)
    if not item:
        item = Support(id=1)
        db.add(item)
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    event(db, user.id, "support", 1, "updated")
    await db.commit()
    return {"ok": True}
