"""沿用市场 Worker，为 App 生成保持源分辨率的私有 HLS 派生物。"""
import asyncio
from datetime import timedelta
import json
import logging
from pathlib import Path
import tempfile
import uuid

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.database import AsyncSessionLocal
from . import storage
from .app_media_models import AppMedia
from .config import get_marketplace_settings, video_duration_limit
from .models import Asset, Series, SeriesEpisode, Work
from .service import now

logger = logging.getLogger(__name__)


async def media_for(db, kind, content_id, version, variant):
    """派生物始终绑定内容版本和用途，旧任务不能覆盖新版本。"""
    return await db.scalar(select(AppMedia).where(AppMedia.content_type == kind,
        AppMedia.content_id == content_id, AppMedia.version == version, AppMedia.variant == variant))


async def enqueue(db, kind, item, asset, variant="full", source_key=None):
    """请求和 Worker 可重复建任务，唯一约束保证只有一个任务。"""
    await db.execute(insert(AppMedia).values(content_type=kind, content_id=item.id, version=item.version,
        variant=variant, asset_id=asset.id, source_key=source_key or asset.object_key).on_conflict_do_nothing(
        index_elements=["content_type", "content_id", "version", "variant"]))
    return await media_for(db, kind, item.id, item.version, variant)


async def discover(db):
    """每轮只为公开版本发现少量缺失任务，不迁移或修改原发布记录。"""
    from .app_access import work_query, series_query
    from .previews import episode_is_free, episode_preview_for, preview_for
    work_full = select(AppMedia.id).where(
        AppMedia.content_type == "work", AppMedia.content_id == Work.id,
        AppMedia.version == Work.version, AppMedia.variant == "full").exists()
    work_preview = select(AppMedia.id).where(
        AppMedia.content_type == "work", AppMedia.content_id == Work.id,
        AppMedia.version == Work.version, AppMedia.variant == "preview").exists()
    works = list((await db.scalars(work_query().where(or_(~work_full,
        and_(Work.sale_type != "free", ~work_preview))).limit(10))).all())
    for item in works:
        asset = await db.get(Asset, item.asset_id)
        await enqueue(db, "work", item, asset)
        if item.sale_type != "free":
            preview = await preview_for(db, item)
            if preview and preview.status == "done":
                await enqueue(db, "work", item, asset, "preview", preview.object_key)
    series_ids = series_query().with_only_columns(Series.id)
    episode_full = select(AppMedia.id).where(AppMedia.content_type == "series_episode",
        AppMedia.content_id == SeriesEpisode.id, AppMedia.version == SeriesEpisode.version,
        AppMedia.variant == "full").exists()
    episode_preview = select(AppMedia.id).where(AppMedia.content_type == "series_episode",
        AppMedia.content_id == SeriesEpisode.id, AppMedia.version == SeriesEpisode.version,
        AppMedia.variant == "preview").exists()
    paid_episode = and_(Series.sale_type != "free", SeriesEpisode.episode_no > Series.free_episode_count)
    episodes = list((await db.scalars(select(SeriesEpisode).join(Series, Series.id == SeriesEpisode.series_id).where(
        SeriesEpisode.series_id.in_(series_ids), or_(~episode_full, and_(paid_episode, ~episode_preview))).limit(10))).all())
    for item in episodes:
        asset = await db.get(Asset, item.asset_id)
        await enqueue(db, "series_episode", item, asset)
        series = await db.get(Series, item.series_id)
        if not episode_is_free(series, item):
            preview = await episode_preview_for(db, item)
            if preview and preview.status == "done":
                await enqueue(db, "series_episode", item, asset, "preview", preview.object_key)


def compatible_source(probe):
    """封装成功不代表 iOS 兼容，只有 H264/yuv420p/AAC 且无旋转才直接复制。"""
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    rotation = video.get("tags", {}).get("rotate", 0)
    for side in video.get("side_data_list", []):
        rotation = side.get("rotation", rotation)
    return bool(video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p"
        and int(float(rotation)) % 360 == 0 and all(s.get("codec_name") == "aac" for s in audio))


async def render(snapshot):
    """本地仅作处理缓存，校验兼容性、完整时长后才把结果写入私有 OSS。"""
    from .worker import cache_root, command
    from .preview_worker import _probe, _video, _duration
    config = get_settings()
    with tempfile.TemporaryDirectory(prefix="job-", dir=cache_root()) as directory:
        root = Path(directory)
        source = root / ("source" + (".mp4" if snapshot["variant"] == "preview" else Path(snapshot["filename"]).suffix))
        await asyncio.to_thread(storage.download, snapshot["source_key"], source)
        if snapshot["variant"] == "full" and source.stat().st_size != snapshot["size_bytes"]:
            raise ValueError("源视频大小已改变")
        if snapshot["variant"] == "full" and snapshot.get("fingerprint"):
            from .worker import fingerprint
            if await asyncio.to_thread(fingerprint, source) != snapshot["fingerprint"]:
                raise ValueError("源视频指纹已改变")
        probe = await _probe(source)
        video = _video(probe)
        if not video or not 0 < int(video.get("width", 0)) * int(video.get("height", 0)) <= 50_000_000:
            raise ValueError("源视频尺寸无效")
        duration = _duration(probe)
        maximum = min(15.0, float(snapshot["duration_seconds"] or 0) * .3) if snapshot["variant"] == "preview" else video_duration_limit()
        if not 0 < duration <= maximum:
            raise ValueError("源视频时长不符合播放用途")
        output = root / "hls"
        output.mkdir()
        playlist = output / "index.m3u8"
        common = [config.ffmpeg_path, "-y", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?"]
        suffix = ["-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
            "-hls_segment_filename", str(output / "segment-%05d.ts"), str(playlist)]
        if compatible_source(probe):
            await command(*common, "-c", "copy", *suffix, timeout=1800)
        else:
            await command(*common, "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:a", "aac", "-b:a", "192k", *suffix, timeout=3600)
        generated = json.loads(await command(config.ffprobe_path, "-v", "error", "-protocol_whitelist", "file,crypto,data",
            "-show_streams", "-show_format", "-of", "json", str(playlist), timeout=60))
        result_video = _video(generated)
        if not result_video or not compatible_source(generated):
            raise ValueError("播放派生物不兼容 iOS")
        original_size = (int(video["width"]), int(video["height"]))
        rotated_size = (original_size[1], original_size[0])
        if (int(result_video["width"]), int(result_video["height"])) not in {
            original_size, rotated_size, tuple((v + 1) // 2 * 2 for v in original_size), tuple((v + 1) // 2 * 2 for v in rotated_size)}:
            raise ValueError("播放派生物改变了源分辨率")
        generated_duration = _duration(generated)
        if snapshot["variant"] == "preview" and generated_duration > maximum or abs(generated_duration - duration) > .5:
            raise ValueError("播放派生物时长校验失败")
        from .app_playback import parse_playlist
        prefix = f"marketplace/app-hls/{snapshot['job_id']}/{snapshot['token']}/"
        parse_playlist(playlist.read_text(encoding="utf-8"), prefix)
        files = list(output.glob("*.ts")) + [playlist]
        for file in files:
            await asyncio.to_thread(storage.upload, prefix + file.name, file,
                "application/vnd.apple.mpegurl" if file.suffix == ".m3u8" else "video/mp2t")
        return prefix + "index.m3u8"


async def heartbeat(job_id, token):
    """长视频转码续租，不借用原 AI 调度器。"""
    while True:
        await asyncio.sleep(20)
        async with AsyncSessionLocal() as db:
            job = await db.scalar(select(AppMedia).where(AppMedia.id == job_id, AppMedia.lease_token == token).with_for_update())
            if not job:
                return
            job.lease_until = now() + timedelta(seconds=90)
            await db.commit()


async def run_app_media_once():
    """现有市场并发槽内执行一项，可重试、续租并在服务重启后恢复。"""
    from .app_access import app_open
    if not app_open():
        return False
    async with AsyncSessionLocal() as db:
        await discover(db)
        await db.execute(update(AppMedia).where(AppMedia.status == "running",
            AppMedia.attempts >= get_marketplace_settings().worker_max_attempts,
            AppMedia.lease_until < now()).values(status="failed", lease_token=None, lease_until=None,
                error="处理重启恢复次数已达上限，请在运营后台重试"))
        job = await db.scalar(select(AppMedia).where(AppMedia.status.in_(("pending", "running")),
            AppMedia.attempts < get_marketplace_settings().worker_max_attempts,
            or_(AppMedia.lease_until.is_(None), AppMedia.lease_until < now())).order_by(AppMedia.id).with_for_update(skip_locked=True).limit(1))
        if not job:
            await db.commit()
            return False
        asset = await db.get(Asset, job.asset_id)
        if not asset or asset.status != "ready":
            job.status, job.error = "failed", "源视频尚未就绪"
            await db.commit()
            return True
        token = uuid.uuid4().hex
        job.status, job.lease_token, job.lease_until = "running", token, now() + timedelta(seconds=90)
        job.attempts += 1
        snapshot = {"job_id": job.id, "token": token, "variant": job.variant, "source_key": job.source_key,
            "asset_id": job.asset_id, "version": job.version,
            "filename": asset.filename, "size_bytes": asset.size_bytes, "fingerprint": asset.fingerprint,
            "duration_seconds": asset.duration_seconds}
        await db.commit()
    pulse = asyncio.create_task(heartbeat(snapshot["job_id"], token))
    result, failure = None, ""
    try:
        result = await render(snapshot)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("App 播放准备失败 job=%s", snapshot["job_id"])
        failure = "App 播放文件准备失败，可在运营后台重试"
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
    async with AsyncSessionLocal() as db:
        # 完成旧版本派生物是合法的（供历史买家使用），只写回同一不可变任务快照。
        job = await db.scalar(select(AppMedia).where(AppMedia.id == snapshot["job_id"],
            AppMedia.lease_token == token, AppMedia.asset_id == snapshot["asset_id"],
            AppMedia.version == snapshot["version"], AppMedia.source_key == snapshot["source_key"]).with_for_update())
        if job:
            job.status = "done" if result else "failed" if job.attempts >= get_marketplace_settings().worker_max_attempts else "pending"
            job.manifest_key, job.error = result, failure
            job.lease_token, job.lease_until = None, None
            await db.commit()
    return True
