"""下游共享业务规则；审核、访问与咨询复用同一就绪判定。"""
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from .models import Asset, Event, Notification, Recruit, RegistrationCase, Rights, Submission, Work, WorkPreview


def now() -> datetime:
    """统一使用 UTC，展示层负责北京时间格式化。"""
    return datetime.now(timezone.utc)


def fail(message: str, status: int = 400) -> None:
    """抛出可读业务错误。"""
    raise HTTPException(status, detail=message)


def check_version(record, version: int) -> None:
    """锁定后比较版本，拒绝过期页面提交和旧审核结论。"""
    if record.version != version:
        fail("内容已更新，请刷新后重新操作", 409)


async def owned(db: AsyncSession, model, record_id: int, user: User, *, admin: bool = False):
    """锁定独立记录并验证所属用户。"""
    record = (await db.execute(select(model).where(model.id == record_id).with_for_update())).scalar_one_or_none()
    if record is None or (record.owner_id != user.id and not (admin and user.role == "admin")):
        fail("记录不存在或无权访问", 404)
    return record


def ensure_kept(item) -> None:
    """已软删的作品不再进入编辑、审核和上架。"""
    if getattr(item, "deleted_at", None):
        fail("作品已删除", 404)


async def retire_owned(db: AsyncSession, item, user: User, kind: str) -> None:
    """作者软删自己的单视频或短剧，撤下展示并保留文件与审核记录。"""
    if item.owner_id != user.id:
        fail("只能删除自己的作品", 403)
    if item.deleted_at:
        return
    from .models import Publication, SeriesEpisode
    item.deleted_at = now()
    item.listed = False
    publications = []
    if kind == "series":
        episodes = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == item.id).with_for_update())).scalars().all())
        episode_ids = []
        for episode in episodes:
            episode.listed = False
            episode_ids.append(episode.id)
        if episode_ids:
            publications = list((await db.execute(select(Publication).where(Publication.content_type == "series_episode", Publication.content_id.in_(episode_ids)).with_for_update())).scalars().all())
    else:
        publications = list((await db.execute(select(Publication).where(Publication.content_type == "work", Publication.content_id == item.id).with_for_update())).scalars().all())
    for publication in publications:
        publication.listed = False
    event(db, user.id, kind, item.id, "deleted", version=getattr(item, "version", None))


async def asset_owned(db: AsyncSession, asset_id: int, user: User, kinds: tuple[str, ...] = ("video",)) -> Asset:
    """只接受本人的已就绪媒体，不接受任意 URL 或上游资源。"""
    asset = await owned(db, Asset, asset_id, user)
    if asset.kind not in kinds or asset.status != "ready":
        fail("文件尚未处理完成或类型不正确")
    return asset


async def asset_owned_for_draft(db: AsyncSession, asset_id: int, user: User, kinds: tuple[str, ...] = ("video",)) -> Asset:
    """草稿可绑定上传中/处理中媒体；发布前仍由 asset_owned 强制 ready。"""
    asset = await owned(db, Asset, asset_id, user)
    if asset.kind not in kinds or asset.status in ("failed", "expired"):
        fail("文件不存在、已失败或类型不正确")
    return asset


async def rights_for(db: AsyncSession, asset_id: int | None, *, lock: bool = False) -> Rights | None:
    """读取媒体绑定的权属档案。"""
    query = select(Rights).where(Rights.asset_id == asset_id)
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


def rights_valid(rights: Rights | None, *, full: bool = False) -> bool:
    """权属过期、封禁或版本更新时，立即停止依赖它的访问。"""
    if not rights or rights.blocked or (rights.valid_until and rights.valid_until <= now()):
        return False
    if rights.basic_status != "approved":
        return False
    if rights.details.get("source") == "printfilm" and not full_proof_present(rights):
        return False
    return not full or (rights.full_status == "approved" and full_proof_present(rights))


def full_proof_present(rights: Rights) -> bool:
    """读取已核验材料时保留明确支持的历史授权；新提交另行检查现行版本。"""
    if rights.details.get("source") == "printfilm":
        from .letter_template import PUBLISHED_VERSIONS
        return bool(rights.details.get("authorization_id") and rights.details.get("authorization_version") in PUBLISHED_VERSIONS)
    return bool(rights.certificate_asset_id)


def public_work_filters() -> tuple:
    """列表与详情使用相同 SQL 条件，价格筛选前即排除不可售作品。"""
    from .letter_template import PUBLISHED_VERSIONS
    from .previews import CLIP_WORK_PREFIX
    proof = or_(and_(Rights.details["source"].as_string() == "printfilm",
                     Rights.details["authorization_id"].as_string().is_not(None),
                     Rights.details["authorization_version"].as_string().in_(PUBLISHED_VERSIONS)),
                and_(Rights.details["source"].as_string() != "printfilm", Rights.certificate_asset_id.is_not(None)))
    def preview_exists():
        return select(WorkPreview.id).where(
            WorkPreview.work_id == Work.id, WorkPreview.asset_id == Work.asset_id,
            WorkPreview.version == Work.version, WorkPreview.status == "done",
            WorkPreview.object_key.startswith(CLIP_WORK_PREFIX)).exists()

    return (Work.listed.is_(True), Work.blocked.is_(False), Work.deleted_at.is_(None), Work.audit_status == "approved",
            Asset.status == "ready", Rights.basic_status == "approved", Rights.full_status == "approved",
            or_(Work.sale_type == "free", preview_exists()),
            proof, Rights.blocked.is_(False),
            Rights.details["source"].as_string() == Work.source,
            or_(Rights.valid_until.is_(None), Rights.valid_until > now()))


def public_recruit_filters() -> tuple:
    """招募到期在每次请求时校验，不依赖维护任务及时运行。"""
    return (Recruit.audit_status == "approved", Recruit.state == "open", Recruit.blocked.is_(False), Recruit.deadline_at > now())


async def is_public_work(db: AsyncSession, work_id: int) -> bool:
    """统一判断作品是否允许公众播放或咨询购买。"""
    query = select(Work.id).join(Asset, Asset.id == Work.asset_id).join(Rights, Rights.asset_id == Asset.id).where(Work.id == work_id, *public_work_filters())
    return (await db.execute(query)).scalar_one_or_none() is not None


def recruit_open(post: Recruit) -> bool:
    """投稿写入前实时检查截止、审核和关闭状态。"""
    return post.state == "open" and post.audit_status == "approved" and not post.blocked and post.deadline_at > now()


def event(db: AsyncSession, actor: int, kind: str, target: int, action: str, note: str = "", version: int | None = None) -> None:
    """保留审核与敏感访问审计，不保存密码或签名 URL。"""
    db.add(Event(actor_id=actor, target_type=kind, target_id=target, action=action, note=note, version=version))


def notify(db: AsyncSession, owner: int, message: str, link: str = "/marketplace/mine") -> None:
    """站内消息与业务事务一并提交，不依赖 SMTP。"""
    from .notification_locale import encode
    code, params = encode(message)
    db.add(Notification(owner_id=owner, message=str(message), link=link, template_code=code, message_params=params))


def data(record, *fields: str) -> dict:
    """显式字段序列化，禁止把 ORM 整行直接暴露给公众。"""
    return {field: getattr(record, field) for field in fields}


async def work_data(db: AsyncSession, work: Work, private: bool = False) -> dict:
    """公开资料不包含邮箱、原片位置和权属材料。"""
    owner = await db.get(User, work.owner_id)
    asset = await db.get(Asset, work.asset_id) if work.asset_id else None
    result = data(work, "id", "title", "description", "category", "tags", "price_fen", "sale_type", "unlock_price_fen", "share_bps", "source", "license_scope", "created_at")
    from .categories import category_fields
    from .locale import localized
    result.update(await category_fields(db, work))
    result.update(author=owner.nickname if owner else localized("创作者", "Creator"), duration_seconds=asset.duration_seconds if asset else None)
    if private:
        from .previews import is_preview_key, preview_for, requires_preview
        preview = await preview_for(db, work)
        usable = bool(preview and preview.version == work.version and preview.status != "cancelled"
                      and (preview.status != "done" or is_preview_key(preview.object_key, episode=False)))
        result["preview_status"] = (preview.status if usable else "missing") if requires_preview(work.sale_type) else "none"
        result["preview_error"] = preview.error if usable and requires_preview(work.sale_type) else ""
        result.update(data(work, "owner_id", "asset_id", "cover_asset_id", "version", "audit_status", "listed", "blocked", "reason"))
        result["media_status"] = asset.status if asset else "missing"
        rights = await rights_for(db, work.asset_id)
        result["basic_status"] = rights.basic_status if rights else "missing"
        result["full_status"] = rights.full_status if rights else "missing"
        result["rights_ready"] = rights_valid(rights, full=True) and rights.details.get("source") == work.source
        result["rights_source"] = rights.details.get("source") if rights else None
        result["rights_complete"] = False
        if rights and not rights.blocked and rights.details.get("source") == work.source:
            try:
                validate_rights(rights.details, full=True, certificate=bool(rights.certificate_asset_id))
                result["rights_complete"] = True
            except HTTPException:
                pass
    return result


async def recruit_data(db: AsyncSession, post: Recruit, private: bool = False) -> dict:
    """招募公开说明不包含私密投稿。"""
    owner = await db.get(User, post.owner_id)
    result = data(post, "id", "title", "description", "category", "budget_fen", "wanted_count", "requirements", "license_scope", "image_ids", "deadline_at", "created_at")
    from .categories import category_fields
    from .locale import localized
    result.update(await category_fields(db, post))
    result["author"] = owner.nickname if owner else localized("需求发布者", "Client")
    if private:
        result.update(data(post, "owner_id", "version", "audit_status", "state", "blocked", "reason"))
        result["submission_count"] = (await db.execute(select(func.count()).select_from(Submission).where(Submission.recruit_id == post.id))).scalar_one()
    return result


async def submission_data(db: AsyncSession, item: Submission, user: User) -> dict:
    """仅相关双方可看投稿，签名接口仍再次检查基础核验。"""
    post = await db.get(Recruit, item.recruit_id)
    if user.id not in (item.owner_id, post.owner_id) and user.role != "admin":
        fail("无权访问投稿", 404)
    rights = await rights_for(db, item.asset_id)
    result = data(item, "id", "recruit_id", "owner_id", "asset_id", "quote_fen", "description", "snapshot", "selection", "withdrawn", "blocked", "created_at")
    matching = submission_rights_match(item, rights)
    result.update(recruit_title=post.title, can_review=matching and not item.withdrawn and not item.blocked and not post.blocked and rights_valid(rights),
                  can_purchase=matching and not item.withdrawn and not item.blocked and not post.blocked and rights_valid(rights, full=True))
    return result


def rights_identity(rights: Rights) -> str:
    """补交证书不改变投稿；作者、权利人或授权范围变化则必须重新投稿。"""
    identity = {key: rights.details.get(key, "") for key in ("author", "holder", "relationship", "acquisition", "source", "scope")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def submission_rights_match(item: Submission, rights: Rights | None) -> bool:
    """以稳定权利指纹校验快照，不因补材料版本增加而丢失候选。"""
    return bool(rights and item.snapshot.get("rights_identity") == rights_identity(rights))


async def page(db: AsyncSession, query, page_number: int, page_size: int) -> tuple[list, dict]:
    """数据库分页，避免全量数据下发再切片。"""
    total = (await db.execute(select(func.count()).select_from(query.order_by(None).subquery()))).scalar_one()
    records = list((await db.execute(query.offset((page_number - 1) * page_size).limit(page_size))).scalars().all())
    return records, {"page": page_number, "page_size": page_size, "total": total}


def validate_rights(details: dict, *, full: bool, certificate: bool) -> None:
    """按来源执行最小必要核验材料，避免让用户重复填写无关信息。"""
    source = details.get("source")
    if source == "printfilm":
        from .authorization import VERSION
        if not details.get("authorization_id") or details.get("authorization_version") != VERSION:
            fail("请先签署现行 PrintFilm 授权函，再保存权属档案以关联签署记录")
        return
    if source == "external" and full:
        if not certificate or not str(details.get("certificate_number", "")).strip():
            fail("请填写版权证书编号并上传截图或照片；没有版权材料可联系客服协办")
        if not details.get("dispute_ack"):
            fail("请确认版权纠纷与平台无关")
    if source not in ("printfilm", "external"):
        fields = ["author", "holder", "relationship", "acquisition", "scope", "third_party"]
        if source == "ai":
            fields.extend(["ai_platform_license", "ai_generation_record", "human_contribution"])
        if full:
            fields.extend(["institution", "certificate_number"])
            if not certificate:
                fail("请上传版权证书")
        if any(not str(details.get(key, "")).strip() for key in fields):
            fail("请补齐版权信息")


async def get_target(db: AsyncSession, kind: str, target_id: int, user: User):
    """咨询和举报共用可访问目标检查，防止凭编号枚举私密投稿。"""
    from .models import Series, SeriesEpisode
    model = {"work": Work, "recruit": Recruit, "submission": Submission, "series_episode": SeriesEpisode, "case": RegistrationCase}[kind]
    record = await db.get(model, target_id)
    if not record:
        fail("内容不存在", 404)
    if user.role == "admin" or record.owner_id == user.id:
        return record
    if kind == "work" and await is_public_work(db, target_id):
        return record
    if kind == "recruit" and recruit_open(record):
        return record
    if kind == "submission":
        post = await db.get(Recruit, record.recruit_id)
        if post.owner_id == user.id and not record.withdrawn:
            return record
    if kind == "series_episode":
        series = await db.get(Series, record.series_id)
        if (series and series.sale_type == "copyright_contact" and series.listed
                and series.audit_status == "approved" and record.listed
                and record.audit_status == "approved" and not series.blocked
                and not record.blocked):
            return record
    fail("内容不存在或无权访问", 404)
