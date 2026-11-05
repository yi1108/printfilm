"""分享业务链接及客户端完成事件；从不返回视频对象或播放令牌。"""
from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Literal
import uuid

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from app.config import get_settings
from .app_access import current_content, error, require_app_open
from .app_engagement import (aware, insert_once, lock_stats, public_type, stored_type, totals, utcnow)
from .app_engagement_models import ShareCredit, ShareEvent, ShareLink, ShareSession
from .app_settings import get_app_settings
from .dependencies import DB, Visitor
from .locale import localized

router = APIRouter()
public_router = APIRouter()
ShareTarget = Literal["works", "episodes"]


class ShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anonymous_id: str | None = Field(default=None, min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ShareEventInput(ShareInput):
    action: Literal["completed", "copied", "cancelled"]


class ShareSessionOutput(BaseModel):
    token: str = Field(description="24小时分享回调凭证，不得写入日志；不是播放令牌。")
    expires_at: datetime
    content_type: Literal["work", "series_episode"]
    content_id: int
    title: str
    description: str
    cover_url: str | None
    url: str = Field(description="稳定的公网HTTPS作品业务链接；不包含原片或HLS地址。")


class ShareEventOutput(BaseModel):
    ok: bool
    counted: bool = Field(description="此会话是否已计入真实分享；重复返回true不代表新增一次。")
    action: Literal["completed", "copied", "cancelled"]
    share_count: int = Field(description="已合计运营初始值及真实分享的展示总数。")


def sharing_configuration():
    from .sharing_config import validate_share_origin
    config = get_app_settings()
    try:
        origin = validate_share_origin(getattr(config, "share_base_url", ""))
    except (ValueError, TypeError):
        error("MARKETPLACE_SHARE_UNAVAILABLE", localized("请先在系统管理中配置有效的 HTTPS 分享域名。", "Configure a valid HTTPS sharing domain in system settings."), 503)
    team = getattr(config, "share_apple_team_id", "")
    bundle = getattr(config, "share_bundle_id", "") or getattr(config, "apple_bundle_id", "")
    if not team or not bundle:
        error("MARKETPLACE_SHARE_UNAVAILABLE", localized("请先在系统管理中补齐 Apple 分享关联配置。", "Complete the Apple sharing association settings first."), 503)
    return origin, team, bundle


def require_sharing():
    require_app_open()
    if not getattr(get_app_settings(), "sharing_enabled", False):
        error("MARKETPLACE_SHARE_UNAVAILABLE", localized("作品分享暂未开放。", "Content sharing is not available yet."), 503)
    return sharing_configuration()


def actor_key(user, anonymous_id):
    if user:
        value = f"user:{user.id}"
    elif anonymous_id:
        value = f"anonymous:{anonymous_id}"
    else:
        error("MARKETPLACE_SHARE_IDENTITY_REQUIRED", localized("游客分享需要匿名安装标识。", "An anonymous installation ID is required for guest sharing."), 422)
    return hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


async def share_link(db, kind, target_id):
    await insert_once(db, ShareLink, {"target_type": kind, "target_id": target_id, "public_id": uuid.uuid4().hex}, ["target_type", "target_id"])
    return await db.scalar(select(ShareLink).where(ShareLink.target_type == kind, ShareLink.target_id == target_id))


@router.post("/{target_type}/{target_id}/share-sessions", response_model=ShareSessionOutput,
    summary="准备单视频或当前分集分享", description="先检查App可见性及分享配置。游客须提供匿名安装ID，登录用户按账号识别；同一身份每分钟最多创建10个会话。会话有效24小时。")
async def create_share_session(target_type: ShareTarget, target_id: int, body: ShareInput, db: DB, user: Visitor):
    origin, _, _ = require_sharing()
    kind = "work" if target_type == "works" else "episode"
    item, parent, _, _, _ = await current_content(db, public_type(kind), target_id, user.id if user else None)
    identity = actor_key(user, body.anonymous_id)
    if db.bind.dialect.name == "postgresql":
        # Serialize COUNT + INSERT per identity across API processes. A hash
        # collision only makes unrelated identities wait; it cannot add quota.
        await db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :key)"), {
            "namespace": 18428,
            "key": int.from_bytes(bytes.fromhex(identity)[:4], "big", signed=True),
        })
    current = utcnow()
    recent = int(await db.scalar(select(func.count()).select_from(ShareSession).where(ShareSession.actor_key == identity,
        ShareSession.created_at > current - timedelta(minutes=1))) or 0)
    if recent >= 10:
        error("MARKETPLACE_SHARE_RATE_LIMITED", localized("分享操作过于频繁，请稍后再试。", "Too many share requests. Please try again shortly."), 429)
    link = await share_link(db, kind, target_id)
    token = secrets.token_urlsafe(36)
    expires = current + timedelta(hours=24)
    db.add(ShareSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), actor_key=identity,
        target_type=kind, target_id=target_id, expires_at=expires))
    from .app_content import cover_url
    cover = await cover_url(db, item.cover_asset_id or parent.cover_asset_id)
    await db.commit()
    return {"token": token, "expires_at": expires, "content_type": public_type(kind), "content_id": target_id,
        "title": item.title, "description": (item.description or parent.description or "")[:300],
        "cover_url": cover, "url": f"{origin}/s/{link.public_id}"}


@router.post("/share-sessions/{token}/events", response_model=ShareEventOutput,
    summary="确认分享或复制操作", description="仅在系统分享完成或复制成功后上报；取消不计数。首个有效事件确定会话结果，重试原令牌和原动作。同身份同作品滚动24小时最多计数一次。")
async def finish_share_session(token: str, body: ShareEventInput, db: DB, user: Visitor):
    require_sharing()
    if len(token) > 100:
        error("MARKETPLACE_SHARE_SESSION_INVALID", localized("分享会话无效。", "Invalid sharing session."), 404)
    hashed = hashlib.sha256(token.encode()).hexdigest()
    row = await db.scalar(select(ShareSession).where(ShareSession.token_hash == hashed))
    identity = actor_key(user, body.anonymous_id)
    if not row or not hmac.compare_digest(row.actor_key, identity):
        error("MARKETPLACE_SHARE_SESSION_INVALID", localized("分享会话不存在或无权访问。", "The sharing session is unavailable."), 404)
    current = utcnow()
    if aware(row.expires_at) <= current:
        error("MARKETPLACE_SHARE_SESSION_EXPIRED", localized("分享会话已过期，请重新分享。", "The sharing session has expired. Please start again."), 410)
    await current_content(db, public_type(row.target_type), row.target_id, user.id if user else None)
    stats = await lock_stats(db, row.target_type, row.target_id)
    row = await db.scalar(select(ShareSession).where(ShareSession.id == row.id).with_for_update().execution_options(populate_existing=True))
    counted = False
    if row.completed_at is None:
        row.completed_at, row.action = current, body.action
        if body.action != "cancelled":
            created = await insert_once(db, ShareCredit, {"actor_key": identity, "target_type": row.target_type,
                "target_id": row.target_id, "last_shared_at": current}, ["actor_key", "target_type", "target_id"])
            credit = await db.scalar(select(ShareCredit).where(ShareCredit.actor_key == identity,
                ShareCredit.target_type == row.target_type, ShareCredit.target_id == row.target_id).with_for_update())
            if created or aware(credit.last_shared_at) <= current - timedelta(hours=24):
                credit.last_shared_at = current
                stats.share_count += 1
                db.add(ShareEvent(session_id=row.id, target_type=row.target_type, target_id=row.target_id, action=body.action))
                counted = True
    else:
        counted = bool(await db.scalar(select(ShareEvent.id).where(ShareEvent.session_id == row.id)))
    await db.flush()
    result = await totals(db, row.target_type, row.target_id, stats)
    await db.commit()
    return {"ok": True, "counted": counted, "action": row.action, "share_count": result["share_count"]}


@public_router.get("/s/{public_id}", include_in_schema=False)
async def open_shared_content(public_id: str, db: DB):
    """链接只解析到业务页面；每次访问重查可见性，不提供任何视频对象。"""
    require_app_open()
    origin, _, _ = sharing_configuration()
    row = await db.scalar(select(ShareLink).where(ShareLink.public_id == public_id))
    if not row:
        error("MARKETPLACE_CONTENT_UNAVAILABLE", localized("作品不存在或暂不可访问。", "The content is not available."), 404)
    item, _, _, _, _ = await current_content(db, public_type(row.target_type), row.target_id)
    path = f"/marketplace/works/{item.id}" if row.target_type == "work" else f"/marketplace/series/{item.series_id}?episode_id={item.id}"
    return RedirectResponse(f"{origin}{path}", status_code=302, headers={"Cache-Control": "no-store"})


@public_router.get("/.well-known/apple-app-site-association", include_in_schema=False)
async def apple_association():
    _, team, bundle = sharing_configuration()
    return {"applinks": {"apps": [], "details": [{"appID": f"{team}.{bundle}", "paths": ["/s/*"]}]}}
