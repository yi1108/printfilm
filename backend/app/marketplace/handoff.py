"""把 PrintFilm 成片异步复制到市场前缀。

接口只接受项目或分集编号。视频地址由服务端读取并记在转存记录里，
复制、指纹和探测由现有市场 Worker 完成，不在请求里下载整段视频。
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import hashlib
import logging
from pathlib import Path
from urllib.parse import unquote, urlparse
import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.models import Project
from app.models_drama import DramaEpisode, DramaEpisodeFragment, DramaProject
from .authorization import current as current_authorization
from .categories import category_config
from .config import get_marketplace_settings
from .dependencies import Actor, DB, storage_ready
from .models import Asset, Handoff, Series, SeriesEpisode, Work
from .schemas import PrintfilmEpisodeInput, PrintfilmWorkInput
from .service import data, fail, notify, now

logger = logging.getLogger("marketplace.handoff")
router = APIRouter()
VIDEO_LIMIT = 2 * 1024 * 1024 * 1024
IMAGE_LIMIT = 20 * 1024 * 1024
_VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska"}
_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def object_key(locator: str, *, bucket: str, public_base: str, folder: str) -> str | None:
    """从本站 OSS 地址或对象键取出同桶复制用的 key；本地地址不在这里解析。"""
    text = (locator or "").strip()
    if not text or text.startswith("/static/") or text.startswith("marketplace/"):
        return None
    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        path = unquote(parsed.path).lstrip("/")
        host = parsed.netloc.split("@")[-1]
        if bucket and host.startswith(f"{bucket}."):
            return path or None
        if bucket and path.startswith(f"{bucket}/"):
            path = path[len(bucket) + 1 :]
            return path or None
        base = public_base.rstrip("/")
        bare = text.split("?", 1)[0]
        if bare.startswith(base + "/"):
            return unquote(bare[len(base) + 1 :]) or None
        marker = f"/{folder.strip('/')}/"
        index = parsed.path.find(marker)
        if index >= 0:
            return unquote(parsed.path[index + 1 :].split("?", 1)[0]) or None
        return None
    key = text.split("?", 1)[0].lstrip("/")
    if not key or key.startswith("marketplace/") or key.startswith("static/"):
        return None
    prefix = folder.strip("/")
    if prefix and not key.startswith(prefix + "/") and "/" not in key:
        key = f"{prefix}/{key}"
    return key


def _version(marker: str, locator: str) -> str:
    digest = hashlib.sha256(locator.encode()).hexdigest()[:16]
    return f"{marker}:{digest}"[:80]


def _item_key(prefix: str, source_kind: str, source_id: int, version: str) -> str:
    raw = f"{prefix}:{source_kind}:{source_id}" if prefix else f"{source_kind}:{source_id}:{version}"
    return raw if len(raw) <= 120 else hashlib.sha256(raw.encode()).hexdigest()


def _suffix(locator: str, default: str) -> str:
    suffix = Path(locator.split("?", 1)[0]).suffix.lower()
    if suffix in _VIDEO_TYPES or suffix in _IMAGE_TYPES:
        return suffix
    return default


def _content_type(suffix: str, default: str) -> str:
    return _VIDEO_TYPES.get(suffix) or _IMAGE_TYPES.get(suffix) or default


def _local_file(locator: str) -> Path | None:
    """只接受 static 目录内的成片，避免按任意本地路径读取。"""
    from app.services import storage as upstream

    local = upstream.local_path_from_url(locator)
    if local and local.is_file():
        return local
    candidate = Path(locator)
    if not candidate.is_absolute() or not candidate.is_file():
        return None
    try:
        relative = candidate.resolve().relative_to(upstream.STATIC_ROOT.resolve())
    except ValueError:
        return None
    resolved = upstream.STATIC_ROOT / relative
    return resolved if resolved.is_file() else None


def place_object(locator: str, dest_key: str, content_type: str, limit: int) -> int:
    """同桶复制，或由服务器读取本地成片后上传。不向浏览器返回源地址。"""
    from app.config import get_settings
    from app.services import oss as upstream_oss
    from . import storage

    local = _local_file(locator)
    if local:
        size = local.stat().st_size
        if size <= 0 or size > limit:
            raise ValueError("成片大小无效或超过限制")
        storage.upload(dest_key, local, content_type)
        return size
    settings = get_settings()
    key = object_key(locator, bucket=settings.oss_bucket, public_base=upstream_oss.public_base(), folder=upstream_oss.folder_prefix())
    if not key:
        raise ValueError("成片尚未就绪")
    size = storage.copy_private(key, dest_key, content_type)
    if size <= 0 or size > limit:
        raise ValueError("成片大小无效或超过限制")
    return size


async def _view(db, item: Handoff) -> dict:
    """给页面的状态。不返回源地址、对象键或指纹原文以外的内部快照。"""
    authorization = await current_authorization(db, item.owner_id)
    ready = bool(authorization)
    retryable = not any(code in (item.error or "") for code in ("SOURCE_CHANGED", "TARGET_CHANGED", "SOURCE_INCOMPATIBLE", "重新选择分集"))
    if item.status == "failed":
        label = "同步失败，可重新同步" if retryable else "同步中断，请重新选择成片"
    elif item.status == "ready":
        label = "成片同步完成" if ready else "成片同步完成，提交审核前请签署授权函"
    else:
        label = "正在同步"
    payload = data(item, "id", "status", "target_kind", "target_id", "series_id", "asset_id", "attempts", "created_at")
    phase = (item.source_snapshot or {}).get("phase", "queued")
    phases = {"queued": "排队中", "copying": "正在同步素材", "composing": "正在合成完整分集", "validating": "正在校验视频", "ready": "同步完成", "failed": "同步失败"}
    payload.update(label=label, phase=item.status if item.status in ("ready", "failed") else phase,
                   phase_label=phases.get(item.status if item.status in ("ready", "failed") else phase, "正在同步"),
                   retryable=retryable,
                   authorization_ready=ready, error=item.error if item.status == "failed" else "",
                   work_id=item.target_id if item.target_kind == "work" else None,
                   episode_id=item.target_id if item.target_kind == "series_episode" else None)
    from .locale_messages import translate_message
    payload["label"] = translate_message(payload["label"])
    payload["phase_label"] = translate_message(payload["phase_label"])
    return payload


async def _owned_handoff(db, handoff_id: int, user) -> Handoff:
    item = await db.get(Handoff, handoff_id)
    if not item or item.owner_id != user.id:
        fail("转存记录不存在", 404)
    return item


async def _find(db, owner_id: int, key: str) -> Handoff | None:
    return (await db.execute(select(Handoff).where(Handoff.owner_id == owner_id, Handoff.idempotency_key == key))).scalar_one_or_none()


async def _category(db, preferred: str) -> str:
    names = (await category_config(db))["names"]
    if preferred in names:
        return preferred
    if "其他" in names:
        return "其他"
    return names[0] if names else "其他"


def _clip(value: str, limit: int) -> str:
    return (value or "").strip()[:limit]


async def _project_source(db, user_id: int, project_id: int) -> tuple[Project, str]:
    project = await db.get(Project, project_id)
    if not project or project.user_id != user_id:
        fail("成片不存在或无权访问", 404)
    locator = (project.final_video_url or "").strip()
    if not locator:
        fail("成片尚未生成", 409)
    return project, locator


async def _next_no(db, series_id: int) -> int:
    current = (await db.execute(select(func.max(SeriesEpisode.episode_no)).where(SeriesEpisode.series_id == series_id))).scalar_one()
    return int(current or 0) + 1


def _handoff(owner_id: int, key: str, source_kind: str, source_id: int, version: str, target_kind: str, target_id: int, series_id: int | None, locator: str, cover: str, title: str) -> Handoff:
    return Handoff(owner_id=owner_id, idempotency_key=key, source_kind=source_kind, source_id=source_id, source_version=version,
                   target_kind=target_kind, target_id=target_id, series_id=series_id, status="pending",
                   source_snapshot={"locator": locator, "cover_locator": cover, "title": title})


@router.get(
    "/printfilm/sources", response_model=dict,
    summary='获取我的 PRINTFILM 可转存来源',
    description='登录后列出本人已有成片的科普项目及可选择的漫剧分集上下文；科普项目最多返回最近更新的 50 项，不返回源视频地址。',
    response_description='科普项目 projects 与漫剧项目 dramas 列表。',
)
async def printfilm_sources(db: DB, user: Actor):
    """只列出当前用户已经生成成片的科普项目和漫剧分集，不返回视频地址。"""
    from .series import import_sources

    projects = list((await db.execute(select(Project).where(Project.user_id == user.id, Project.final_video_url.is_not(None), Project.final_video_url != "").order_by(Project.updated_at.desc()).limit(50))).scalars().all())
    dramas = await import_sources(db, user)
    return {"projects": [{"id": item.id, "title": item.title, "updated_at": item.updated_at, "has_cover": bool(item.cover_url), "status": item.status} for item in projects], "dramas": dramas["items"]}


@router.post(
    "/works/from-printfilm", response_model=dict,
    summary='将科普成片转为市场作品草稿',
    description='仅源项目所有者可操作。校验私有存储后登记市场草稿和异步转存任务；相同幂等键及来源成片版本的重复请求复用原记录，文件复制由市场 Worker 执行。',
    response_description='目标作品信息与转存任务状态。',
)
async def work_from_printfilm(body: PrintfilmWorkInput, db: DB, user: Actor):
    """把一部科普成片登记为市场草稿。同一成片版本重复点击返回原来的草稿。"""
    await storage_ready()
    project, locator = await _project_source(db, user.id, body.project_id)
    version = _version(project.updated_at.isoformat(), locator)
    key = _item_key(body.idempotency_key.strip(), "project_final", project.id, version)
    existing = await _find(db, user.id, key)
    if existing:
        return await _view(db, existing)
    work = Work(owner_id=user.id, title=_clip(project.title or "未命名作品", 200) or "未命名作品", description=_clip(project.source_text or "", 5000),
                category=await _category(db, "科普"), price_fen=0, sale_type="copyright_contact", source="printfilm", audit_status="draft")
    from .categories import resolve_category
    work.category, work.category_code = await resolve_category(db, work.category)
    db.add(work)
    await db.flush()
    db.add(_handoff(user.id, key, "project_final", project.id, version, "work", work.id, None, locator, (project.cover_url or "").strip(), work.title))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await _find(db, user.id, key)
        if existing:
            return await _view(db, existing)
        raise
    created = await _find(db, user.id, key)
    return await _view(db, created)


async def enqueue_series_import(series_id: int, body: PrintfilmEpisodeInput, db, user) -> dict:
    """把选中的漫剧分集或一部科普成片登记为短剧分集，实际复制交给 Worker。"""
    await storage_ready()
    if not body.project_id:
        from .drama_publish import legacy_import
        return await legacy_import(series_id, body, db, user)
    from .series import _episode_data, _series

    series = await _series(db, series_id, user, lock=True)
    from .service import ensure_kept
    ensure_kept(series)
    if series.owner_id != user.id:
        fail("只能导入到自己的短剧", 403)
    jobs: list[tuple[str, str, int, str, str, str, str]] = []
    if body.project_id:
        project, locator = await _project_source(db, user.id, body.project_id)
        version = _version(project.updated_at.isoformat(), locator)
        jobs.append((_item_key(body.idempotency_key.strip(), f"series{series.id}:project_final", project.id, version), "project_final", project.id, version, locator, (project.cover_url or "").strip(), _clip(project.title or "第1集", 200) or "第1集"))
    created: list[SeriesEpisode] = []
    records: list[Handoff] = []
    added = False
    for key, source_kind, source_id, version, locator, cover, title in jobs:
        existing = await _find(db, user.id, key)
        if existing:
            if existing.target_kind == "series_episode" and existing.series_id == series.id:
                episode = await db.get(SeriesEpisode, existing.target_id)
                if episode:
                    created.append(episode)
            records.append(existing)
            continue
        episode_no = await _next_no(db, series.id)
        item = SeriesEpisode(series_id=series.id, owner_id=user.id, episode_no=episode_no, title=title or f"第{episode_no}集", source="printfilm", source_type="drama_import",
                             source_snapshot={"source_kind": source_kind, "source_id": source_id, "source_title": title})
        db.add(item)
        await db.flush()
        handoff = _handoff(user.id, key, source_kind, source_id, version, "series_episode", item.id, series.id, locator, cover, item.title)
        db.add(handoff)
        created.append(item)
        records.append(handoff)
        added = True
    if added:
        series.version += 1
        series.audit_status, series.listed = "draft", False
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        records = []
        created = []
        for key, *_rest in jobs:
            existing = await _find(db, user.id, key)
            if not existing:
                continue
            records.append(existing)
            episode = await db.get(SeriesEpisode, existing.target_id) if existing.target_kind == "series_episode" else None
            if episode and episode.series_id == series.id:
                created.append(episode)
    return {"items": [await _episode_data(db, item, private=True) for item in created], "handoffs": [await _view(db, item) for item in records]}


@router.post(
    "/series/{series_id}/episodes/import-printfilm", response_model=dict,
    summary='将 PRINTFILM 内容导入系列分集',
    description='仅目标系列作者可操作。将选定漫剧分集或一部科普成片登记为分集草稿，实际复制异步执行；重复的同版本导入请求复用已有记录。',
    response_description='目标分集草稿 items 与转存记录 handoffs。',
)
async def import_printfilm(series_id: int, body: PrintfilmEpisodeInput, db: DB, user: Actor):
    """明确选中的漫剧分集，或一部科普成片，转成短剧分集草稿。"""
    return await enqueue_series_import(series_id, body, db, user)


@router.get(
    "/handoffs/{handoff_id}", response_model=dict,
    summary='查询自己的媒体转存任务',
    description='仅任务所属用户可查看。读取指定转存任务的来源、目标、处理进度和错误信息。',
    response_description='转存任务详情。',
)
async def get_handoff(handoff_id: int, db: DB, user: Actor):
    """查看自己的转存进度。"""
    return await _view(db, await _owned_handoff(db, handoff_id, user))


@router.get(
    "/handoffs", response_model=dict,
    summary='查询我的最近媒体转存任务',
    description='登录后查询本人最近 50 条转存记录。target_kind 与 target_id 同时提供时按目标筛选，series_id 非零时按系列筛选。',
    response_description='按任务 ID 倒序排列的转存记录 items。',
)
async def list_handoffs(db: DB, user: Actor, target_kind: str = "", target_id: int = 0, series_id: int = 0):
    """按作品、分集或系列查看当前用户的转存进度。"""
    query = select(Handoff).where(Handoff.owner_id == user.id)
    if target_kind and target_id:
        query = query.where(Handoff.target_kind == target_kind, Handoff.target_id == target_id)
    if series_id:
        query = query.where(Handoff.series_id == series_id)
    rows = list((await db.execute(query.order_by(Handoff.id.desc()).limit(50))).scalars().all())
    return {"items": [await _view(db, item) for item in rows]}


@router.post(
    "/handoffs/{handoff_id}/retry", response_model=dict,
    summary='重试失败的媒体转存任务',
    description='仅任务所属用户可操作。校验存储以及适用的漫剧来源和目标版本后，将 failed 任务重置为 pending；其他状态直接返回现有记录。',
    response_description='转存任务最新详情与状态。',
)
async def retry_handoff(handoff_id: int, db: DB, user: Actor):
    """失败后重新排队。已复制完成的记录保持不变。"""
    await storage_ready()
    item = await _owned_handoff(db, handoff_id, user)
    if item.status != "failed":
        return await _view(db, item)
    if item.source_kind == "drama_episode":
        await _validate_drama_source(db, item)
        await _drama_target(db, item)
    item.status, item.error, item.attempts = "pending", "", 0
    item.lease_token, item.lease_until = None, None
    await db.commit()
    return await _view(db, item)


async def _claim() -> tuple[int, str] | None:
    async with AsyncSessionLocal() as db:
        query = select(Handoff).where(or_(Handoff.status == "pending", and_(Handoff.status == "running", Handoff.lease_until < now()))).order_by(Handoff.id).with_for_update(skip_locked=True).limit(1)
        item = (await db.execute(query)).scalar_one_or_none()
        if not item:
            return None
        if item.attempts >= get_marketplace_settings().worker_max_attempts:
            item.status = "failed"
            item.error = item.error or "复制重试次数已用完，请稍后重试"
            link = f"/marketplace/works/{item.target_id}/edit?handoff={item.id}" if item.target_kind == "work" else f"/marketplace/series/{item.series_id}/edit"
            notify(db, item.owner_id, "成片复制失败，可在发布页重试", link)
            await db.commit()
            return None
        item.attempts += 1
        item.status, item.lease_token, item.lease_until = "running", uuid.uuid4().hex, now() + timedelta(minutes=15)
        item.error = ""
        await db.commit()
        return item.id, item.lease_token


async def _heartbeat(handoff_id: int, token: str) -> None:
    while True:
        await asyncio.sleep(20)
        async with AsyncSessionLocal() as db:
            result = await db.execute(update(Handoff).where(Handoff.id == handoff_id, Handoff.lease_token == token, Handoff.status == "running").values(lease_until=now() + timedelta(minutes=15)))
            await db.commit()
            if not result.rowcount:
                raise RuntimeError("转存任务租约已丢失")


async def _fail(handoff_id: int, token: str, message: str) -> None:
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(Handoff).where(Handoff.id == handoff_id, Handoff.lease_token == token).with_for_update())).scalar_one_or_none()
        if not item:
            return
        terminal = item.attempts >= get_marketplace_settings().worker_max_attempts or any(
            code in message for code in ("MARKETPLACE_SOURCE_CHANGED", "MARKETPLACE_TARGET_CHANGED", "MARKETPLACE_SOURCE_INCOMPATIBLE", "重新选择分集"))
        item.status = "failed" if terminal else "pending"
        item.error = message[:500]
        item.lease_token, item.lease_until = None, None
        if item.asset_id:
            asset = await db.get(Asset, item.asset_id)
            if asset and asset.status == "processing":
                asset.status, asset.error = "failed", message[:500]
        if terminal:
            link = f"/marketplace/works/{item.target_id}/edit?handoff={item.id}" if item.target_kind == "work" else f"/marketplace/series/{item.series_id}/edit"
            must_reselect = any(code in message for code in ("SOURCE_CHANGED", "TARGET_CHANGED", "SOURCE_INCOMPATIBLE", "重新选择分集"))
            notice = "成片同步中断，请在发布页查看原因并重新选择成片" if must_reselect else "成片同步失败，可在发布页重新同步"
            notify(db, item.owner_id, notice, link)
        await db.commit()


async def _store_cover(locator: str, owner_id: int, folder: str) -> tuple[str, int, str] | None:
    if not locator:
        return None
    suffix = _suffix(locator, "")
    if suffix not in _IMAGE_TYPES:
        return None
    key = f"{folder}/cover-{uuid.uuid4().hex}{suffix}"
    try:
        size = await asyncio.to_thread(place_object, locator, key, _content_type(suffix, "image/png"), IMAGE_LIMIT)
    except Exception:
        logger.info("市场转存封面跳过")
        return None
    return key, size, _content_type(suffix, "image/png")


async def _copy(handoff_id: int, token: str) -> None:
    """复制到 marketplace/ 后探测时长和指纹，再把资产标为 ready。"""
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(Handoff).where(Handoff.id == handoff_id, Handoff.lease_token == token))).scalar_one_or_none()
        if not item:
            return
        if item.source_kind == "drama_episode":
            # Legacy tasks were snapshots of only the final shot; never run them as full episodes.
            await _copy_drama(handoff_id, token)
            return
        snapshot = dict(item.source_snapshot or {})
        owner_id, target_kind, target_id = item.owner_id, item.target_kind, item.target_id
        if item.asset_id:
            asset = await db.get(Asset, item.asset_id)
            if asset and asset.status == "ready":
                await _bind(db, item, asset.id, None)
                item.status, item.error = "ready", ""
                item.lease_token, item.lease_until = None, None
                await db.commit()
                return
            if asset and asset.status == "processing":
                asset.status, asset.error = "failed", "已重新复制"
                await db.commit()
    locator = str(snapshot.get("locator") or "")
    suffix = _suffix(locator, ".mp4")
    content_type = _content_type(suffix, "video/mp4")
    folder = f"marketplace/{'works' if target_kind == 'work' else 'series'}/u{owner_id}/{target_id}"
    dest = f"{folder}/{uuid.uuid4().hex}{suffix}"
    try:
        size = await asyncio.to_thread(place_object, locator, dest, content_type, VIDEO_LIMIT)
    except HTTPException:
        await _fail(handoff_id, token, "文件服务暂未配置或不可用")
        return
    except ValueError as exc:
        await _fail(handoff_id, token, str(exc))
        return
    except Exception:
        logger.exception("marketplace handoff %s copy failed", handoff_id)
        await _fail(handoff_id, token, "复制成片失败，请稍后重试")
        return
    filename = f"{_clip(str(snapshot.get('title') or 'video'), 80) or 'video'}{suffix}"
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(Handoff).where(Handoff.id == handoff_id, Handoff.lease_token == token).with_for_update())).scalar_one_or_none()
        if not item:
            return
        asset = Asset(owner_id=owner_id, kind="video", filename=filename[:255], content_type=content_type, size_bytes=size, object_key=dest, status="processing")
        db.add(asset)
        await db.flush()
        item.asset_id = asset.id
        asset_id = asset.id
        probe = {"id": asset.id, "filename": asset.filename, "object_key": dest, "kind": "video", "size_bytes": size, "content_type": content_type}
        await db.commit()
    from .worker import process_asset
    try:
        result = await process_asset(probe)
    except ValueError as exc:
        await _fail(handoff_id, token, str(exc))
        return
    except Exception:
        logger.exception("marketplace handoff %s probe failed", handoff_id)
        await _fail(handoff_id, token, "成片无法解析，请确认文件完整后重试")
        return
    cover = await _store_cover(str(snapshot.get("cover_locator") or ""), owner_id, folder)
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(Handoff).where(Handoff.id == handoff_id, Handoff.lease_token == token).with_for_update())).scalar_one_or_none()
        asset = await db.get(Asset, asset_id) if item else None
        if not item or not asset:
            return
        asset.fingerprint = str(result.get("fingerprint") or "")
        asset.duration_seconds = result.get("duration_seconds")
        asset.display_width = result.get("display_width")
        asset.display_height = result.get("display_height")
        asset.status, asset.error = "ready", ""
        item.source_fingerprint = asset.fingerprint
        cover_id = None
        if cover:
            cover_asset = Asset(owner_id=owner_id, kind="image", filename=f"cover{Path(cover[0]).suffix}", content_type=cover[2], size_bytes=cover[1], object_key=cover[0], status="ready")
            db.add(cover_asset)
            await db.flush()
            cover_id = cover_asset.id
        await _bind(db, item, asset.id, cover_id)
        item.status, item.error = "ready", ""
        item.lease_token, item.lease_until = None, None
        await db.commit()


async def _bind(db, item: Handoff, asset_id: int, cover_id: int | None, series_cover_id: int | None = None) -> None:
    """把就绪资产挂到草稿上；不改审核状态，也不生成水印。"""
    if item.target_kind == "work":
        work = await db.get(Work, item.target_id)
        if work and work.owner_id == item.owner_id:
            work.asset_id = asset_id
            if cover_id and not work.cover_asset_id:
                work.cover_asset_id = cover_id
        return
    if item.source_kind == "drama_episode":
        episode = await _drama_target(db, item)
        episode.asset_id = asset_id
        if cover_id and not episode.cover_asset_id:
            episode.cover_asset_id = cover_id
        series = await db.get(Series, item.series_id)
        snapshot = item.source_snapshot or {}
        if (series_cover_id and snapshot.get("inherit_series_cover") and not series.cover_asset_id
                and series.version == snapshot.get("series_cover_version")):
            series.cover_asset_id = series_cover_id
        episode.source_snapshot = {**(episode.source_snapshot or {}), "pending_handoff_id": None,
            "last_handoff_id": item.id, "imported_source_version": item.source_version}
        from .drama_publish import ensure_import_rights
        # Set ready only for the authorization helper; the transaction is atomic.
        item.status = "ready"
        await ensure_import_rights(db, episode)
        return
    episode = await db.get(SeriesEpisode, item.target_id)
    if episode and episode.owner_id == item.owner_id:
        episode.asset_id = asset_id
        if cover_id and not episode.cover_asset_id:
            episode.cover_asset_id = cover_id


async def _drama_target(db, item):
    from .models import Series
    series = (await db.execute(select(Series).where(Series.id == item.series_id).with_for_update())).scalar_one_or_none()
    episode = (await db.execute(select(SeriesEpisode).where(SeriesEpisode.id == item.target_id).with_for_update())).scalar_one_or_none()
    snapshot = item.source_snapshot or {}
    if (not series or series.owner_id != item.owner_id or series.deleted_at or series.blocked or not episode
            or episode.series_id != series.id or episode.owner_id != item.owner_id or episode.blocked
            or episode.version != snapshot.get("target_version")
            or episode.asset_id != snapshot.get("original_asset_id")
            or (episode.source_snapshot or {}).get("pending_handoff_id") != item.id):
        fail("MARKETPLACE_TARGET_CHANGED:市场分集已修改、删除或有新的同步任务，请重新选择", 409)
    return episode


async def _validate_drama_source(db, item):
    from .drama_publish import episode_snapshot, source_matches
    snapshot = item.source_snapshot or {}
    if snapshot.get("schema_version") != 2:
        fail("MARKETPLACE_SOURCE_CHANGED:旧导入未包含完整分镜，请重新选择分集并确认更新", 409)
    try:
        current = await episode_snapshot(db, item.owner_id, snapshot["drama_project_id"], item.source_id)
    except HTTPException as exc:
        if exc.status_code == 503:
            raise
        fail("MARKETPLACE_SOURCE_CHANGED:源分集已变化或正在重新生成，请重新选择分集", 409)
    if not source_matches(current, item):
        fail("MARKETPLACE_SOURCE_CHANGED:源分集已更新，请重新选择分集", 409)


async def _phase(handoff_id, token, phase):
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(Handoff).where(Handoff.id == handoff_id,
            Handoff.lease_token == token, Handoff.status == "running").with_for_update())).scalar_one_or_none()
        if not item:
            raise RuntimeError("同步任务租约已丢失")
        item.source_snapshot = {**(item.source_snapshot or {}), "phase": phase}
        await db.commit()


async def _copy_drama(handoff_id, token):
    """完整视频成功写入私有 OSS 且源/目标仍有效，才一次性绑定新资产。"""
    async with AsyncSessionLocal() as db:
        item = (await db.execute(select(Handoff).where(Handoff.id == handoff_id, Handoff.lease_token == token))).scalar_one_or_none()
        if not item:
            return
        await _validate_drama_source(db, item)
        await _drama_target(db, item)
        snapshot, owner_id, target_id = dict(item.source_snapshot), item.owner_id, item.target_id
    folder = f"marketplace/series/u{owner_id}/{target_id}"
    dest = f"{folder}/{uuid.uuid4().hex}.mp4"
    cover_key = f"{folder}/cover-{uuid.uuid4().hex}.png"
    series_cover_key = (cover_key if snapshot.get("project_cover_locator") == snapshot.get("cover_locator")
                        else f"{folder}/series-cover-{uuid.uuid4().hex}.png")
    object_keys = tuple(dict.fromkeys((dest, cover_key, series_cover_key)))
    try:
        await _finish_drama_copy(handoff_id, token, snapshot, owner_id, dest, cover_key, series_cover_key)
    finally:
        from .storage import discard_generated
        try:
            # A commit error can have an uncertain outcome. Only discard objects
            # confirmed unbound, including covers superseded by the author's edit.
            async with AsyncSessionLocal() as db:
                referenced = set((await db.execute(select(Asset.object_key).where(Asset.object_key.in_(object_keys)))).scalars().all())
            for key in object_keys:
                if key not in referenced:
                    await asyncio.to_thread(discard_generated, key)
        except Exception:
            logger.warning("未绑定的市场同步对象清理失败，任务 %s", handoff_id)


async def _finish_drama_copy(handoff_id, token, snapshot, owner_id, dest, cover_key, series_cover_key):
    """独立转存分集与项目封面，仅为未被编辑的新系列回填项目封面。"""
    from .drama_media import prepare_drama_video, prepare_drama_cover
    result = await prepare_drama_video(snapshot, dest, lambda phase: _phase(handoff_id, token, phase))
    cover = None
    if snapshot.get("cover_locator"):
        try:
            cover = {**await prepare_drama_cover(snapshot["cover_locator"], cover_key, snapshot.get("cover_stamp")), "object_key": cover_key}
        except (ValueError, HTTPException, OSError):
            logger.info("漫剧来源封面不可用，保留为待上传封面")
    series_cover = None
    if snapshot.get("inherit_series_cover") and snapshot.get("project_cover_locator"):
        if snapshot["project_cover_locator"] == snapshot.get("cover_locator"):
            series_cover = cover
        else:
            try:
                series_cover = {**await prepare_drama_cover(snapshot["project_cover_locator"], series_cover_key,
                    snapshot.get("project_cover_stamp")), "object_key": series_cover_key}
            except (ValueError, HTTPException, OSError):
                logger.info("漫剧项目封面不可用，保留为待上传系列封面")
    async with AsyncSessionLocal() as db:
        # Queue/update locks series -> episode -> handoff; use the same order.
        candidate = await db.get(Handoff, handoff_id)
        if not candidate:
            return False
        await _drama_target(db, candidate)
        item = (await db.execute(select(Handoff).where(Handoff.id == handoff_id,
            Handoff.lease_token == token, Handoff.status == "running").with_for_update())).scalar_one_or_none()
        if not item:
            return False
        await _validate_drama_source(db, item)
        episode = await _drama_target(db, item)
        asset = Asset(owner_id=owner_id, kind="video", filename=f"{snapshot['title'][:180]}.mp4", object_key=dest,
            status="ready", display_width=result.get("width"), display_height=result.get("height"),
            **{key: result[key] for key in ("size_bytes", "content_type", "fingerprint", "duration_seconds")})
        db.add(asset)
        await db.flush()
        item.asset_id, item.source_fingerprint = asset.id, asset.fingerprint
        cover_id = None
        if cover and not episode.cover_asset_id:
            cover_asset = Asset(owner_id=owner_id, kind="image", filename="cover" + Path(cover["object_key"]).suffix,
                status="ready", **{key: cover[key] for key in ("object_key", "size_bytes", "content_type")})
            db.add(cover_asset)
            await db.flush()
            cover_id = cover_asset.id
        series_cover_id = None
        series = await db.get(Series, item.series_id)
        if (series_cover and not series.cover_asset_id and snapshot.get("inherit_series_cover")
                and series.version == snapshot.get("series_cover_version")):
            if series_cover is cover and cover_id is not None:
                series_cover_id = cover_id
            else:
                series_cover_asset = Asset(owner_id=owner_id, kind="image", filename="series-cover.png", status="ready",
                    **{key: series_cover[key] for key in ("object_key", "size_bytes", "content_type")})
                db.add(series_cover_asset)
                await db.flush()
                series_cover_id = series_cover_asset.id
        await _bind(db, item, asset.id, cover_id, series_cover_id)
        item.status, item.error, item.lease_token, item.lease_until = "ready", "", None, None
        item.source_snapshot = {**item.source_snapshot, "phase": "ready"}
        await db.commit()
        return True


async def run_handoff_once() -> bool:
    """领取一条转存。没有待处理记录时返回 False。"""
    claimed = await _claim()
    if not claimed:
        return False
    handoff_id, token = claimed
    pulse = asyncio.create_task(_heartbeat(handoff_id, token))
    copy = asyncio.create_task(_copy(handoff_id, token))
    try:
        done, _ = await asyncio.wait({pulse, copy}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    except (ValueError, HTTPException) as exc:
        await _fail(handoff_id, token, str(exc.detail) if isinstance(exc, HTTPException) else str(exc))
    except Exception:
        logger.exception("marketplace handoff %s failed", handoff_id)
        await _fail(handoff_id, token, "复制成片失败，请稍后重试")
    finally:
        pulse.cancel()
        copy.cancel()
        await asyncio.gather(pulse, copy, return_exceptions=True)
    return True
