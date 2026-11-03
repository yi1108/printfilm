"""独立媒体进程：python -m app.marketplace.worker；不修改原任务运行时。"""
import asyncio
from datetime import timedelta
import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
import threading
import tempfile
import time
import uuid

from sqlalchemy import and_, or_, select, update

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from . import storage
from .config import get_marketplace_settings, is_marketplace_enabled
from .models import Asset, MarketBase, MediaJob, PlaybackJob, Publication, Recruit, Series, SeriesEpisode, Upload, Work
from .service import now, notify

logger = logging.getLogger("marketplace.worker")


def cache_root() -> Path:
    """专用非公开缓存根；不使用上游 static 或生成目录。"""
    root = Path(tempfile.gettempdir()).resolve() / "printfilm-marketplace-cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def clean_stale_cache() -> None:
    """只删除本模块24小时前的任务缓存；校验绝对路径并拒绝符号链接。"""
    root = cache_root().resolve()
    for candidate in root.iterdir():
        if candidate.is_symlink() or not candidate.name.startswith("job-"):
            continue
        resolved = candidate.resolve()
        if resolved.parent != root or not resolved.is_dir():
            continue
        if time.time() - resolved.stat().st_mtime > 86400:
            shutil.rmtree(resolved)


def resolve_tool(executable: str) -> str:
    """后台默认命令不在 PATH 时，使用本机环境中已配置的实际路径。"""
    if executable in ("ffmpeg", "ffprobe") and not shutil.which(executable):
        from app.config import Settings
        configured = getattr(Settings(), executable + "_path")
        if configured != executable and (Path(configured).is_file() or shutil.which(configured)):
            return configured
        raise ValueError(f"未找到 {executable}，请在后台系统设置中配置有效程序路径")
    return executable


async def threaded_command(args, timeout):
    """Windows Selector 事件循环不支持异步子进程，在线程中执行并支持取消。"""
    cancelled = threading.Event()
    def run():
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancelled.is_set():
                    raise RuntimeError("媒体命令已取消")
                if time.monotonic() >= deadline:
                    raise TimeoutError("媒体处理超时")
                try:
                    output, error = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                logger.warning("media command failed: %s", error[-1500:].decode("utf-8", errors="replace"))
                raise ValueError("媒体文件无法解析或转码失败")
            return output
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()
    task = asyncio.create_task(asyncio.to_thread(run))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        await asyncio.gather(task, return_exceptions=True)
        raise


async def command(*args: str, timeout: float = 3600) -> bytes:
    """有界子进程，超时或停机时回收 FFmpeg，避免孤儿进程。"""
    args = (resolve_tool(args[0]), *args[1:])
    try:
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except NotImplementedError:
        return await threaded_command(args, timeout)
    try:
        output, error = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            logger.warning("media command failed: %s", error[-1500:].decode("utf-8", errors="replace"))
            raise ValueError("媒体文件无法解析或转码失败")
        return output
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def fingerprint(path: Path) -> str:
    """流式计算指纹，不把完整原片读入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def process_asset(asset: dict) -> dict:
    """临时文件仅供检测和转码，所有结果成功上传 OSS 后返回 ready 数据。"""
    settings, upstream = get_marketplace_settings(), get_settings()
    with tempfile.TemporaryDirectory(prefix="job-", dir=cache_root()) as directory:
        root = Path(directory)
        source = root / ("source" + Path(asset["filename"]).suffix.lower())
        await asyncio.to_thread(storage.download, asset["object_key"], source)
        if source.stat().st_size != asset["size_bytes"]:
            raise ValueError("文件大小与上传记录不一致")
        result = {"fingerprint": await asyncio.to_thread(fingerprint, source)}
        if asset["content_type"] == "application/pdf":
            with source.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise ValueError("文件内容不是 PDF")
            return result
        # MP4 is the primary upload format.  Keep probing independent from
        # upload filename and accept the three supported video containers.
        formats = "mov,mp4,matroska,webm" if asset["kind"] == "video" else "png_pipe,jpeg_pipe,webp_pipe"
        probe = json.loads(await command(upstream.ffprobe_path, "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", formats, "-show_format", "-show_streams", "-show_data", "-of", "json", str(source), timeout=60))
        videos = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
        if not videos:
            raise ValueError("文件不包含有效画面")
        width, height = int(videos[0].get("width", 0)), int(videos[0].get("height", 0))
        if width < 2 or height < 2 or width * height > 50_000_000:
            raise ValueError("画面尺寸不支持")
        if asset["kind"] != "video":
            if videos[0].get("codec_name") not in ("png", "mjpeg", "webp"):
                raise ValueError("图片内容与允许格式不符")
            # 重新编码图片去除附加内容，签名时只返回处理后的对象。
            image = root / "image.png"
            await command(upstream.ffmpeg_path, "-y", "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", formats, "-i", str(source), "-frames:v", "1", str(image), timeout=60)
            key = f"marketplace/processed/{asset['id']}/image.png"
            await asyncio.to_thread(storage.upload, key, image, "image/png")
            return {**result, "cover_key": key}
        format_name = probe.get("format", {}).get("format_name", "")
        if not any(name in format_name.split(",") for name in ("mov", "mp4", "matroska", "webm")):
            raise ValueError("只支持 MP4、MOV、WebM 视频")
        duration = float(probe.get("format", {}).get("duration", 0))
        if not 0 < duration <= settings.max_duration_seconds:
            raise ValueError("视频时长无效或超过30分钟限制")
        # Upload processing only validates the source and records metadata.
        # Free works play the original object, while paid works create their
        # 15-second/30%-limited watermark in the submission path and platform
        # HLS is packaged only after approval.  Generating previews for every
        # upload here made free content appear perpetually "processing" and
        # needlessly changed video quality.
        from .drama_geometry import stream_display_size
        display_width, display_height = stream_display_size(videos[0])
        return {**result, "duration_seconds": duration, "display_width": display_width, "display_height": display_height}


async def heartbeat(job_id: int, token: str) -> None:
    """租约心跳使多进程不会同时提交一个任务的结果。"""
    while True:
        await asyncio.sleep(20)
        async with AsyncSessionLocal() as db:
            result = await db.execute(update(MediaJob).where(MediaJob.id == job_id, MediaJob.lease_token == token, MediaJob.status == "running").values(lease_until=now() + timedelta(seconds=90)))
            await db.commit()
            if not result.rowcount:
                raise RuntimeError("媒体任务租约已丢失")


async def claim() -> tuple[int, str, dict] | None:
    """SKIP LOCKED 领取一个任务，恢复进程中断遗留任务。"""
    async with AsyncSessionLocal() as db:
        query = select(MediaJob).where(or_(MediaJob.status == "pending", and_(MediaJob.status == "running", MediaJob.lease_until < now()))).order_by(MediaJob.id).with_for_update(skip_locked=True).limit(1)
        item = (await db.execute(query)).scalar_one_or_none()
        if not item:
            return None
        asset = await db.get(Asset, item.asset_id)
        if item.attempts >= get_marketplace_settings().worker_max_attempts:
            item.status, asset.status = "failed", "failed"
            asset.error = "处理重试次数已用完，请检查文件后重试"
            notify(db, asset.owner_id, f"文件《{asset.filename}》处理失败，请查看我的作品")
            await db.commit()
            return None
        item.attempts += 1
        item.status, item.lease_token, item.lease_until = "running", uuid.uuid4().hex, now() + timedelta(seconds=90)
        snapshot = {key: getattr(asset, key) for key in ("id", "filename", "object_key", "kind", "size_bytes", "content_type")}
        await db.commit()
        return item.id, item.lease_token, snapshot


async def backfill_display_size_once() -> bool:
    """每次最多补一条已入库但没有画幅的视频；失败写成 0，避免反复下载坏文件。"""
    async with AsyncSessionLocal() as db:
        asset = (await db.execute(select(Asset).where(Asset.kind == "video", Asset.status == "ready", Asset.display_width.is_(None)).order_by(Asset.id).limit(1))).scalar_one_or_none()
        if not asset:
            return False
        snapshot = {"id": asset.id, "filename": asset.filename, "object_key": asset.object_key}
    width = height = 0
    try:
        with tempfile.TemporaryDirectory(prefix="job-", dir=cache_root()) as directory:
            source = Path(directory) / ("source" + Path(snapshot["filename"] or "video.mp4").suffix.lower())
            await asyncio.to_thread(storage.download, snapshot["object_key"], source)
            upstream = get_settings()
            probe = json.loads(await command(upstream.ffprobe_path, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-show_data", "-of", "json", str(source), timeout=60))
            videos = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
            if videos:
                from .drama_geometry import stream_display_size
                width, height = stream_display_size(videos[0])
    except Exception:
        logger.warning("视频画幅补齐失败 asset=%s", snapshot["id"])
        width = height = 0
    async with AsyncSessionLocal() as db:
        row = await db.get(Asset, snapshot["id"])
        if row is not None and row.display_width is None:
            row.display_width, row.display_height = width, height
            await db.commit()
    return True


async def run_once() -> bool:
    """执行单任务，结果写入时再次比较租约令牌。"""
    claimed = await claim()
    if not claimed:
        return False
    job_id, token, asset = claimed
    pulse = asyncio.create_task(heartbeat(job_id, token))
    processing = asyncio.create_task(process_asset(asset))
    result, error = None, ""
    try:
        done, _ = await asyncio.wait((pulse, processing), return_when=asyncio.FIRST_COMPLETED)
        if pulse in done:
            await pulse
            raise RuntimeError("媒体心跳意外停止")
        result = await processing
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("marketplace media job %s failed", job_id)
        error = "媒体处理失败，请检查文件、字体和文件服务配置后重试"
    finally:
        pulse.cancel()
        processing.cancel()
        await asyncio.gather(pulse, processing, return_exceptions=True)
    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(MediaJob).where(MediaJob.id == job_id, MediaJob.lease_token == token).with_for_update())).scalar_one_or_none()
        if not job:
            return True
        record = await db.get(Asset, asset["id"])
        if result is not None:
            for key, value in result.items():
                setattr(record, key, value)
            job.status, record.status, record.error = "done", "ready", ""
            notify(db, record.owner_id, f"文件《{record.filename}》已处理完成")
        else:
            terminal = job.attempts >= get_marketplace_settings().worker_max_attempts
            job.status, record.status = ("failed", "failed") if terminal else ("pending", "processing")
            job.error, record.error = error, error
        job.lease_until, job.lease_token = None, None
        await db.commit()
    return True


async def maintenance() -> None:
    """清理过期 multipart，并标记到期需求；不删除证据或已提交素材。"""
    await asyncio.to_thread(clean_stale_cache)
    async with AsyncSessionLocal() as db:
        uploads = (await db.execute(select(Upload).where(Upload.state == "uploading", Upload.expires_at < now()).with_for_update(skip_locked=True).limit(10))).scalars().all()
        for item in uploads:
            asset = await db.get(Asset, item.asset_id)
            await asyncio.to_thread(storage.abort, asset.object_key, item.remote_id)
            item.state, asset.status = "expired", "expired"
        await db.execute(update(Recruit).where(Recruit.state == "open", Recruit.deadline_at <= now()).values(state="expired"))
        await db.commit()


async def package_publication_once() -> bool:
    """为已审核的平台投放版本生成同源分辨率 HLS 播放清单。"""
    async with AsyncSessionLocal() as db:
        # PlaybackJob owns the lease so a crashed Worker can resume packaging;
        # Publication retains only the immutable playback result/status.  Join
        # against approved publications to avoid repeatedly claiming jobs for a
        # draft that is still waiting for admin review.
        job = (await db.execute(select(PlaybackJob).join(
            Publication, Publication.id == PlaybackJob.publication_id
        ).where(
            PlaybackJob.status.in_(("pending", "running")),
            Publication.sale_type == "platform_unlock",
            Publication.audit_status == "approved",
            Publication.playback_status.in_(("pending", "running")),
            Publication.playback_manifest_key.is_(None),
        ).order_by(PlaybackJob.id).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if not job:
            # Backfill a job for platform publications created before the durable
            # job table was introduced.  This remains idempotent under the row
            # lock and allows existing approved content to recover automatically.
            publication = (await db.execute(select(Publication).where(
                Publication.sale_type == "platform_unlock",
                Publication.audit_status == "approved",
                Publication.playback_status.in_(("pending", "running")),
                Publication.playback_manifest_key.is_(None),
                ~select(PlaybackJob.id).where(PlaybackJob.publication_id == Publication.id).exists(),
            ).order_by(Publication.id).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
            if not publication:
                return False
            job = PlaybackJob(publication_id=publication.id, status="pending")
            db.add(job)
            await db.flush()
        publication = await db.get(Publication, job.publication_id, with_for_update=True)
        if not publication:
            job.status, job.error = "failed", "发布版本不存在"
            await db.commit()
            return True
        asset = await db.get(Asset, publication.asset_id)
        if not asset or asset.status != "ready":
            job.status, job.error = "failed", "媒体尚未就绪"
            publication.playback_status, publication.playback_error = "failed", "媒体尚未就绪"
            await db.commit()
            return True
        token = uuid.uuid4().hex
        job.status, job.attempts = "running", job.attempts + 1
        job.lease_token, job.lease_until = token, now() + timedelta(seconds=90)
        publication.playback_status, publication.playback_attempts = "running", publication.playback_attempts + 1
        publication_id, attempts = publication.id, job.attempts
        snapshot = {"object_key": asset.object_key, "filename": asset.filename, "size_bytes": asset.size_bytes}
        await db.commit()

    result_key, error = None, ""
    try:
        settings = get_settings()
        with tempfile.TemporaryDirectory(prefix="job-", dir=cache_root()) as directory:
            root = Path(directory)
            source = root / ("source" + Path(snapshot["filename"]).suffix.lower())
            await asyncio.to_thread(storage.download, snapshot["object_key"], source)
            if source.stat().st_size != snapshot["size_bytes"]:
                raise ValueError("原片大小不一致")
            hls_dir = root / "hls"
            hls_dir.mkdir()
            segment_pattern = str(hls_dir / "segment-%05d.ts")
            playlist = hls_dir / "index.m3u8"
            try:
                await command(settings.ffmpeg_path, "-y", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod", "-hls_segment_filename", segment_pattern, str(playlist), timeout=1800)
            except Exception:
                # 只在封装不兼容时重编码，保留原分辨率，不强制降画质或尺寸。
                await command(settings.ffmpeg_path, "-y", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod", "-hls_segment_filename", segment_pattern, str(playlist), timeout=3600)
            prefix = f"marketplace/hls/{publication_id}/"
            for file in hls_dir.iterdir():
                content_type = "application/vnd.apple.mpegurl" if file.suffix == ".m3u8" else "video/mp2t"
                await asyncio.to_thread(storage.upload, prefix + file.name, file, content_type)
            result_key = prefix + playlist.name
    except Exception as exc:
        logger.exception("publication playback packaging failed id=%s", publication_id)
        error = "播放版本生成失败，请稍后重试"

    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(PlaybackJob).where(
            PlaybackJob.publication_id == publication_id,
            PlaybackJob.lease_token == token,
        ).with_for_update())).scalar_one_or_none()
        publication = await db.get(Publication, publication_id, with_for_update=True)
        if job and publication:
            if result_key:
                publication.playback_manifest_key, publication.playback_status, publication.playback_error = result_key, "done", ""
                job.status, job.error = "done", ""
                if publication.content_type == "work":
                    parent = await db.get(Work, publication.content_id)
                else:
                    episode = await db.get(SeriesEpisode, publication.content_id)
                    parent = await db.get(Series, episode.series_id) if episode else None
                publication.listed = bool(parent and parent.listed and parent.audit_status == "approved" and not parent.blocked)
            else:
                terminal = attempts >= get_marketplace_settings().worker_max_attempts
                job.status, job.error = ("failed" if terminal else "pending"), error
                publication.playback_status, publication.playback_error = ("failed" if terminal else "pending"), error
            job.lease_until, job.lease_token = None, None
            await db.commit()
    return True


async def refresh_storage_settings() -> None:
    """只读后台配置；不初始化、修复或回写原模型路由。"""
    from app.config import reload_settings
    from app.models_settings import AppSettings
    from app.services.model_settings import _decrypt_flat_config, _refresh_overlay
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSettings, "default")
        _refresh_overlay({"flat": _decrypt_flat_config(row.config_json if row else {})})
    reload_settings()


async def run_app_media_if_ready() -> bool:
    """复用市场并发槽，App关闭或未显式迁移时不查询其媒体及财务表。"""
    from .app_access import app_open
    if not app_open():
        return False
    from .app_bootstrap import schema_ready
    if not await schema_ready():
        return False
    from .app_media import run_app_media_once
    return await run_app_media_once()


async def run_loop(*, standalone: bool = False) -> None:
    """后端内嵌与独立命令共用循环；不释放共享数据库连接池。"""
    from sqlalchemy import text
    while True:
        try:
            if standalone:
                await refresh_storage_settings()
            if is_marketplace_enabled() and storage.configured():
                # 所有后端进程/手动命令共享一把事务锁，市场媒体总并发保持为1。
                async with engine.begin() as connection:
                    acquired = await connection.scalar(text("SELECT pg_try_advisory_xact_lock(18427, 73102)"))
                    if acquired:
                        await asyncio.to_thread(storage.bucket)
                        await maintenance()
                        from .preview_worker import release_finished_series_once, run_episode_preview_once, run_preview_once
                        await run_episode_preview_once()
                        await run_preview_once()
                        await release_finished_series_once()
                        from .handoff import run_handoff_once
                        await run_handoff_once()
                        await run_once()
                        await backfill_display_size_once()
                        await package_publication_once()
                        await run_app_media_if_ready()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("市场 Worker 本轮失败，将延迟重试")
        await asyncio.sleep(max(1, get_marketplace_settings().worker_poll_seconds))


async def main() -> None:
    """保留手动命令兼容；日常开发由后端生命周期自动托管。"""
    if not is_marketplace_enabled():
        logger.info("下游模块未启用，Worker 不启动")
        return
    try:
        from .app_schema import legacy_marketplace_tables
        async with engine.begin() as conn:
            await conn.run_sync(lambda connection: MarketBase.metadata.create_all(connection, tables=legacy_marketplace_tables()))
        from .app_settings import get_app_settings
        if get_app_settings().enabled:
            from .app_bootstrap import verify_schema
            if await verify_schema():
                raise RuntimeError("App数据库结构未准备，请先执行 App 显式增量迁移并检查。")
        await run_loop(standalone=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
