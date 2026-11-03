"""App 可续期播放会话；每个分片在服务端鉴权后才签发短时私有 OSS URL。"""
import asyncio
from functools import lru_cache
import json
import re
import secrets
import time

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from redis.asyncio import Redis

from app.config import get_settings
from app.models import User
from . import storage
from .app_access import (current_content, environment, error, has_entitlement, purchased_content, require_app_open)
from .app_media import enqueue
from .app_media_models import AppMedia
from .dependencies import DB, Visitor, storage_ready
from .models import Publication

router = APIRouter()
SESSION_IDLE_SECONDS = 1800
SESSION_MAX_SECONDS = 7200
SEGMENT_SECONDS = 60
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,80}$")


def session_limits():
    """配置可缩短会话期限，仍受计划中的30分钟/2小时上限约束。"""
    from .app_settings import get_app_settings
    settings = get_app_settings()
    return settings.playback_idle_seconds, settings.playback_max_seconds


class PlaybackInput(BaseModel):
    """客户端仅提交业务 ID，不能提交视频、清单或对象路径。"""
    model_config = ConfigDict(extra="forbid")
    content_type: str | None = Field(None, pattern="^(work|series_episode)$")
    content_id: int | None = Field(None, gt=0)
    publication_id: int | None = Field(None, gt=0)

    @model_validator(mode="after")
    def one_target(self):
        if self.publication_id is not None:
            if self.content_type is not None or self.content_id is not None:
                raise ValueError("已购版本和当前内容只能选择一种")
        elif not self.content_type or self.content_id is None:
            raise ValueError("请指定作品或已购发布版本")
        return self


@lru_cache
def session_store():
    """Redis 只保存短期播放会话，财务和权益仍由数据库持久化。"""
    return Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)


async def put_session(token, value):
    """任何缓存故障均拒绝播放，不回退到公开链接。"""
    try:
        ttl = min(session_limits()[0], int(value["expires_at"] - time.time()))
        if ttl <= 0:
            error("MARKETPLACE_PLAYBACK_SESSION_EXPIRED", "播放会话已到期，请重新加载", 401)
        await session_store().set(f"marketplace:app:playback:{token}", json.dumps(value), ex=ttl)
    except Exception as exc:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            raise
        error("MARKETPLACE_PLAYBACK_UNAVAILABLE", "播放服务暂不可用，请稍后重试", 503)


async def get_session(token):
    """访问延长空闲期限，但不超过最初两小时的绝对期限。"""
    if not TOKEN_PATTERN.fullmatch(token):
        error("MARKETPLACE_PLAYBACK_SESSION_EXPIRED", "播放会话无效或已到期", 401)
    try:
        raw = await session_store().get(f"marketplace:app:playback:{token}")
        value = json.loads(raw) if raw else None
    except Exception:
        error("MARKETPLACE_PLAYBACK_UNAVAILABLE", "播放服务暂不可用，请稍后重试", 503)
    if not value or value.get("expires_at", 0) <= time.time() or value.get("environment") != environment():
        error("MARKETPLACE_PLAYBACK_SESSION_EXPIRED", "播放会话已到期，请重新加载", 401)
    await put_session(token, value)
    return value


def parse_playlist(text: str, prefix: str):
    """只允许本 Worker 生成的单层 TS 清单，拒绝所有 URI 属性、外部地址和穿越。"""
    if not text.startswith("#EXTM3U") or "#EXT-X-ENDLIST" not in text or not prefix.startswith("marketplace/app-hls/"):
        error("MARKETPLACE_PLAYLIST_INVALID", "播放清单无效", 502)
    segments, lines = [], []
    for line in text.splitlines():
        value = line.strip()
        if value.startswith("#"):
            if re.search(r"\bURI\s*=", value, re.I) or value.startswith(("#EXT-X-STREAM-INF", "#EXT-X-I-FRAME-STREAM-INF", "#EXT-X-BYTERANGE")):
                error("MARKETPLACE_PLAYLIST_INVALID", "播放清单含不支持的地址引用", 502)
            lines.append(line)
        elif value:
            if not re.fullmatch(r"segment-\d{5,}\.ts", value):
                error("MARKETPLACE_PLAYLIST_INVALID", "播放分片地址无效", 502)
            segments.append(prefix + value)
            lines.append(f"segments/{len(segments) - 1}")
        else:
            lines.append("")
    if not segments or len(segments) > 10000:
        error("MARKETPLACE_PLAYLIST_INVALID", "播放清单没有有效分片", 502)
    return "\n".join(lines) + "\n", segments


async def authorize_session(db, value):
    """每次清单和分片访问重新校验，不缓存已撤销权益。"""
    if value["access_mode"] == "entitled":
        publication = await db.get(Publication, value["publication_id"])
        if not publication:
            error("MARKETPLACE_CONTENT_UNAVAILABLE", "发布版本不存在", 404)
        await purchased_content(db, publication, value["user_id"])
        if publication.asset_id != value["asset_id"] or publication.version != value["version"]:
            error("MARKETPLACE_CONTENT_CHANGED", "发布版本已变化，请重新加载", 409)
    else:
        require_app_open()
        item, _, asset, _, free = await current_content(db, value["content_type"], value["content_id"], value["user_id"])
        if item.version != value["version"] or asset.id != value["asset_id"] or (value["access_mode"] == "free" and not free):
            error("MARKETPLACE_CONTENT_CHANGED", "内容已更新，请重新加载", 409)
    media = await db.get(AppMedia, value["media_id"])
    if not media or media.status != "done" or media.asset_id != value["asset_id"]:
        error("MARKETPLACE_EPISODE_NOT_READY", "播放文件尚未就绪", 409)
    return media


@router.post("/playback-sessions", response_model=dict)
async def create_session(body: PlaybackInput, request: Request, db: DB, user: Visitor):
    """服务端决定免费、试看或已购原版本；不会把收费原片交给客户端。"""
    publication = None
    if body.publication_id:
        publication = await db.get(Publication, body.publication_id)
        if not publication or not user:
            error("MARKETPLACE_ENTITLEMENT_REQUIRED", "请登录并解锁对应发布版本", 403)
        asset = await purchased_content(db, publication, user.id)
        item, kind, free, mode = publication, publication.content_type, False, "entitled"
        content_id = publication.content_id
    else:
        require_app_open()
        kind, content_id = body.content_type, body.content_id
        item, parent, asset, publication, free = await current_content(db, kind, content_id, user.id if user else None)
        mode = "free" if free else "entitled" if publication and user and await has_entitlement(db, user.id, publication.id) else "preview"
        if mode == "entitled":
            await purchased_content(db, publication, user.id)
    await storage_ready()
    source_key = asset.object_key
    variant = "preview" if mode == "preview" else "full"
    if variant == "preview":
        from .previews import episode_preview_for, is_preview_key, preview_for
        preview = await preview_for(db, item) if kind == "work" else await episode_preview_for(db, item)
        if not preview or preview.status != "done" or preview.version != item.version or not is_preview_key(preview.object_key, episode=kind != "work"):
            error("MARKETPLACE_EPISODE_NOT_READY", "短试看尚未就绪", 409)
        source_key = preview.object_key
    # 发布快照使用 content_id，不使用发布记录自身的 ID 作为作品 ID。
    from types import SimpleNamespace
    target = SimpleNamespace(id=content_id, version=item.version)
    media = await enqueue(db, kind, target, asset, variant, source_key)
    await db.commit()
    if media.status != "done" or not media.manifest_key:
        error("MARKETPLACE_EPISODE_NOT_READY", "App 播放文件准备失败，请联系客服重试" if media.status == "failed"
              else "视频正在准备 App 播放版本，请稍后重试", 409)
    text = (await asyncio.to_thread(storage.read, media.manifest_key)).decode("utf-8")
    _, segments = parse_playlist(text, media.manifest_key.rsplit("/", 1)[0] + "/")
    token, started = secrets.token_urlsafe(36), time.time()
    idle_seconds, max_seconds = session_limits()
    value = {"user_id": user.id if user else None, "environment": environment(), "content_type": kind,
        "content_id": content_id, "publication_id": publication.id if publication else None,
        "asset_id": asset.id, "version": item.version, "access_mode": mode, "media_id": media.id,
        "created_at": started, "expires_at": started + max_seconds, "segments": segments}
    await put_session(token, value)
    base = get_settings().public_base_url.rstrip("/")
    return {"session_id": token, "playback_url": f"{base}/api/marketplace/app/v1/playback-sessions/{token}/index.m3u8",
        "format": "hls", "access_mode": mode, "publication_id": value["publication_id"],
        "expires_in": idle_seconds, "max_lifetime_seconds": max_seconds}


@router.get("/playback-sessions/{token}/index.m3u8", name="app_playback_manifest", response_class=Response,
    responses={200: {"description": "鉴权后的HLS播放清单", "content": {"application/vnd.apple.mpegurl": {"schema": {"type": "string"}}}}})
async def manifest(token: str, db: DB):
    """返回 AVPlayer 可直接请求的清单，不把签名分片一次性固化在整片中。"""
    value = await get_session(token)
    media = await authorize_session(db, value)
    await storage_ready()
    text = (await asyncio.to_thread(storage.read, media.manifest_key)).decode("utf-8")
    rewritten, segments = parse_playlist(text, media.manifest_key.rsplit("/", 1)[0] + "/")
    if segments != value["segments"]:
        error("MARKETPLACE_CONTENT_CHANGED", "播放文件已变化，请重新加载", 409)
    return PlainTextResponse(rewritten, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "private, no-store"})


@router.get("/playback-sessions/{token}/segments/{segment_id}", response_class=RedirectResponse, status_code=302,
    responses={302: {"description": "重定向至60秒有效的OSS分片地址", "headers": {"Location": {"schema": {"type": "string", "format": "uri"}}}}})
async def segment(token: str, segment_id: int, db: DB):
    """分片逐次鉴权后重定向到60秒 OSS 链接，视频流量不经过 API。"""
    value = await get_session(token)
    await authorize_session(db, value)
    if segment_id < 0 or segment_id >= len(value["segments"]):
        error("MARKETPLACE_SEGMENT_NOT_FOUND", "播放分片不存在", 404)
    await storage_ready()
    # 不改现有 Web signer 的默认5分钟配置。
    url = await asyncio.to_thread(lambda: storage.bucket().sign_url("GET", value["segments"][segment_id], SEGMENT_SECONDS, slash_safe=True))
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "private, no-store"})
