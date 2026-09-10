"""参考音色音频时长：合成源头截断/补足 + 一次性旧数据修复。"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models_drama import DramaAsset, DramaProject
from app.services import storage as storage_svc
from app.services.drama.build_seedance_generate_body import read_asset_voice_audio_url
from app.services.ffmpeg_compose import probe_duration

logger = logging.getLogger(__name__)

# Seedance r2v 单条 reference_audio 下限（API ≥ 1.8s）
SEEDANCE_REFERENCE_AUDIO_MIN_SEC = 1.8
# 合成/落盘目标下限（留余量，避免边界被拒）
VOICE_REFERENCE_MIN_SEC = 2.0
# Seedance r2v 单条 reference_audio 上限（API 30.2s）
SEEDANCE_REFERENCE_AUDIO_MAX_SEC = 30.0
# 合成完成后截断目标（2–15s 即可）
VOICE_REFERENCE_TARGET_SEC = 15.0


# 用 ffmpeg 将音频截断至 max_sec
def trim_audio_to_max(path: Path, max_sec: float, dest: Path | None = None) -> Path:
    settings = get_settings()
    ffmpeg = shutil.which(settings.ffmpeg_path) or shutil.which("ffmpeg")
    if not ffmpeg or not path.exists():
        return path
    out = dest or path.with_name(f"{path.stem}_trim{path.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(path),
            "-t",
            f"{max_sec:.3f}",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        logger.warning(
            "ffmpeg 截断参考音频失败 path=%s stderr=%s",
            path,
            (proc.stderr or "")[:200],
        )
        return path
    if out.exists() and out.stat().st_size > 500:
        return out
    return path


# 用静音补足到至少 min_sec（Seedance 拒收过短 reference_audio）
def pad_audio_to_min(path: Path, min_sec: float, dest: Path | None = None) -> Path:
    settings = get_settings()
    ffmpeg = shutil.which(settings.ffmpeg_path) or shutil.which("ffmpeg")
    if not ffmpeg or not path.exists():
        return path
    duration = probe_duration(path)
    if duration is not None and duration >= min_sec:
        return path
    out = dest or path.with_name(f"{path.stem}_pad{path.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(path),
            "-af",
            f"apad=whole_dur={min_sec:.3f}",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        logger.warning(
            "ffmpeg 补足参考音频失败 path=%s stderr=%s",
            path,
            (proc.stderr or "")[:200],
        )
        return path
    if out.exists() and out.stat().st_size > 500:
        return out
    return path


def _local_duration(url: str) -> float | None:
    local = storage_svc.local_path_from_url(url)
    if local and local.exists():
        return probe_duration(local)
    return None


# 解析本地路径；远程 URL 先下载再探测
async def resolve_voice_audio_local_path(url: str, *, dest: Path) -> Path | None:
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        return await storage_svc.ensure_local_media(raw, dest)
    except Exception:  # noqa: BLE001
        logger.warning("无法落盘参考音频 url=%s", raw[:120])
        return None


# 探测参考音频时长（必要时下载）
async def probe_voice_url_duration(url: str, *, work_dir: Path) -> float | None:
    dest = work_dir / "probe_voice.mp3"
    path = await resolve_voice_audio_local_path(url, dest=dest)
    if path is None or not path.exists():
        return None
    return probe_duration(path)


def is_voice_duration_too_short(
    duration: float | None,
    *,
    min_sec: float = VOICE_REFERENCE_MIN_SEC,
) -> bool:
    if duration is None:
        return False
    return float(duration) + 1e-6 < float(min_sec)


# 合成完成后：过短补足、过长截断，并重新发布
def finalize_voice_reference_url(
    url: str,
    *,
    project_id: int,
    asset_id: int,
    max_sec: float = VOICE_REFERENCE_TARGET_SEC,
    min_sec: float = VOICE_REFERENCE_MIN_SEC,
) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw
    local = storage_svc.local_path_from_url(raw)
    if local is None or not local.exists():
        return raw
    duration = probe_duration(local)
    project_dir = storage_svc.project_dir(project_id)
    current = local
    if duration is not None and duration < min_sec:
        dest = project_dir / f"voice_ref_{asset_id:04d}_pad.mp3"
        padded = pad_audio_to_min(current, min_sec, dest)
        if padded.resolve() != current.resolve():
            current = padded
            duration = probe_duration(current)
            logger.info(
                "参考音频过短已补足 asset_id=%s →≥%.2fs",
                asset_id,
                min_sec,
            )
    if duration is not None and duration > max_sec:
        dest = project_dir / f"voice_ref_{asset_id:04d}.mp3"
        trimmed = trim_audio_to_max(current, max_sec, dest)
        if trimmed.resolve() != current.resolve():
            current = trimmed
    if current.resolve() == local.resolve():
        return raw
    published = storage_svc.publish_local(current, sync=True)
    return published or storage_svc.rel_static_url(current)


# 更新 params 内 voiceAudio / canvas.voiceAudio 的 url
def patch_params_voice_url(params: dict[str, Any], url: str) -> dict[str, Any]:
    next_params = dict(params)
    binding = next_params.get("voiceAudio")
    if isinstance(binding, dict):
        next_params["voiceAudio"] = {**binding, "url": url}
    canvas = next_params.get("canvas")
    if isinstance(canvas, dict):
        voice_binding = canvas.get("voiceAudio")
        if isinstance(voice_binding, dict):
            next_params["canvas"] = {**canvas, "voiceAudio": {**voice_binding, "url": url}}
    return next_params


def _trim_and_publish_url(
    url: str,
    *,
    project_id: int,
    asset_id: int,
    max_sec: float = VOICE_REFERENCE_TARGET_SEC,
) -> tuple[str, bool]:
    """返回 (新 URL, 是否变更)。"""
    new_url = finalize_voice_reference_url(
        url,
        project_id=project_id,
        asset_id=asset_id,
        max_sec=max_sec,
    )
    return new_url, new_url != url


# 一次性修复：voice 资产、角色绑定、旁白绑定中的超长参考音
async def backfill_long_voice_references(
    db: AsyncSession,
    *,
    dry_run: bool = False,
    limit: int = 500,
    max_sec: float = VOICE_REFERENCE_TARGET_SEC,
) -> dict[str, Any]:
    stats = {
        "ok": True,
        "dry_run": dry_run,
        "voice_assets_checked": 0,
        "voice_assets_trimmed": 0,
        "characters_updated": 0,
        "projects_updated": 0,
        "skipped_remote_only": 0,
        "errors": [],
    }

    voice_rows = (
        await db.execute(
            select(DramaAsset)
            .where(DramaAsset.type == "voice")
            .order_by(DramaAsset.id.asc())
            .limit(limit)
        )
    ).scalars().all()

    url_by_voice_id: dict[int, str] = {}

    for asset in voice_rows:
        stats["voice_assets_checked"] += 1
        url = (asset.url or "").strip()
        if not url:
            continue
        duration = _local_duration(url)
        if duration is not None and duration <= max_sec:
            url_by_voice_id[asset.id] = url
            continue
        if storage_svc.local_path_from_url(url) is None:
            stats["skipped_remote_only"] += 1
            url_by_voice_id[asset.id] = url
            continue
        if dry_run:
            stats["voice_assets_trimmed"] += 1
            url_by_voice_id[asset.id] = url
            continue
        try:
            new_url, changed = _trim_and_publish_url(
                url,
                project_id=asset.project_id,
                asset_id=asset.id,
                max_sec=max_sec,
            )
            if changed:
                asset.url = new_url
                asset.cover = new_url
                params = dict(asset.params or {}) if isinstance(asset.params, dict) else {}
                params["referenceAudioTrimmed"] = True
                asset.params = params
                stats["voice_assets_trimmed"] += 1
            url_by_voice_id[asset.id] = new_url if changed else url
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append(f"voice#{asset.id}: {exc}")
            url_by_voice_id[asset.id] = url

    char_rows = (
        await db.execute(
            select(DramaAsset)
            .where(DramaAsset.type == "character")
            .order_by(DramaAsset.id.asc())
            .limit(limit)
        )
    ).scalars().all()

    for asset in char_rows:
        params = dict(asset.params or {}) if isinstance(asset.params, dict) else {}
        binding = params.get("voiceAudio")
        if not isinstance(binding, dict):
            continue
        url = read_asset_voice_audio_url(params)
        if not url:
            continue
        source_id = binding.get("sourceAssetId")
        if isinstance(source_id, int) and source_id in url_by_voice_id:
            new_url = url_by_voice_id[source_id]
            if new_url != url:
                if not dry_run:
                    asset.params = patch_params_voice_url(params, new_url)
                stats["characters_updated"] += 1
            continue
        duration = _local_duration(url)
        if duration is not None and duration <= max_sec:
            continue
        if storage_svc.local_path_from_url(url) is None:
            stats["skipped_remote_only"] += 1
            continue
        if dry_run:
            stats["characters_updated"] += 1
            continue
        try:
            new_url, changed = _trim_and_publish_url(
                url,
                project_id=asset.project_id,
                asset_id=asset.id,
                max_sec=max_sec,
            )
            if changed:
                asset.params = patch_params_voice_url(params, new_url)
                stats["characters_updated"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append(f"character#{asset.id}: {exc}")

    project_rows = (
        await db.execute(select(DramaProject).order_by(DramaProject.id.asc()).limit(limit))
    ).scalars().all()
    for project in project_rows:
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        narrator = params.get("narrationVoiceAudio")
        if not isinstance(narrator, dict):
            continue
        url = str(narrator.get("url") or narrator.get("previewUrl") or "").strip()
        if not url:
            continue
        source_id = narrator.get("sourceAssetId")
        if isinstance(source_id, int) and source_id in url_by_voice_id:
            new_url = url_by_voice_id[source_id]
            if new_url != url:
                if not dry_run:
                    params["narrationVoiceAudio"] = {**narrator, "url": new_url}
                    project.params = params
                stats["projects_updated"] += 1
            continue
        duration = _local_duration(url)
        if duration is not None and duration <= max_sec:
            continue
        if storage_svc.local_path_from_url(url) is None:
            stats["skipped_remote_only"] += 1
            continue
        if dry_run:
            stats["projects_updated"] += 1
            continue
        try:
            new_url, changed = _trim_and_publish_url(
                url,
                project_id=project.id,
                asset_id=project.id,
                max_sec=max_sec,
            )
            if changed:
                params["narrationVoiceAudio"] = {**narrator, "url": new_url}
                project.params = params
                stats["projects_updated"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append(f"project#{project.id}: {exc}")

    if not dry_run:
        await db.commit()

    if stats["errors"]:
        stats["ok"] = False
    return stats
