"""真实 FFmpeg 短片验收及任务回填隔离；OSS 传输使用测试替身。"""
from contextlib import asynccontextmanager
import asyncio
from datetime import timedelta
import hashlib
import json
import shutil
import subprocess

import pytest
from sqlalchemy import text

from app.config import get_settings


def _independent_fps_flag(ffmpeg_path: str) -> str:
    """直接对真实二进制做同步探针：FFmpeg 5.1 起支持 -fps_mode。"""
    try:
        subprocess.run([ffmpeg_path, "-hide_banner", "-v", "error",
                        "-f", "lavfi", "-i", "color=size=16x16:duration=0.1:rate=1",
                        "-frames:v", "1", "-fps_mode", "passthrough", "-f", "null", "-"],
                       capture_output=True, check=True, timeout=30)
        return "-fps_mode"
    except Exception:
        return "-vsync"
from app.marketplace import preview_worker, storage, worker
from app.marketplace.config import get_marketplace_settings
from app.marketplace.models import Asset, EpisodePreview, Publication, Rights, Series, SeriesEpisode, Work, WorkPreview
from app.marketplace.previews import CLIP_EPISODE_PREFIX, CLIP_WORK_PREFIX
from app.marketplace.service import now
from test_marketplace import asset, ctx, rights, work_body  # noqa: F401
from test_marketplace_drama_concurrency import concurrent_publish_ctx  # noqa: F401


@pytest.mark.parametrize("mode,seconds,dimensions", [
    ("copy", 10, "1920x1080"), ("fallback", 10, "320x180"),
    ("long_gop", 10, "320x180"), ("vfr", 10, "320x180"), ("copy", 60, "320x180"),
])
async def test_real_short_preview_without_watermark(monkeypatch, tmp_path, mode, seconds, dimensions):
    settings = get_settings()
    source, result = tmp_path / "source.mp4", tmp_path / "result.mp4"
    options = ["-c:v", "mpeg4"] if mode == "fallback" else ["-c:v", "libx264", "-preset", "ultrafast"]
    if mode == "long_gop":
        options += ["-g", "500", "-bf", "3"]
    elif mode != "fallback":
        options += ["-g", "1", "-bf", "0"]
    if mode == "vfr":
        options += ["-vf", "select=not(mod(n\\,2))+not(mod(n\\,3))",
                    _independent_fps_flag(settings.ffmpeg_path), "vfr"]
    inputs = ["-f", "lavfi", "-i", f"color=c=blue:s={dimensions}:r=24"]
    if mode != "copy":
        inputs += ["-f", "lavfi", "-i", "sine=frequency=440"]
        options += ["-c:a", "aac"]
    await worker.command(settings.ffmpeg_path, "-y", "-v", "error", *inputs, "-t", str(seconds),
                         *options, "-pix_fmt", "yuv420p", str(source), timeout=120)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    commands, uploaded = [], []
    real_command = worker.command

    async def capture(*args, **kwargs):
        commands.append(args)
        return await real_command(*args, **kwargs)

    def upload(key, path, mime):
        uploaded.append((key, mime))
        shutil.copyfile(path, result)

    monkeypatch.setattr(worker, "command", capture)
    monkeypatch.setattr(storage, "download", lambda _key, target: shutil.copyfile(source, target))
    monkeypatch.setattr(storage, "upload", upload)
    # An invalid font must not affect no-watermark video processing.
    monkeypatch.setattr(get_marketplace_settings(), "watermark_font", "Z:/missing-font.ttf")
    key = await preview_worker.render_preview(dict(content_type="series_episode", content_id=12,
        asset_id=34, filename=source.name, source_key="private-source", size_bytes=source.stat().st_size))
    probe = json.loads(await real_command(settings.ffprobe_path, "-v", "error", "-show_format",
                                          "-show_streams", "-of", "json", str(result)))
    maximum = min(15, seconds * .3)
    assert maximum - .5 <= float(probe["format"]["duration"]) <= maximum
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"]) == tuple(map(int, dimensions.split("x")))
    assert video["codec_name"] == "h264"
    assert uploaded == [(key, "video/mp4")] and key.startswith(CLIP_EPISODE_PREFIX)
    assert not any("drawtext" in str(value) for command in commands for value in command)
    if mode == "copy":
        assert any("copy" in command for command in commands)
        assert not any("libx264" in command for command in commands)
    if mode == "fallback":
        assert any("libx264" in command for command in commands)
    if mode != "copy":
        assert any(stream["codec_type"] == "audio" for stream in probe["streams"])
    frame = await real_command(settings.ffmpeg_path, "-v", "error", "-i", str(result), "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1")
    assert not any(value > 30 for value in frame[::3])  # 蓝底上不能出现白色烧录文字。
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


@pytest.mark.parametrize("phase", ["download", "upload"])
async def test_render_failure_identifies_stage_without_exposing_credentials(monkeypatch, tmp_path, phase):
    secret = "oss-private-credential"

    def fail(*_args):
        raise RuntimeError(secret)

    snapshot = dict(content_type="work", content_id=1, asset_id=2, filename="source.mp4", source_key="private", size_bytes=1)
    if phase == "download":
        monkeypatch.setattr(storage, "download", fail)
    else:
        monkeypatch.setattr(storage, "download", lambda _key, target: target.write_bytes(b"x"))
        monkeypatch.setattr(storage, "upload", fail)
        probe = {"format": {"duration": "10"}, "streams": [
            {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "width": 320, "height": 180}]}

        async def fake_probe(path):
            return {**probe, "format": {"duration": "2.8"}} if path.name == "preview.mp4" else probe

        async def fake_command(*args, **_kwargs):
            from pathlib import Path
            Path(args[-1]).write_bytes(b"preview")

        monkeypatch.setattr(preview_worker, "_probe", fake_probe)
        monkeypatch.setattr(worker, "command", fake_command)
    with pytest.raises(preview_worker.PreviewProcessingError) as caught:
        await preview_worker.render_preview(snapshot)
    assert ("下载" if phase == "download" else "上传") in str(caught.value)
    assert secret not in str(caught.value)


async def episode_job(ctx, *, attempts=0, expired=False):
    video = await asset(ctx)
    cover = await asset(ctx, kind="image")
    await rights(ctx, video, full=True)
    series = Series(owner_id=ctx.owner.id, title="任务测试", sale_type="copyright_contact",
                    cover_asset_id=cover.id, audit_status="processing")
    ctx.db.add(series)
    await ctx.db.flush()
    episode = SeriesEpisode(series_id=series.id, owner_id=ctx.owner.id, episode_no=1,
        title="第一集", asset_id=video.id, source="original", preview_status="pending")
    ctx.db.add(episode)
    await ctx.db.flush()
    job = EpisodePreview(episode_id=episode.id, asset_id=video.id, version=episode.version,
                         attempts=attempts, status="running" if expired else "pending",
                         lease_token="expired" if expired else None,
                         lease_until=now() - timedelta(seconds=1) if expired else None)
    publication = Publication(content_type="series_episode", content_id=episode.id, owner_id=ctx.owner.id,
        version=episode.version, asset_id=video.id, sale_type=series.sale_type, preview_status="pending")
    ctx.db.add_all([job, publication])
    await ctx.db.flush()
    return series, episode, job, publication


def worker_session(ctx, monkeypatch):
    @asynccontextmanager
    async def session():
        yield ctx.db
    monkeypatch.setattr(preview_worker, "AsyncSessionLocal", session)


async def test_episode_worker_recovers_lease_and_advances_review(ctx, monkeypatch):
    series, episode, job, publication = await episode_job(ctx, attempts=1, expired=True)
    worker_session(ctx, monkeypatch)

    async def render(_snapshot):
        return CLIP_EPISODE_PREFIX + "ready.mp4"

    monkeypatch.setattr(preview_worker, "render_preview", render)
    assert await preview_worker.run_episode_preview_once()
    assert job.status == "done" and job.attempts == 2
    assert episode.preview_status == publication.preview_status == "done"
    assert series.audit_status == "pending" and not series.listed
    assert not await preview_worker.run_episode_preview_once()


@pytest.mark.parametrize("change", ["episode_version", "series_version", "asset", "lease", "free", "blocked", "deleted"])
async def test_episode_worker_does_not_overwrite_changed_target(ctx, monkeypatch, change):
    series, episode, job, publication = await episode_job(ctx)
    worker_session(ctx, monkeypatch)

    async def render(_snapshot):
        if change == "episode_version":
            episode.version += 1
            episode.preview_status, episode.preview_key = "pending", "new-result"
        elif change == "series_version":
            series.version += 1
        elif change == "asset":
            episode.asset_id = (await asset(ctx)).id
        elif change == "lease":
            job.lease_token = "new-token"
        elif change == "free":
            series.sale_type = "free"
        elif change == "blocked":
            episode.blocked = True
        else:
            series.deleted_at = now()
        await ctx.db.flush()
        return CLIP_EPISODE_PREFIX + "obsolete.mp4"

    monkeypatch.setattr(preview_worker, "render_preview", render)
    assert await preview_worker.run_episode_preview_once()
    assert publication.preview_key is None and publication.preview_status == "pending"
    assert series.audit_status == "processing" and not series.listed
    if change == "lease":
        assert job.status == "running" and job.lease_token == "new-token"
    else:
        assert job.status == "cancelled" and job.lease_token is None
    if change == "episode_version":
        assert episode.preview_key == "new-result" and episode.preview_status == "pending"


async def test_episode_retry_limit_prevents_expensive_rerender(ctx, monkeypatch):
    series, episode, job, publication = await episode_job(ctx, attempts=get_marketplace_settings().worker_max_attempts, expired=True)
    worker_session(ctx, monkeypatch)

    async def render(_snapshot):
        pytest.fail("重试已用完时不应再次转码")

    monkeypatch.setattr(preview_worker, "render_preview", render)
    assert await preview_worker.run_episode_preview_once()
    assert job.status == episode.preview_status == publication.preview_status == "failed"
    assert series.audit_status == "preview_failed"


async def test_ready_preview_never_automatically_relists_work(ctx, monkeypatch):
    video = await asset(ctx)
    work = Work(owner_id=ctx.owner.id, **work_body(video), audit_status="approved", listed=False)
    ctx.db.add(work)
    await ctx.db.flush()
    job = WorkPreview(work_id=work.id, asset_id=video.id, version=work.version)
    ctx.db.add(job)
    await ctx.db.flush()
    worker_session(ctx, monkeypatch)

    async def render(_snapshot):
        return CLIP_WORK_PREFIX + "ready.mp4"

    monkeypatch.setattr(preview_worker, "render_preview", render)
    assert await preview_worker.run_preview_once()
    assert job.status == "done" and work.audit_status == "approved" and not work.listed


async def test_approved_publication_snapshot_is_immutable_during_preview_repair(ctx, monkeypatch):
    video = await asset(ctx)
    work = Work(owner_id=ctx.owner.id, **work_body(video), audit_status="approved", listed=True)
    ctx.db.add(work)
    await ctx.db.flush()
    job = WorkPreview(work_id=work.id, asset_id=video.id, version=work.version)
    publication = Publication(content_type="work", content_id=work.id, owner_id=ctx.owner.id,
        version=work.version, asset_id=video.id, sale_type="platform_unlock", unlock_price_fen=899,
        share_bps=2000, audit_status="approved", listed=True, preview_status="done",
        preview_key="marketplace/work-watermarks-full/historical.mp4", playback_status="done",
        playback_manifest_key="marketplace/hls/purchased/index.m3u8")
    ctx.db.add_all([job, publication])
    await ctx.db.flush()
    snapshot = (publication.preview_key, publication.preview_status, publication.playback_manifest_key,
                publication.asset_id, publication.unlock_price_fen, publication.share_bps)
    worker_session(ctx, monkeypatch)

    async def render(_snapshot):
        return CLIP_WORK_PREFIX + "new-preview.mp4"

    monkeypatch.setattr(preview_worker, "render_preview", render)
    assert await preview_worker.run_preview_once()
    assert job.status == "done" and job.object_key == CLIP_WORK_PREFIX + "new-preview.mp4"
    assert work.listed and work.audit_status == "approved"
    assert snapshot == (publication.preview_key, publication.preview_status, publication.playback_manifest_key,
                        publication.asset_id, publication.unlock_price_fen, publication.share_bps)


async def test_worker_completion_does_not_lock_preview_before_series(concurrent_publish_ctx, monkeypatch):
    """独立 PG 事务实际争锁，验证 Worker 等父行锁时不先占用任务锁。"""
    state = concurrent_publish_ctx
    async with state.sessions() as db:
        video = Asset(owner_id=state.owner_id, kind="video", filename="source.mp4", content_type="video/mp4",
                      size_bytes=1, object_key="test-source", status="ready")
        cover = Asset(owner_id=state.owner_id, kind="image", filename="cover.png", content_type="image/png",
                      size_bytes=1, object_key="test-cover", status="ready")
        db.add_all([video, cover])
        await db.flush()
        proof = Rights(owner_id=state.owner_id, asset_id=video.id, certificate_asset_id=cover.id,
            details={"source": "original", "author": "测试作者", "holder": "测试权利人", "relationship": "本人",
                     "acquisition": "original", "scope": "展示销售", "third_party": "无", "institution": "登记机构", "certificate_number": "test"})
        series = Series(owner_id=state.owner_id, title="真实锁顺序", sale_type="copyright_contact",
                        cover_asset_id=cover.id, audit_status="processing")
        db.add_all([proof, series])
        await db.flush()
        episode = SeriesEpisode(owner_id=state.owner_id, series_id=series.id, episode_no=1, title="第一集",
                                asset_id=video.id, source="original", preview_status="pending")
        db.add(episode)
        await db.flush()
        job = EpisodePreview(episode_id=episode.id, asset_id=video.id, version=episode.version)
        db.add(job)
        await db.commit()
        series_id, job_id = series.id, job.id
    rendering, release, finishing = asyncio.Event(), asyncio.Event(), asyncio.Event()
    session_pids = []

    @asynccontextmanager
    async def session():
        async with state.sessions() as db:
            session_pids.append(await db.scalar(text("SELECT pg_backend_pid()")))
            if len(session_pids) == 2:
                finishing.set()
            yield db

    async def render(_snapshot):
        rendering.set()
        await release.wait()
        return CLIP_EPISODE_PREFIX + "concurrent.mp4"

    monkeypatch.setattr(preview_worker, "AsyncSessionLocal", session)
    monkeypatch.setattr(preview_worker, "render_preview", render)
    task = asyncio.create_task(preview_worker.run_episode_preview_once())
    try:
        await asyncio.wait_for(rendering.wait(), 5)
        async with state.sessions() as guard:
            await guard.get(Series, series_id, with_for_update=True)
            release.set()
            await asyncio.wait_for(finishing.wait(), 5)
            async with asyncio.timeout(5):
                async with state.engine.connect() as observer:
                    while not await observer.scalar(text(
                        "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:pid AND NOT granted)"
                    ), {"pid": session_pids[-1]}):
                        await asyncio.sleep(.01)
            await guard.execute(text("SET LOCAL lock_timeout = '1s'"))
            locked_job = await guard.get(EpisodePreview, job_id, with_for_update=True)
            assert locked_job.status == "running"
            await guard.commit()
        assert await asyncio.wait_for(task, 5)
        async with state.sessions() as db:
            assert (await db.get(EpisodePreview, job_id)).status == "done"
            assert (await db.get(Series, series_id)).audit_status == "pending"
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
