"""App 播放真实 FFmpeg 本地验证；不连接真实 OSS，不把替身结果记作线上上传验收。"""
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.marketplace import app_media, worker
from app.marketplace.app_playback import parse_playlist


@pytest.mark.asyncio
@pytest.mark.parametrize("codec,extension,expected_copy", [("libx264", ".mp4", True), ("libvpx-vp9", ".webm", False)])
async def test_app_hls_real_ffmpeg_preserves_dimensions_and_checks_ios_codec(tmp_path, monkeypatch, codec, extension, expected_copy):
    """H264 原码封装、VP9 同分辨率转码，两者均检验真实生成文件。"""
    settings = get_settings()
    try:
        ffmpeg = worker.resolve_tool(settings.ffmpeg_path)
        worker.resolve_tool(settings.ffprobe_path)
    except FileNotFoundError:
        pytest.skip("本环境没有 FFmpeg/ffprobe，须在媒体联调环境补验")
    source = tmp_path / ("input" + extension)
    await worker.command(ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10",
        "-t", "2", "-c:v", codec, "-pix_fmt", "yuv420p", str(source), timeout=60)
    uploaded, commands = {}, []
    original_command = worker.command

    async def track_command(*args, **kwargs):
        commands.append(args)
        return await original_command(*args, **kwargs)

    def download(key, target):
        shutil.copyfile(source, target)

    def upload(key, path, content_type):
        uploaded[key] = (Path(path).read_bytes(), content_type)

    monkeypatch.setattr(worker, "command", track_command)
    monkeypatch.setattr(worker, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(app_media.storage, "download", download)
    monkeypatch.setattr(app_media.storage, "upload", upload)
    snapshot = {"job_id": 99, "token": "a" * 32, "variant": "full", "source_key": "marketplace/works/video" + extension,
        "filename": source.name, "size_bytes": source.stat().st_size, "fingerprint": worker.fingerprint(source), "duration_seconds": 2}
    key = await app_media.render(snapshot)
    assert key == "marketplace/app-hls/99/" + "a" * 32 + "/index.m3u8"
    playlist = uploaded[key][0].decode()
    _, segments = parse_playlist(playlist, key.rsplit("/", 1)[0] + "/")
    assert all(segment in uploaded for segment in segments)
    encode = next(args for args in commands if "-hls_segment_filename" in args)
    assert ("copy" in encode) is expected_copy
    assert "scale=" not in " ".join(encode)
    assert uploaded[key][1] == "application/vnd.apple.mpegurl"


@pytest.mark.asyncio
async def test_app_media_rejects_same_size_source_fingerprint_change_before_upload(tmp_path, monkeypatch):
    """源对象同长度被覆盖，也不能把替换文件静默绑定到原版本。"""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"changed")
    uploads = []
    monkeypatch.setattr(worker, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(app_media.storage, "download", lambda key, path: shutil.copyfile(source, path))
    monkeypatch.setattr(app_media.storage, "upload", lambda *args: uploads.append(args))
    with pytest.raises(ValueError, match="指纹"):
        await app_media.render({"job_id": 1, "token": "b" * 32, "variant": "full", "source_key": "marketplace/works/input.mp4",
            "filename": "input.mp4", "size_bytes": 7, "fingerprint": "0" * 64, "duration_seconds": 100})
    assert uploads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [[], ["marketplace_coin_wallets"]])
async def test_standalone_market_worker_cannot_create_app_financial_tables(monkeypatch, missing):
    """手动 Worker 只初始化既有表；新 App 结构缺失时不能绕过显式迁移。"""
    from app.marketplace import app_bootstrap, app_schema, app_settings
    app_tables = set(app_schema.register_models())
    created, lifecycle = [], []

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def run_sync(self, callback):
            callback(None)

    async def verify():
        lifecycle.append("verify")
        return missing

    async def run_loop(*, standalone):
        assert standalone
        lifecycle.append("loop")

    async def dispose():
        lifecycle.append("dispose")

    monkeypatch.setattr(worker, "is_marketplace_enabled", lambda: True)
    monkeypatch.setattr(worker, "engine", SimpleNamespace(begin=lambda: Connection(), dispose=dispose))
    monkeypatch.setattr(worker.MarketBase.metadata, "create_all", lambda bind, *, tables: created.extend(tables))
    monkeypatch.setattr(app_settings, "get_app_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(app_bootstrap, "verify_schema", verify)
    monkeypatch.setattr(worker, "run_loop", run_loop)
    if missing:
        with pytest.raises(RuntimeError, match="App数据库结构未准备"):
            await worker.main()
        assert lifecycle == ["verify", "dispose"]
    else:
        await worker.main()
        assert lifecycle == ["verify", "loop", "dispose"]
    assert created and not app_tables.intersection(created)
