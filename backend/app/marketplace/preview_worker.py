"""收费短试看：优先无损裁剪，结果校验通过后才写入私有 OSS。"""
import asyncio
from contextlib import contextmanager
from datetime import timedelta
import json
import logging
import math
from pathlib import Path
import tempfile
import time
import uuid

from sqlalchemy import and_, or_, select, update

from app.config import get_settings
from app.database import AsyncSessionLocal
from . import storage
from .config import get_marketplace_settings
from .models import Asset, EpisodePreview, Publication, Series, SeriesEpisode, Work, WorkPreview
from .previews import (
    CLIP_EPISODE_PREFIX, CLIP_WORK_PREFIX, PREVIEW_LEASE_PREFIX, episode_is_free, is_preview_key,
    preview_duration, requires_preview, series_submission_ready, work_submission_ready,
)
from .service import event, now, notify

logger = logging.getLogger(__name__)
FORMATS = "mov,matroska,webm,mp4"


class PreviewProcessingError(ValueError):
    """对外只报告处理阶段；底层异常留在服务端日志中。"""


@contextmanager
def _stage(name, snapshot):
    started = time.monotonic()
    try:
        yield
    except Exception as exc:
        logger.exception("短试看%s失败 content=%s asset=%s", name,
                         snapshot.get("content_id"), snapshot.get("asset_id"))
        raise PreviewProcessingError(f"短试看{name}失败，请重试；持续失败请联系管理员") from exc
    finally:
        logger.info("短试看阶段=%s content=%s asset=%s elapsed=%.3fs", name,
                    snapshot.get("content_id"), snapshot.get("asset_id"), time.monotonic() - started)


_FPS_FLAG_BY_BINARY: dict[tuple[str, int], str] = {}


async def _supports_fps_mode(ffmpeg_path: str) -> bool:
    """Probe the actual binary: -fps_mode exists only since FFmpeg 5.1."""
    from .worker import command
    try:
        await command(ffmpeg_path, "-hide_banner", "-v", "error",
                      "-f", "lavfi", "-i", "color=size=16x16:duration=0.1:rate=1",
                      "-frames:v", "1", "-fps_mode", "passthrough", "-f", "null", "-", timeout=30)
        return True
    except Exception:
        # 探测失败（旧版不支持或二进制异常）时退回所有版本都接受的 -vsync；
        # 若 ffmpeg 本身损坏，真正的转码仍会报出原始错误。
        return False


async def _fps_passthrough_args(ffmpeg_path: str) -> list[str]:
    # 以 (路径, mtime) 为键缓存探测结果：替换同路径二进制后重新探测。
    try:
        key = (ffmpeg_path, Path(ffmpeg_path).stat().st_mtime_ns)
    except OSError:
        key = (ffmpeg_path, -1)
    flag = _FPS_FLAG_BY_BINARY.get(key)
    if flag is None:
        flag = "-fps_mode" if await _supports_fps_mode(ffmpeg_path) else "-vsync"
        if key[1] != -1:
            _FPS_FLAG_BY_BINARY[key] = flag
    return [flag, "passthrough"]


async def _probe(path):
    from .worker import command
    return json.loads(await command(get_settings().ffprobe_path, "-v", "error",
        "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS,
        "-show_format", "-show_streams", "-of", "json", str(path), timeout=60))


def _video(probe):
    return next((stream for stream in probe.get("streams", [])
                 if stream.get("codec_type") == "video"), None)


def _duration(probe):
    # 同时检查容器和流的时长，避免 AAC 尾帧或 B 帧造成实际超长。
    values = [probe.get("format", {}).get("duration")]
    values.extend(stream.get("duration") for stream in probe.get("streams", []))
    durations = [float(value) for value in values if value not in (None, "N/A")]
    if not durations or any(not math.isfinite(value) or value <= 0 for value in durations):
        raise ValueError("视频时长无效")
    return max(durations)


def _compatible_clip(probe, source, maximum):
    try:
        video, original = _video(probe), _video(source)
        if not video or not original or not 0 < _duration(probe) <= maximum:
            return False
        width, height = int(original["width"]), int(original["height"])
        rotation = original.get("tags", {}).get("rotate", 0)
        for side in original.get("side_data_list", []):
            rotation = side.get("rotation", rotation)
        if int(float(rotation)) % 180:
            width, height = height, width
        dimensions = {(int(original["width"]), int(original["height"])),
                      ((width + 1) // 2 * 2, (height + 1) // 2 * 2)}
        audio = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"]
        source_audio = any(stream.get("codec_type") == "audio" for stream in source.get("streams", []))
        return bool(video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p"
                    and (int(video["width"]), int(video["height"])) in dimensions
                    and (not source_audio or audio) and all(stream.get("codec_name") == "aac" for stream in audio))
    except (ValueError, TypeError, KeyError):
        return False


async def render_preview(snapshot):
    """免费内容不调用此函数；每次输出独立对象，不覆盖已购买的发布版本。"""
    from .worker import cache_root, command
    upstream = get_settings()
    with tempfile.TemporaryDirectory(prefix="job-", dir=cache_root()) as directory:
        root = Path(directory)
        source = root / ("source" + Path(snapshot["filename"]).suffix.lower())
        with _stage("下载", snapshot):
            await asyncio.to_thread(storage.download, snapshot["source_key"], source)
            if source.stat().st_size != snapshot["size_bytes"]:
                raise ValueError("原片大小不一致")
        with _stage("源文件校验", snapshot):
            probe = await _probe(source)
            video = _video(probe)
            if not video or not 0 < int(video.get("width", 0)) * int(video.get("height", 0)) <= 50_000_000:
                raise ValueError("无效的视频尺寸")
            duration = _duration(probe)
            if duration > get_marketplace_settings().max_duration_seconds:
                raise ValueError("视频超过时长限制")
            maximum = preview_duration(duration)
            # 留出音频尾帧余量，最终仍以 FFprobe 的实际结果为准。
            target = maximum - min(0.15, maximum * 0.1)
        output = root / "preview.mp4"
        args = (upstream.ffmpeg_path, "-y", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", FORMATS, "-i", str(source), "-t", str(target),
                "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn")
        with _stage("截取", snapshot):
            copied = False
            audios = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"]
            if video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p" and all(
                    audio.get("codec_name") == "aac" for audio in audios):
                try:
                    await command(*args, "-c", "copy", "-avoid_negative_ts", "make_zero",
                                  "-movflags", "+faststart", str(output), timeout=120)
                    copied = _compatible_clip(await _probe(output), probe, maximum)
                except (ValueError, TimeoutError, json.JSONDecodeError):
                    logger.info("无损裁剪无法满足播放要求，改为短片段编码 content=%s", snapshot.get("content_id"))
            if not copied:
                await command(*args, "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-threads", "2",
                    *(await _fps_passthrough_args(upstream.ffmpeg_path)),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(output), timeout=600)
        with _stage("输出校验", snapshot):
            if not output.is_file() or not output.stat().st_size or not _compatible_clip(await _probe(output), probe, maximum):
                raise ValueError("试看时长、画幅或编码不符合要求")
        prefix = CLIP_EPISODE_PREFIX if snapshot.get("content_type") == "series_episode" else CLIP_WORK_PREFIX
        content_id = snapshot.get("content_id", snapshot.get("work_id"))
        key = f"{prefix}{content_id}/{snapshot['asset_id']}/{uuid.uuid4().hex}.mp4"
        with _stage("上传", snapshot):
            await asyncio.to_thread(storage.upload, key, output, "video/mp4")
        return key


def _eligible(model):
    return or_(model.status == "pending", and_(model.status == "running",
               or_(model.lease_until.is_(None), model.lease_until < now())))


def _cancel(job):
    job.status, job.lease_token, job.lease_until = "cancelled", None, None


def _asset_matches(asset, owner_id):
    return bool(asset and asset.owner_id == owner_id and asset.kind == "video" and asset.status == "ready")


async def _render_with_lease(model, job_id, token, snapshot):
    async def heartbeat():
        while True:
            await asyncio.sleep(20)
            async with AsyncSessionLocal() as db:
                changed = await db.execute(update(model).where(model.id == job_id, model.lease_token == token,
                    model.status == "running").values(lease_until=now() + timedelta(minutes=2)))
                await db.commit()
                if not changed.rowcount:
                    raise RuntimeError("试看任务租约失效")
    pulse = asyncio.create_task(heartbeat())
    processing = asyncio.create_task(render_preview(snapshot))
    try:
        done, _ = await asyncio.wait((pulse, processing), return_when=asyncio.FIRST_COMPLETED)
        if pulse in done:
            await pulse
        key = await processing
        if not is_preview_key(key, episode=model is EpisodePreview):
            raise ValueError("试看策略版本不匹配")
        return key, ""
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("短试看处理失败 task=%s/%s", model.__name__, job_id)
        return None, str(exc) if isinstance(exc, PreviewProcessingError) else "短试看处理失败，可重试；持续失败请联系管理员"
    finally:
        pulse.cancel()
        processing.cancel()
        await asyncio.gather(pulse, processing, return_exceptions=True)


async def _publications(db, kind, content_id, version, asset_id):
    return list((await db.execute(select(Publication).where(Publication.content_type == kind,
        Publication.content_id == content_id, Publication.version == version,
        Publication.asset_id == asset_id).with_for_update())).scalars().all())


def _record_result(job, publications, key, error):
    terminal = job.attempts >= get_marketplace_settings().worker_max_attempts
    job.status = "done" if key else ("failed" if terminal else "pending")
    job.object_key, job.error = key, error
    # 失败令牌只标识处理策略，status=failed 不可领取也不可续租；重启不无限重试。
    job.lease_token = (job.lease_token if (job.lease_token or "").startswith(PREVIEW_LEASE_PREFIX)
                       else PREVIEW_LEASE_PREFIX + uuid.uuid4().hex) if job.status == "failed" else None
    job.lease_until = None
    for publication in publications:
        if publication.audit_status == "approved":
            continue  # 已批准发布快照及旧买家的播放文件保持不变。
        publication.preview_key, publication.preview_status, publication.preview_error = key, job.status, error
    return terminal


async def run_preview_once():
    async with AsyncSessionLocal() as db:
        candidate = (await db.execute(select(WorkPreview.id, WorkPreview.work_id).where(_eligible(WorkPreview))
                                     .order_by(WorkPreview.id).limit(1))).first()
        if not candidate:
            return False
        # 与编辑/提交接口一致：先内容、后任务。候选读取不持有行锁。
        work = await db.get(Work, candidate.work_id, with_for_update=True)
        job = (await db.execute(select(WorkPreview).where(WorkPreview.id == candidate.id,
            _eligible(WorkPreview)).with_for_update(skip_locked=True))).scalar_one_or_none()
        if not job:
            return False
        asset = await db.get(Asset, job.asset_id)
        if not work or work.deleted_at or work.blocked or work.version != job.version or work.asset_id != job.asset_id or not requires_preview(work.sale_type) or not _asset_matches(asset, work.owner_id):
            _cancel(job)
            await db.commit()
            return True
        publications = await _publications(db, "work", work.id, job.version, job.asset_id)
        if job.attempts >= get_marketplace_settings().worker_max_attempts:
            _record_result(job, publications, None, "短试看重试次数已用完，请手动重试")
            if work.audit_status == "processing":
                work.audit_status, work.reason = "preview_failed", job.error
            await db.commit()
            return True
        token = PREVIEW_LEASE_PREFIX + uuid.uuid4().hex
        job.status, job.lease_token, job.lease_until = "running", token, now() + timedelta(minutes=2)
        job.attempts += 1
        snapshot = dict(content_type="work", content_id=work.id, work_id=work.id, owner_id=work.owner_id,
            asset_id=asset.id, version=job.version, filename=asset.filename, source_key=asset.object_key,
            size_bytes=asset.size_bytes)
        job_id = job.id
        await db.commit()
    key, error = await _render_with_lease(WorkPreview, job_id, token, snapshot)
    started = time.monotonic()
    try:
        async with AsyncSessionLocal() as db:
            work = await db.get(Work, snapshot["content_id"], with_for_update=True)
            job = (await db.execute(select(WorkPreview).where(WorkPreview.id == job_id,
                WorkPreview.status == "running", WorkPreview.lease_token == token).with_for_update())).scalar_one_or_none()
            if not job:
                return True
            asset = await db.get(Asset, snapshot["asset_id"])
            if not work or work.deleted_at or work.blocked or work.owner_id != snapshot["owner_id"] or work.version != snapshot["version"] or work.asset_id != snapshot["asset_id"] or job.version != snapshot["version"] or job.asset_id != snapshot["asset_id"] or not requires_preview(work.sale_type) or not _asset_matches(asset, work.owner_id):
                _cancel(job)
            else:
                publications = await _publications(db, "work", work.id, job.version, job.asset_id)
                terminal = _record_result(job, publications, key, error)
                if work.audit_status == "processing":
                    if key and await work_submission_ready(db, work):
                        work.audit_status, work.reason = "pending", ""
                        for publication in publications:
                            if publication.audit_status != "approved":
                                publication.audit_status = "pending"
                        event(db, work.owner_id, "work", work.id, "preview_ready", version=work.version)
                        notify(db, work.owner_id, f"作品《{work.title}》短试看已生成，已进入待审核", f"/marketplace/works/{work.id}/manage")
                    elif key:
                        work.audit_status, work.reason = "draft", "发布资料已变化，请检查后重新提交审核"
                    elif terminal:
                        work.audit_status, work.reason = "preview_failed", error
                        notify(db, work.owner_id, f"作品《{work.title}》短试看生成失败，可重试", f"/marketplace/works/{work.id}/manage")
                # 文件就绪不改变 listed，作者主动下架后不会自动恢复销售。
            await db.commit()
    except Exception:
        logger.exception("短试看状态回写失败 work=%s task=%s", snapshot["content_id"], job_id)
        raise
    finally:
        logger.info("短试看阶段=状态回写 work=%s elapsed=%.3fs", snapshot["content_id"], time.monotonic() - started)
    return True


async def _advance_series_review(db, series_id):
    series = await db.get(Series, series_id, with_for_update=True)
    if not series or series.audit_status != "processing" or series.deleted_at or series.blocked:
        return
    episodes = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == series.id)
                                     .order_by(SeriesEpisode.id).with_for_update())).scalars().all())
    failed, ready = False, bool(episodes)
    for episode in episodes:
        if episode_is_free(series, episode):
            episode.preview_status, episode.preview_key = "none", None
            continue
        preview = (await db.execute(select(EpisodePreview).where(EpisodePreview.episode_id == episode.id,
            EpisodePreview.asset_id == episode.asset_id, EpisodePreview.version == episode.version))).scalar_one_or_none()
        failed = failed or bool(preview and preview.status == "failed")
        ready = ready and bool(preview and preview.status == "done" and is_preview_key(preview.object_key, episode=True))
    if not await series_submission_ready(db, series):
        series.audit_status, series.reason = "draft", "发布资料已变化，请检查后重新提交审核"
    elif failed:
        series.audit_status, series.reason = "preview_failed", "短试看生成失败，可重试"
        notify(db, series.owner_id, f"短剧《{series.title}》短试看生成失败，可在发布页重试", f"/marketplace/series/{series.id}/edit")
    elif ready:
        series.audit_status, series.reason = "pending", ""
        notify(db, series.owner_id, f"短剧《{series.title}》已进入待审核", f"/marketplace/series/{series.id}/edit")


async def release_finished_series_once():
    async with AsyncSessionLocal() as db:
        series_ids = list((await db.execute(select(Series.id).where(Series.audit_status == "processing")
                                            .order_by(Series.id))).scalars().all())
    # 每个系列单独提交，不持有一串父行锁等待其他系列，避免与启动协调交叉锁定。
    for series_id in series_ids:
        async with AsyncSessionLocal() as db:
            await _advance_series_review(db, series_id)
            await db.commit()
    return bool(series_ids)


async def run_episode_preview_once():
    async with AsyncSessionLocal() as db:
        candidate = (await db.execute(select(EpisodePreview.id, EpisodePreview.episode_id, SeriesEpisode.series_id)
            .outerjoin(SeriesEpisode, SeriesEpisode.id == EpisodePreview.episode_id).where(_eligible(EpisodePreview))
            .order_by(EpisodePreview.id).limit(1))).first()
        if not candidate:
            return False
        # 所有路径统一锁序 Series -> Episode -> Preview，避免与提交接口死锁。
        series = await db.get(Series, candidate.series_id, with_for_update=True) if candidate.series_id else None
        episode = await db.get(SeriesEpisode, candidate.episode_id, with_for_update=True)
        job = (await db.execute(select(EpisodePreview).where(EpisodePreview.id == candidate.id,
            _eligible(EpisodePreview)).with_for_update(skip_locked=True))).scalar_one_or_none()
        if not job:
            return False
        asset = await db.get(Asset, job.asset_id)
        if not series or series.deleted_at or series.blocked or not episode or episode.blocked or episode.owner_id != series.owner_id or episode.version != job.version or episode.asset_id != job.asset_id or episode_is_free(series, episode) or not _asset_matches(asset, episode.owner_id):
            _cancel(job)
            if series and episode and episode_is_free(series, episode):
                episode.preview_status, episode.preview_key = "none", None
            await db.commit()
            return True
        publications = await _publications(db, "series_episode", episode.id, job.version, job.asset_id)
        if job.attempts >= get_marketplace_settings().worker_max_attempts:
            _record_result(job, publications, None, "短试看重试次数已用完，请手动重试")
            episode.preview_status = "failed"
            await _advance_series_review(db, series.id)
            await db.commit()
            return True
        token = PREVIEW_LEASE_PREFIX + uuid.uuid4().hex
        job.status, job.lease_token, job.lease_until = "running", token, now() + timedelta(minutes=2)
        job.attempts += 1
        episode.preview_status, episode.preview_attempts = "running", job.attempts
        snapshot = dict(content_type="series_episode", content_id=episode.id, series_id=series.id,
            owner_id=episode.owner_id, asset_id=asset.id, version=job.version, series_version=series.version,
            filename=asset.filename, source_key=asset.object_key, size_bytes=asset.size_bytes)
        job_id = job.id
        await db.commit()
    key, error = await _render_with_lease(EpisodePreview, job_id, token, snapshot)
    started = time.monotonic()
    try:
        async with AsyncSessionLocal() as db:
            series = await db.get(Series, snapshot["series_id"], with_for_update=True)
            episode = await db.get(SeriesEpisode, snapshot["content_id"], with_for_update=True)
            job = (await db.execute(select(EpisodePreview).where(EpisodePreview.id == job_id,
                EpisodePreview.status == "running", EpisodePreview.lease_token == token).with_for_update())).scalar_one_or_none()
            if not job:
                return True
            asset = await db.get(Asset, snapshot["asset_id"])
            if not series or series.deleted_at or series.blocked or series.version != snapshot["series_version"] or not episode or episode.series_id != series.id or episode.blocked or episode.owner_id != snapshot["owner_id"] or episode.version != snapshot["version"] or episode.asset_id != snapshot["asset_id"] or job.version != snapshot["version"] or job.asset_id != snapshot["asset_id"] or episode_is_free(series, episode) or not _asset_matches(asset, episode.owner_id):
                _cancel(job)
                if series and episode and episode_is_free(series, episode):
                    episode.preview_status, episode.preview_key = "none", None
            else:
                publications = await _publications(db, "series_episode", episode.id, job.version, job.asset_id)
                _record_result(job, publications, key, error)
                episode.preview_key, episode.preview_status = key, job.status
                await _advance_series_review(db, series.id)
            await db.commit()
    except Exception:
        logger.exception("短试看状态回写失败 episode=%s task=%s", snapshot["content_id"], job_id)
        raise
    finally:
        logger.info("短试看阶段=状态回写 episode=%s elapsed=%.3fs", snapshot["content_id"], time.monotonic() - started)
    return True
