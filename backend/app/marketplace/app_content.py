"""面向 App 的版本化内容契约，保留现有 Web 接口含义。"""
import asyncio
import base64
from datetime import datetime
import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Path, Query
from .distribution import AppEdition
from sqlalchemy import literal, select, tuple_, union_all

from app.config import get_settings
from app.models import User
from . import storage
from .app_access import (app_open, current_content, entitlement_filters, environment, error,
    has_entitlement, purchased_content, require_app_open, series_query, work_query)
from .app_media import media_for
from .categories import category_fields, category_filter, category_config
from .locale import localized
from .dependencies import Actor, DB, Visitor
from .models import Asset, Publication, Series, SeriesEpisode, Work
from .service import data
from .curation import (flags as curation_flags, join_curation, ordering_columns, revision as curation_revision,
    feed_fingerprint, encode_feed_cursor, decode_feed_cursor)

from .app_response import AppJSONResponse

router = APIRouter(default_response_class=AppJSONResponse)


def encode_cursor(timestamp, kind, record_id):
    """签名游标禁止拼接 SQL 条件，不依赖页码在新增内容时跳页。"""
    body = json.dumps([timestamp.isoformat(), kind, record_id], separators=(",", ":")).encode()
    signature = hmac.new(get_settings().secret_key.encode(), body, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(signature + body).decode().rstrip("=")


def decode_cursor(value):
    """所有无效或被修改游标均返回稳定业务错误。"""
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        signature, body = decoded[:16], decoded[16:]
        if not hmac.compare_digest(signature, hmac.new(get_settings().secret_key.encode(), body, hashlib.sha256).digest()[:16]):
            raise ValueError()
        timestamp, kind, record_id = json.loads(body)
        parsed = datetime.fromisoformat(timestamp)
        if not parsed.tzinfo or kind not in ("work", "series", "publication", "episode") or type(record_id) is not int or record_id < 1:
            raise ValueError()
        return parsed, kind, record_id
    except (ValueError, TypeError, json.JSONDecodeError):
        error("MARKETPLACE_CURSOR_INVALID", "分页位置无效，请刷新列表", 422)


async def cover_url(db, asset_id):
    """封面只签已就绪对象；无存储配置时提供真实的空状态。"""
    if not asset_id or not storage.configured():
        return None
    asset = await db.get(Asset, asset_id)
    if not asset or asset.status != "ready":
        return None
    return await asyncio.to_thread(storage.signed, asset.object_key, asset.content_type)


def author_card(user: User | None, owner_id: int) -> dict:
    """列表和详情共用创作者卡片。只给昵称和头像地址，不返回邮箱。"""
    return {"id": owner_id, "name": user.nickname if user else localized("创作者", "Creator"), "avatar_url": (user.avatar_url or "") if user else ""}


def video_shape(asset) -> dict:
    """只读已保存的显示宽高。没有记录或探测失败时返回空，不在请求里下载原片。"""
    from .drama_geometry import orientation_name
    width = int(asset.display_width or 0) if asset else 0
    height = int(asset.display_height or 0) if asset else 0
    if width < 1 or height < 1:
        return {"display_width": None, "display_height": None, "orientation": None}
    return {"display_width": width, "display_height": height, "orientation": orientation_name(width, height)}


async def content_data(db, kind, item, parent, asset, publication, free, user=None):
    """公开资料不泄露对象键、邮箱、版权附件或后台分成配置。"""
    author = await db.get(User, item.owner_id)
    entitled = bool(publication and user and await has_entitlement(db, user.id, publication.id))
    mode = "free" if free else "entitled" if entitled else "preview"
    media = await media_for(db, kind, item.id, item.version, "preview" if mode == "preview" else "full")
    from .app_social import _stats
    social = await _stats(db, "episode" if kind == "series_episode" else kind, item.id, user.id if user else None)
    return {**await curation_flags(db, kind, item.id), **await category_fields(db, parent), **data(item, "id", "title", "description", "version"), "content_type": kind,
        "author": author_card(author, item.owner_id),
        "creator": author_card(author, item.owner_id), "engagement": {k: social[k] for k in ("like_count", "comment_count", "favorite_count", "share_count", "liked_by_me", "favorited_by_me")},
        "social": {"comments_enabled": social["comments_enabled"]},
        "category": parent.category, "tags": parent.tags, "sale_type": parent.sale_type,
        "cover_url": await cover_url(db, item.cover_asset_id or (parent.cover_asset_id if kind == "series_episode" else None)),
        "duration_seconds": asset.duration_seconds if asset else None, **video_shape(asset),
        "series_id": item.series_id if kind == "series_episode" else None,
        "episode_no": item.episode_no if kind == "series_episode" else None,
        "publication_id": publication.id if publication else None, "is_free": free,
        "unlock_coins": 0 if free else publication.unlock_price_fen if publication else item.unlock_price_fen,
        "entitled": entitled, "access_mode": mode,
        "playback_ready": bool(media and media.status == "done" and media.asset_id == item.asset_id),
        "playback_status": media.status if media else "pending", "created_at": item.created_at}


async def series_data(db, item, user=None):
    """系列列表保持一张卡片，分集详情通过独立分页目录读取。"""
    author = await db.get(User, item.owner_id)
    from sqlalchemy import func
    count = await db.scalar(select(func.count()).select_from(SeriesEpisode).where(SeriesEpisode.series_id == item.id))
    first = await db.scalar(select(SeriesEpisode).where(SeriesEpisode.series_id == item.id).order_by(SeriesEpisode.episode_no).limit(1))
    asset = await db.get(Asset, first.asset_id) if first and first.asset_id else None
    from .app_social import _stats
    social = await _stats(db, "series", item.id, user.id if user else None)
    return {**await curation_flags(db, "series", item.id), **await category_fields(db, item), **data(item, "id", "title", "description", "category", "tags", "version", "sale_type", "free_episode_count", "created_at"),
        "content_type": "series", "episode_count": count,
        "author": author_card(author, item.owner_id), "creator": author_card(author, item.owner_id),
        "engagement": {k: social[k] for k in ("like_count", "comment_count", "favorite_count", "share_count", "liked_by_me", "favorited_by_me")},
        "social": {"comments_enabled": social["comments_enabled"]},
        "cover_url": await cover_url(db, item.cover_asset_id), **video_shape(asset)}


@router.get("/capabilities", response_model=dict)
async def capabilities(user: Visitor):
    """配置可用不等于真实苹果购买或 OSS 联调已验收。"""
    from .app_settings import get_app_settings
    from .apple_client import apple_configured
    config = get_app_settings()
    from .apple_api import purchasing_enabled
    from .sandbox_wallet import tester, new_purchase_allowed
    testing = tester(user.id if user else None)
    from app.services.billing import wallet
    return {"sharing_enabled": bool(getattr(config, "sharing_enabled", False) and app_open()), "enabled": app_open(), "social_enabled": bool(config.social_enabled and app_open()), "comments_enabled": bool(config.comments_enabled and app_open()), "storage_configured": storage.configured(),
        "apple_iap_enabled": new_purchase_allowed(user.id) if testing else bool(config.apple_iap_enabled), "environment": environment(user.id if user else None),
        "payments_configured": apple_configured(),
        "purchasing_enabled": purchasing_enabled(user.id if user else None),
        "unified_wallet_enabled": wallet.enabled(), "wallet_type": "sandbox_test" if testing else "platform_balance", "test_only": testing,
        "coin_value_fen": 1, "offline_download": False, "supported_locales": ["zh", "en"], "default_locale": "zh"}


@router.get("/categories", response_model=dict)
async def app_categories(db: DB):
    """App 与 Web 共用分类代码和双语名称。"""
    require_app_open()
    return await category_config(db)


@router.get(
    "/feed", response_model=dict, summary="获取 App 推荐或最新内容流",
    description=("先按分类、关键词、内容类型及公开权限筛选，再执行服务端排序。默认 recommended：置顶优先、置顶排序值降序、"
                 "精选优先、发布时间及内容类型与编号降序；latest 严格按发布时间排序。公开卡片只返回 is_featured 和 is_pinned，"
                 "不返回运营权重。推荐排序调整后，或请求读取期间运营排序发生变化，返回409 MARKETPLACE_FEED_UPDATED；"
                 "客户端应清空列表和游标并重新加载第一页。旧时间游标仅兼容 latest；切换筛选或排序需清空游标。"),
    responses={
        200: {"description": "服务端排序后的作品及系列卡片、分页状态和下一页游标。", "content": {"application/json": {"schema": {
            "type": "object", "properties": {
                "items": {"type": "array", "items": {"type": "object", "properties": {
                    "is_featured": {"type": "boolean", "description": "平台精选标识，仅由运营设置；前端可显示精选 / Featured。"},
                    "is_pinned": {"type": "boolean", "description": "平台置顶标识，仅由运营设置；仅推荐排序提高位置，latest仍遵守时间排序。"},
                }}},
                "has_more": {"type": "boolean"},
                "next_cursor": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "不透明签名游标，原样传回；无下一页时为null。"},
            }}}}},
        409: {"description": "推荐列表已更新，请清空列表和游标后重新加载。", "content": {"application/json": {
            "example": {"detail": {"code": "MARKETPLACE_FEED_UPDATED", "message": "列表已更新，请刷新"}}
        }}},
    },
)
async def feed(db: DB, user: Visitor, q: str = Query("", max_length=100), category: str = Query("", max_length=60), category_code: str = Query("", max_length=80),
               content_type: str = Query("all", pattern="^(all|work|series)$"), cursor: str = Query("", max_length=1024, description="上一页返回的next_cursor；切换筛选或排序时清空。"),
               limit: int = Query(20, ge=1, le=50), sort: str = Query("recommended", pattern="^(recommended|latest)$", description="recommended：置顶及精选优先（默认）；latest：严格按发布时间。"),
               app_edition: AppEdition = Query("domestic", description="国内版domestic、国际版international；省略默认国内版。先筛投放范围再排序分页，与语言无关。")):
    """SQL 层先筛审核、版权、封禁和作者屏蔽，再执行稳定游标分页。"""
    require_app_open()
    fingerprint = feed_fingerprint(q=q, category=category, category_code=category_code, content_type=content_type, sort=sort, user_id=user.id if user else None, app_edition=app_edition)
    revision = await curation_revision(db) if sort == "recommended" else 0
    queries = []
    for kind, model, query in (("work", Work, work_query(user.id if user else None, app_edition)),
                               ("series", Series, series_query(user.id if user else None, app_edition))):
        if content_type not in ("all", kind):
            continue
        if q:
            query = query.where(model.title.ilike(f"%{q}%"))
        if category or category_code:
            query = query.where(await category_filter(db, model, category, category_code))
        query = join_curation(query, model, kind)
        queries.append(query.with_only_columns(*ordering_columns(), model.created_at.label("timestamp"), literal(kind).label("kind"), model.id.label("record_id")))
    combined = union_all(*queries).subquery()
    query = select(combined)
    keys = [combined.c.timestamp, combined.c.kind, combined.c.record_id]
    if sort == "recommended":
        keys = [combined.c.pin, combined.c.priority, combined.c.feature, *keys]
    if cursor:
        position = decode_feed_cursor(cursor, sort=sort, fingerprint=fingerprint, revision=revision, allow_legacy=app_edition == "domestic")
        query = query.where(tuple_(*keys) < position)
    rows = list((await db.execute(query.order_by(*(key.desc() for key in keys)).limit(limit + 1))).all())
    more, rows = len(rows) > limit, rows[:limit]
    items = []
    for row in rows:
        if row.kind == "series":
            item = await db.scalar(series_query(user.id if user else None, app_edition).where(Series.id == row.record_id))
            if item:
                items.append(await series_data(db, item, user))
        else:
            try:
                resolved = await current_content(db, "work", row.record_id, user.id if user else None, app_edition)
            except HTTPException as exc:
                # 本页查询后恰好下架的条目跳过，不让整页发现接口失败。
                if exc.status_code != 404:
                    raise
                continue
            items.append(await content_data(db, "work", *resolved, user))
    # READ COMMITTED can observe an admin change between cursor validation,
    # ordering and item serialization. Never emit a page with a stale epoch.
    if sort == "recommended" and await curation_revision(db) != revision:
        error("MARKETPLACE_FEED_UPDATED", "列表已更新，请刷新", 409)
    return {"items": items, "has_more": more, "next_cursor": encode_feed_cursor(rows[-1], sort=sort, fingerprint=fingerprint, revision=revision) if more else None}


@router.get("/works/{work_id}", response_model=dict)
async def get_work(work_id: int, db: DB, user: Visitor):
    """App 公开详情不复用可返回作者草稿的 Web 管理视图。"""
    require_app_open()
    return await content_data(db, "work", *await current_content(db, "work", work_id, user.id if user else None), user)


@router.get("/series/{series_id}", response_model=dict)
async def get_series(series_id: int, db: DB, user: Visitor):
    """整部短剧保持原有统一审核规则。"""
    require_app_open()
    item = await db.scalar(series_query(user.id if user else None).where(Series.id == series_id))
    if not item:
        error("MARKETPLACE_CONTENT_UNAVAILABLE", "短剧不存在或暂不可访问", 404)
    return await series_data(db, item, user)


@router.get("/series/{series_id}/episodes", response_model=dict)
async def episodes(series_id: int, db: DB, user: Visitor, cursor: str = Query("", max_length=1024), limit: int = Query(20, ge=1, le=50)):
    """集号顺序分页，免费集明确标识，不按参考价推断。"""
    await get_series(series_id, db, user)
    query = select(SeriesEpisode).where(SeriesEpisode.series_id == series_id)
    if cursor:
        _, kind, episode_no = decode_cursor(cursor)
        if kind != "episode":
            error("MARKETPLACE_CURSOR_INVALID", "分集分页位置无效", 422)
        query = query.where(SeriesEpisode.episode_no > episode_no)
    rows = list((await db.scalars(query.order_by(SeriesEpisode.episode_no).limit(limit + 1))).all())
    more, rows = len(rows) > limit, rows[:limit]
    return {"items": [await content_data(db, "series_episode", *await current_content(db, "series_episode", item.id, user.id if user else None), user) for item in rows],
        "has_more": more, "next_cursor": encode_cursor(rows[-1].created_at, "episode", rows[-1].episode_no) if more else None}


async def purchased_data(db, publication, user):
    """历史版本的媒体与权益不变，互动始终归属原作品／分集而非发布版本。"""
    kind = publication.content_type
    item = await db.get(Work if kind == "work" else SeriesEpisode, publication.content_id)
    reason = ""
    try:
        asset = await purchased_content(db, publication, user.id)
    except HTTPException as exc:
        reason = exc.detail.get("message", "暂不可播放") if isinstance(exc.detail, dict) else str(exc.detail)
        asset = await db.get(Asset, publication.asset_id)
    media = await media_for(db, kind, publication.content_id, publication.version, "full")
    author = await db.get(User, publication.owner_id)
    # 下架或关闭发现入口不剥夺已购播放，但不能绕过公开可见性新增互动。
    interactive = False
    if not reason and app_open():
        try:
            await current_content(db, kind, publication.content_id, user.id)
            from .app_settings import get_app_settings
            interactive = bool(get_app_settings().social_enabled)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    engagement = {"like_count": 0, "comment_count": 0, "favorite_count": 0,
                  "share_count": 0, "liked_by_me": False, "favorited_by_me": False}
    comments_enabled = False
    if not reason:
        from .app_social import _stats
        social = await _stats(db, kind, publication.content_id, user.id)
        engagement = {key: social[key] for key in engagement}
        comments_enabled = bool(interactive and social["comments_enabled"])
    return {"id": publication.content_id, "publication_id": publication.id, "content_type": kind,
        "content_id": publication.content_id, "version": publication.version,
        "title": item.title if item else localized("历史作品", "Historical video"),
        "author": author_card(author, publication.owner_id), "creator": author_card(author, publication.owner_id),
        "engagement": engagement, "social": {"comments_enabled": comments_enabled,
                                               "interaction_available": interactive},
        "cover_url": await cover_url(db, publication.cover_asset_id),
        "duration_seconds": asset.duration_seconds if asset else None, **video_shape(asset),
        "series_id": item.series_id if isinstance(item, SeriesEpisode) else None,
        "episode_no": item.episode_no if isinstance(item, SeriesEpisode) else None,
        "sale_type": publication.sale_type, "is_free": False, "entitled": True, "access_mode": "entitled",
        "unlock_coins": publication.unlock_price_fen,
        "playback_ready": bool(not reason and media and media.status == "done" and media.asset_id == publication.asset_id),
        "playback_status": media.status if media else "pending", "restricted_reason": reason, "permanent": True}


@router.get("/me/entitlements", response_model=dict,
            summary="查询已购发布版本及实时创作者与互动数据",
            description="需要登录，按当前服务端交易环境读取权益。媒体来自所购版本，互动按原作品或分集共用，不按版本拆分。下架保留已购播放，禁止新增互动；受限记录保留原因且不展示互动。")
async def entitlements(db: DB, user: Actor, cursor: str = Query("", max_length=1024), limit: int = Query(20, ge=1, le=50)):
    """已购不受展示开关和作者屏蔽影响，仍展示历史版本及受限原因。"""
    query = select(Publication).where(entitlement_filters(user.id))
    if cursor:
        _, kind, publication_id = decode_cursor(cursor)
        if kind != "publication":
            error("MARKETPLACE_CURSOR_INVALID", "已购分页位置无效", 422)
        query = query.where(Publication.id < publication_id)
    rows = list((await db.scalars(query.order_by(Publication.id.desc()).limit(limit + 1))).all())
    more, rows = len(rows) > limit, rows[:limit]
    return {"items": [await purchased_data(db, publication, user) for publication in rows],
            "has_more": more, "next_cursor": encode_cursor(rows[-1].created_at, "publication", rows[-1].id) if more else None}


@router.get("/me/entitlements/{publication_id}", response_model=dict,
            summary="查询指定已购版本的播放器详情",
            description="需要当前账号持有当前环境有效权益。返回与已购列表条目一致的 creator、engagement、social 和播放状态；即使当前作品下架也不回退到公开详情。无权益或不存在统一返回403。创建播放会话仍提交 publication_id。")
async def purchased_detail(db: DB, user: Actor, publication_id: int = Path(gt=0)):
    publication = await db.scalar(select(Publication).where(Publication.id == publication_id,
                                                           entitlement_filters(user.id)))
    if publication is None:
        error("MARKETPLACE_ENTITLEMENT_REQUIRED", "请先解锁该发布版本", 403)
    return await purchased_data(db, publication, user)
