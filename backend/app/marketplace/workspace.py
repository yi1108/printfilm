"""个人管理、站内通知、咨询与举报。"""
from fastapi import APIRouter, Query
from sqlalchemy import func, literal, select, union_all

from .dependencies import Actor, DB
from .models import Asset, Notification, Recruit, RegistrationCase, Report, Rights, Series, SeriesEpisode, Submission, Support, Work
from .schemas import ReportInput, Target
from .service import asset_owned, data, event, fail, get_target, is_public_work, notify, owned, page, recruit_data, recruit_open, rights_for, rights_valid, submission_data, submission_rights_match, work_data

router = APIRouter()


async def owner_works(db, user, page_number: int, page_size: int) -> dict:
    """我的作品同时包含单视频和短剧，按创建时间分页。"""
    work_part = select(Work.id.label("item_id"), literal("work").label("kind"), Work.created_at.label("sort_at"), Work.id.label("tie")).where(Work.owner_id == user.id, Work.deleted_at.is_(None))
    series_part = select(Series.id.label("item_id"), literal("series").label("kind"), Series.created_at.label("sort_at"), Series.id.label("tie")).where(Series.owner_id == user.id, Series.deleted_at.is_(None))
    combined = union_all(work_part, series_part).subquery()
    total = (await db.execute(select(func.count()).select_from(combined))).scalar_one()
    rows = (await db.execute(select(combined).order_by(combined.c.sort_at.desc(), combined.c.tie.desc()).offset((page_number - 1) * page_size).limit(page_size))).all()
    items = []
    for row in rows:
        if row.kind == "work":
            payload = await work_data(db, await db.get(Work, row.item_id), True)
            payload["kind"] = "work"
        else:
            from .series import _series_data
            series = await db.get(Series, row.item_id)
            detail = await _series_data(db, series, private=True)
            payload = {"kind": "series", "id": series.id, "title": series.title, "category": series.category, "category_code": detail["category_code"], "category_label": detail["category_label"], "category_labels": detail["category_labels"],
                       "sale_type": series.sale_type, "price_fen": series.copyright_price_fen,
                       "episode_count": detail["episode_count"], "cover_asset_id": series.cover_asset_id,
                       "audit_status": series.audit_status, "listed": series.listed, "blocked": series.blocked,
                       "reason": series.reason, "created_at": series.created_at}
        items.append(payload)
    return {"items": items, "meta": {"page": page_number, "page_size": page_size, "total": total}}


@router.get(
    "/mine/{kind}", response_model=dict,
    summary='分页查询我的市场记录',
    description='仅查询当前登录账号自己的记录。kind 支持 works、series、recruits、submissions、cases、assets、rights、notifications；works 合并单视频与短剧系列，已删除作品不再展示。',
    response_description='个人记录 items 与分页信息 meta。',
)
async def mine(kind: str, db: DB, user: Actor, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100)):
    """个人数据分页，不能通过请求 owner_id 读取别人数据。"""
    if kind == "works":
        return await owner_works(db, user, page_number, page_size)
    model = {"series": Series, "recruits": Recruit, "submissions": Submission, "cases": RegistrationCase,
             "assets": Asset, "rights": Rights, "notifications": Notification}.get(kind)
    if not model:
        fail("列表类型无效", 404)
    query = select(model).where(model.owner_id == user.id)
    if kind == "series":
        query = query.where(Series.deleted_at.is_(None))
    rows, meta = await page(db, query.order_by(model.id.desc()), page_number, page_size)
    items = []
    for item in rows:
        if isinstance(item, Work):
            result = await work_data(db, item, True)
        elif isinstance(item, Series):
            from .series import _series_data
            result = await _series_data(db, item, private=True)
        elif isinstance(item, Recruit):
            result = await recruit_data(db, item, True)
        elif isinstance(item, Submission):
            result = await submission_data(db, item, user)
        elif isinstance(item, Asset):
            result = data(item, "id", "kind", "filename", "status", "fingerprint", "duration_seconds", "error", "created_at")
        else:
            result = data(item, *[column.name for column in model.__table__.columns])
        if isinstance(item, Notification):
            from .notification_locale import render
            result.update(render(item))
        items.append(result)
    return {"items": items, "meta": meta}


@router.post(
    "/notifications/{notification_id}/read", response_model=dict,
    summary='将我的站内通知标记已读',
    description='仅通知接收者可操作，将指定通知的 read 状态设置为 true。',
    response_description='操作成功时返回 ok=true。',
)
async def read_notification(notification_id: int, db: DB, user: Actor):
    """标记当前账号的站内通知。"""
    item = await owned(db, Notification, notification_id, user)
    item.read = True
    await db.commit()
    return {"ok": True}


@router.get(
    "/support", response_model=dict,
    summary='获取公开客服说明',
    description='允许访客访问。返回已启用客服的名称、微信和服务时间；二维码需登录后通过媒体签名接口单独获取。',
    response_description='客服可用状态 available 及说明；不可用时包含 message。',
)
async def support(db: DB):
    """公开客服说明；二维码使用独立短时签名接口。"""
    item = await db.get(Support, 1)
    if not item or not item.enabled or not item.qr_asset_id:
        from .locale import localized
        return {"available": False, "message": localized("客服暂不可用", "Support is currently unavailable.")}
    return {"available": True, **support_fields(item)}


def support_fields(item):
    from .locale import current_locale
    english = current_locale.get() == "en"
    return {"name": (item.name_en or item.name) if english else item.name,
            "hours": (item.hours_en or item.hours) if english else item.hours,
            "wechat": item.wechat, "name_en": item.name_en, "hours_en": item.hours_en,
            "name_zh": item.name, "hours_zh": item.hours}


@router.post(
    "/consultations", response_model=dict,
    summary='发起市场内容客服咨询',
    description='登录后按目标权限记录咨询。作品与分集须满足可咨询条件，需求咨询用于客服撮合；客服不可用时返回 503。咨询只记录沟通意向，不创建成交、授权或购买权益。',
    response_description='咨询参考编号、标题、人民币分价格及客服联系方式与提示。',
)
async def consult(body: Target, db: DB, user: Actor):
    """记录咨询而非成交；购买类咨询必须满足完整权属核验。"""
    item = await get_target(db, body.target_type, body.target_id, user)
    price, title = None, ""
    if isinstance(item, Work):
        if not await is_public_work(db, item.id):
            fail("作品尚未满足购买咨询条件")
        price, title = item.price_fen, item.title
    elif isinstance(item, Submission):
        post = await db.get(Recruit, item.recruit_id)
        rights = await rights_for(db, item.asset_id)
        if user.id != post.owner_id:
            fail("仅需求方可发起投稿购买咨询", 403)
        if item.withdrawn or item.blocked or post.blocked or not rights_valid(rights, full=True) or not submission_rights_match(item, rights):
            fail("投稿尚未完成完整权属核验或已撤回、封禁")
        from .locale import localized
        price, title = item.quote_fen, localized(f"《{post.title}》投稿 #{item.id}", f"Submission #{item.id} for “{post.title}”")
    elif isinstance(item, Recruit):
        if not recruit_open(item) and user.id != item.owner_id:
            fail("需求已结束，不能发起新咨询")
        price, title = item.budget_fen, item.title
    elif isinstance(item, SeriesEpisode):
        series = await db.get(Series, item.series_id)
        if (not series or series.sale_type != "copyright_contact" or not series.listed
                or series.audit_status != "approved" or not item.listed
                or item.audit_status != "approved" or series.blocked or item.blocked):
            fail("该分集尚未开放版权咨询", 409)
        price = item.copyright_price_fen or series.copyright_price_fen
        from .locale import localized
        title = localized(f"《{series.title}》第{item.episode_no}集 · {item.title}", f"“{series.title}” Episode {item.episode_no} · {item.title}")
    else:
        from .locale import localized
        title = localized(f"版权登记案件 #{item.id}", f"Rights registration case #{item.id}")
    settings = await db.get(Support, 1)
    if not settings or not settings.enabled or not settings.qr_asset_id:
        fail("客服暂不可用", 503)
    event(db, user.id, body.target_type, item.id, "consultation")
    await db.commit()
    notice = ("接单请先联系客服，并提供招募编号。由客服协助确认需求、预算、授权和交付要求，具体合作在线下协商确认。咨询不代表已接单或成交。"
              if isinstance(item, Recruit) else "请联系客服确认价格、授权范围和交付方式。咨询不代表成交或授权。")
    from .locale import localized
    english_notice = ("Contact support first and provide the brief ID. Support will help confirm the requirements, budget, license and delivery. Cooperation is agreed offline; an inquiry does not constitute acceptance or a sale."
                      if isinstance(item, Recruit) else "Contact support to confirm the price, license and delivery. An inquiry does not constitute a sale or license. Copyright transfers require a separate transfer process and may incur fees.")
    return {"reference": f"{body.target_type.upper()}-{item.id}", "title": title, "price_fen": price,
            **support_fields(settings), "notice": localized(notice, english_notice), "notice_labels": {"zh": notice, "en": english_notice}}


@router.post(
    "/reports", response_model=dict,
    summary='提交市场内容举报',
    description='登录后对有权访问的目标提交举报，证据须为本人已就绪的文档或图片资产；登记案件问题需联系客服处理。举报材料按私有权限保存。',
    response_description='新建举报记录 ID。',
)
async def report(body: ReportInput, db: DB, user: Actor):
    """举报证据私有存储，不把投诉人联系方式公开给被举报者。"""
    await get_target(db, body.target_type, body.target_id, user)
    if body.target_type == "case":
        fail("登记案件请联系客服补充说明")
    for asset_id in body.evidence_ids:
        await asset_owned(db, asset_id, user, ("document", "image"))
    item = Report(owner_id=user.id, **body.model_dump())
    db.add(item)
    await db.flush()
    event(db, user.id, "report", item.id, "created")
    notify(db, user.id, f"举报 #{item.id} 已收到，平台将核查材料")
    await db.commit()
    return {"id": item.id}
