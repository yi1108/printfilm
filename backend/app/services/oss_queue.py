"""Async OSS upload queue: enqueue after local save, then backfill DB URLs."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

import redis
from sqlalchemy import String, cast, or_, select, update

from app.config import get_settings
from app.services import oss as oss_svc
from app.services import storage

logger = logging.getLogger(__name__)

_ENQUEUE_KEY = "ai_movie:oss:enqueued:{digest}"
_ENQUEUE_TTL = 7200

# JSON params 内可能存本地媒体 URL 的字段
_ASSET_PARAM_URL_KEYS = ("voiceAudio", "cover", "url", "image", "video")


def _redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def _digest(local_url: str) -> str:
    return hashlib.sha1(local_url.encode("utf-8")).hexdigest()[:24]


def enqueue_oss_upload(local_url: str) -> bool:
    """Queue OSS upload for a /static URL. Returns True if newly enqueued."""
    url = (local_url or "").strip()
    if not url or not storage.is_local_static_url(url):
        return False
    if not oss_svc.oss_enabled():
        return False

    settings = get_settings()
    key = _ENQUEUE_KEY.format(digest=_digest(url))
    try:
        r = _redis()
        if not r.set(key, "1", nx=True, ex=_ENQUEUE_TTL):
            return False
    except Exception:  # noqa: BLE001
        logger.warning("oss enqueue redis unavailable, caller should sync-upload", exc_info=True)
        raise

    asyncio.create_task(_upload_local_url_background(url))
    logger.info("oss upload enqueued %s → background", url)
    return True


async def _upload_local_url_background(local_url: str) -> None:
    """Upload one local static asset and backfill all DB references."""
    try:
        oss_url = await asyncio.to_thread(upload_local_url_sync, local_url)
        if not oss_url:
            clear_enqueue_marker(local_url)
            return
        await backfill_media_url(local_url, oss_url)
        clear_enqueue_marker(local_url)
    except Exception:  # noqa: BLE001
        clear_enqueue_marker(local_url)
        logger.exception("background oss upload failed url=%s", local_url)


def clear_enqueue_marker(local_url: str) -> None:
    try:
        _redis().delete(_ENQUEUE_KEY.format(digest=_digest(local_url)))
    except Exception:  # noqa: BLE001
        pass


# 从资产 params 递归收集本地 /static URL
def _collect_local_urls_from_params(params: Any, out: set[str]) -> None:
    if isinstance(params, dict):
        for key, value in params.items():
            if key in _ASSET_PARAM_URL_KEYS and isinstance(value, str):
                raw = value.strip()
                if storage.is_local_static_url(raw):
                    out.add(raw)
            else:
                _collect_local_urls_from_params(value, out)
    elif isinstance(params, list):
        for item in params:
            _collect_local_urls_from_params(item, out)


# 将 params 内 old→new 的本地 URL 替换；有改动返回 True
def _rewrite_local_urls_in_params(params: Any, old: str, new: str) -> bool:
    changed = False
    if isinstance(params, dict):
        for key, value in list(params.items()):
            if isinstance(value, str) and value.strip() == old:
                params[key] = new
                changed = True
            elif isinstance(value, (dict, list)):
                if _rewrite_local_urls_in_params(value, old, new):
                    changed = True
    elif isinstance(params, list):
        for index, item in enumerate(params):
            if isinstance(item, str) and item.strip() == old:
                params[index] = new
                changed = True
            elif isinstance(item, (dict, list)):
                if _rewrite_local_urls_in_params(item, old, new):
                    changed = True
    return changed


async def backfill_media_url(old_url: str, new_url: str) -> int:
    """Replace exact local URL references with OSS URL across media tables."""
    old = (old_url or "").strip()
    new = (new_url or "").strip()
    if not old or not new or old == new:
        return 0

    from app.database import AsyncSessionLocal
    from app.models import Project, Shot, Template, Work
    from app.models_drama import DramaAsset, DramaEpisodeFragment

    targets: list[tuple[type, list[str]]] = [
        (Shot, ["image_url", "video_url", "audio_url"]),
        (Project, ["cover_url", "final_video_url", "ref_image_url"]),
        (Template, ["preview_cover"]),
        (Work, ["cover_url", "video_url"]),
        (DramaAsset, ["cover", "url"]),
        (DramaEpisodeFragment, ["cover", "video"]),
    ]
    changed = 0
    async with AsyncSessionLocal() as db:
        for model, fields in targets:
            for field in fields:
                col = getattr(model, field)
                result = await db.execute(
                    update(model).where(col == old).values(**{field: new})
                )
                changed += int(result.rowcount or 0)

        # 仅当 params JSON 文本含该 URL 时回写（音色 voiceAudio 等）
        assets = (
            await db.execute(
                select(DramaAsset).where(
                    DramaAsset.params.is_not(None),
                    cast(DramaAsset.params, String).like(f"%{old}%"),
                )
            )
        ).scalars().all()
        for asset in assets:
            params = asset.params
            if not isinstance(params, dict):
                continue
            rewritten = dict(params)
            if _rewrite_local_urls_in_params(rewritten, old, new):
                asset.params = rewritten
                changed += 1
        await db.commit()
    if changed:
        logger.info("oss backfill %s row(s): %s → %s", changed, old, new)
    return changed


def collect_pending_column_targets() -> list[tuple[type, list[str]]]:
    """补传扫描列：科普只扫成片，不含分镜图/配音/镜头视频。"""
    from app.models import Project, Template, Work
    from app.models_drama import DramaAsset, DramaEpisodeFragment

    return [
        (Project, ["final_video_url"]),
        (Template, ["preview_cover"]),
        (Work, ["cover_url", "video_url"]),
        (DramaAsset, ["cover", "url"]),
        (DramaEpisodeFragment, ["cover", "video"]),
    ]


async def collect_pending_local_media_urls(*, limit: int = 2000) -> list[str]:
    """扫描库中仍指向本地 /static 的媒体 URL（含漫剧）。"""
    from app.database import AsyncSessionLocal
    from app.models_drama import DramaAsset

    found: set[str] = set()
    async with AsyncSessionLocal() as db:
        column_targets = collect_pending_column_targets()
        for model, fields in column_targets:
            clauses = []
            for field in fields:
                col = getattr(model, field)
                clauses.append(col.like("/static/%"))
                clauses.append(col.like("%/static/%"))
            rows = (await db.execute(select(model).where(or_(*clauses)))).scalars().all()
            for row in rows:
                for field in fields:
                    raw = (getattr(row, field) or "").strip()
                    if storage.is_local_static_url(raw):
                        found.add(raw)
                        if len(found) >= limit:
                            return sorted(found)

        assets = (
            await db.execute(
                select(DramaAsset).where(DramaAsset.params.is_not(None))
            )
        ).scalars().all()
        for asset in assets:
            _collect_local_urls_from_params(asset.params, found)
            if len(found) >= limit:
                break
    return sorted(found)[:limit]


def upload_local_url_sync(local_url: str) -> str | None:
    """同步上传单个本地 URL；成功返回 OSS https，失败返回 None。"""
    url = (local_url or "").strip()
    if not url or not storage.is_local_static_url(url):
        return None
    if not oss_svc.oss_enabled():
        return None
    path = storage.local_path_from_url(url)
    if not path or not path.is_file():
        logger.warning("oss backfill skip missing file %s", url)
        return None
    oss_url = storage.upload_local_sync(path)
    # 成功须为公网 http(s)；勿用 is_local_static_url（本地副本仍在会误判 OSS URL）
    if not oss_url or not (oss_url.startswith("http://") or oss_url.startswith("https://")):
        raise RuntimeError(f"upload returned local URL for {url}")
    return oss_url


async def backfill_pending_local_media(*, limit: int = 500, dry_run: bool = False) -> dict[str, Any]:
    """把库里仍是 /static 的媒体补传到 OSS 并回写 URL。"""
    pending = await collect_pending_local_media_urls(limit=limit)
    # uploaded / failed / skipped / changed_rows 统计
    uploaded = 0
    failed = 0
    skipped = 0
    changed_rows = 0
    errors: list[str] = []

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "pending": len(pending),
            "urls": pending[:50],
        }

    if not oss_svc.oss_enabled():
        return {"ok": False, "error": "OSS disabled", "pending": len(pending)}

    for local_url in pending:
        try:
            oss_url = upload_local_url_sync(local_url)
            if not oss_url:
                skipped += 1
                continue
            changed_rows += await backfill_media_url(local_url, oss_url)
            clear_enqueue_marker(local_url)
            uploaded += 1
            logger.info("oss pending backfill ok %s → %s", local_url, oss_url)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"{local_url}: {exc}"[:240])
            logger.exception("oss pending backfill failed %s", local_url)

    return {
        "ok": failed == 0,
        "pending": len(pending),
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "changed_rows": changed_rows,
        "errors": errors[:20],
    }
