"""真实 FFmpeg 校验整集顺序、音频与画质；OSS 只使用测试文件替身。"""
import os
from pathlib import Path
import shutil
import struct
from types import SimpleNamespace

import pytest

from app.marketplace import drama_media as media


@pytest.fixture
def local_media(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    cache = tmp_path / "private-cache"
    cache.mkdir()
    monkeypatch.setattr(media, "STATIC_ROOT", static)
    monkeypatch.setattr(media, "cache_root", lambda: cache)
    paths = list(Path("C:/soft/ffmpeg").glob("*/bin/ffmpeg.exe"))
    ffmpeg = shutil.which("ffmpeg") or (str(paths[0]) if paths else "ffmpeg")
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if ffmpeg.endswith(".exe") else "ffprobe"))
    settings = SimpleNamespace(public_base_url="http://localhost:8000", oss_folder="kepu", oss_bucket="test-bucket",
        oss_endpoint="oss-cn-hangzhou.aliyuncs.com", oss_public_base="https://media.example.test/assets",
        ffmpeg_path=ffmpeg, ffprobe_path=ffprobe)
    monkeypatch.setattr(media, "get_settings", lambda: settings)
    uploaded = tmp_path / "uploaded.mp4"
    def upload(key, source, content_type):
        assert key.startswith("marketplace/")
        assert content_type == "video/mp4"
        assert cache in source.parents
        shutil.copyfile(source, uploaded)
    monkeypatch.setattr(media.storage, "upload", upload)
    return static, cache, uploaded, settings


def test_local_stamp_and_version_changes_when_same_length_file_changes(local_media):
    static, _cache, _uploaded, _settings = local_media
    source = static / "demo.mp4"
    source.write_bytes(b"first")
    before = media.source_stamp("/static/demo.mp4")
    old_stat = source.stat()
    source.write_bytes(b"other")
    os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    after = media.source_stamp("/static/demo.mp4")
    assert before["size_bytes"] == after["size_bytes"]
    assert before["mtime_ns"] == after["mtime_ns"]
    assert media.stamp_version(before) != media.stamp_version(after)


@pytest.mark.parametrize("locator", ["/static/../secret.mp4", "https://evil.test/kepu/generated/p1/video.mp4",
    "https://test-bucket.oss-cn-hangzhou.aliyuncs.com.evil.test/kepu/generated/a.mp4",
    "https://media.example.test/not-assets/kepu/generated/a.mp4"])
def test_source_locator_rejects_untrusted_paths(local_media, locator):
    with pytest.raises(ValueError, match="MARKETPLACE_SOURCE_NOT_READY"):
        media.source_stamp(locator)


def test_absolute_file_outside_static_is_rejected(local_media, tmp_path):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not permitted")
    with pytest.raises(ValueError, match="MARKETPLACE_SOURCE_NOT_READY"):
        media.source_stamp(str(outside))


def test_oss_stamp_ignores_temporary_signed_query(local_media, monkeypatch):
    monkeypatch.setattr(media.storage, "source_metadata", lambda key: {"etag": "ABCDEF", "size_bytes": 50})
    first = media.source_stamp("https://test-bucket.oss-cn-hangzhou.aliyuncs.com/kepu/generated/p1/a.mp4?Expires=1")
    second = media.source_stamp("https://test-bucket.oss-cn-hangzhou.aliyuncs.com/kepu/generated/p1/a.mp4?Expires=2")
    assert first["key"] == "kepu/generated/p1/a.mp4"
    assert media.stamp_version(first) == media.stamp_version(second)
    cdn = media.source_stamp("https://media.example.test/assets/kepu/generated/p1/a.mp4?signature=hidden")
    assert media.stamp_version(first) == media.stamp_version(cdn)


def test_old_folder_oss_url_uses_local_file_when_present(local_media, monkeypatch):
    """存储目录已改名时，旧 OSS 地址仍优先使用磁盘上的成片。"""
    static, _cache, _uploaded, settings = local_media
    settings.oss_folder = "printfilm"
    source = static / "generated" / "p1" / "a.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"local-video")
    monkeypatch.setattr(media.storage, "source_metadata", lambda key: (_ for _ in ()).throw(AssertionError(key)))
    stamp = media.source_stamp("https://test-bucket.oss-cn-hangzhou.aliyuncs.com/kepu/generated/p1/a.mp4")
    assert stamp["kind"] == "local"
    assert Path(stamp["locator"]) == source.resolve()


def test_old_folder_oss_object_is_used_when_local_file_missing(local_media, monkeypatch):
    """本地成片已不在时，仍从当前桶按原始对象键复制，不要求目录名是现在的 oss_folder。"""
    _static, _cache, _uploaded, settings = local_media
    settings.oss_folder = "printfilm"
    monkeypatch.setattr(media.storage, "source_metadata", lambda key: {"etag": "E", "size_bytes": 12})
    stamp = media.source_stamp("https://test-bucket.oss-cn-hangzhou.aliyuncs.com/kepu/generated/p1/a.mp4")
    assert stamp["kind"] == "oss" and stamp["key"] == "kepu/generated/p1/a.mp4"


@pytest.mark.asyncio
async def test_source_change_is_rejected_before_upload(local_media):
    static, cache, uploaded, _settings = local_media
    source = static / "demo.mp4"
    source.write_bytes(b"first")
    stamp = media.source_stamp("/static/demo.mp4")
    source.write_bytes(b"new source")
    snapshot = {"schema_version": 2, "clips": [{"id": 1, "sort_order": 0, "locator": "/static/demo.mp4", "stamp": stamp}]}
    with pytest.raises(ValueError, match="MARKETPLACE_SOURCE_CHANGED"):
        await media.prepare_drama_video(snapshot, "marketplace/test/episode.mp4")
    assert not uploaded.exists()
    assert not list(cache.iterdir())


async def _clip(settings, path, color, size="160x90", duration=0.6, audio=False, sar="1:1"):
    """生成用于真实 FFmpeg 拼接回归的短分镜。"""
    if not Path(settings.ffmpeg_path).is_file() and not shutil.which(settings.ffmpeg_path):
        pytest.skip("FFmpeg is not available")
    args = [settings.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=10:d={duration}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=1000:sample_rate=48000:duration={duration}", "-c:a", "aac", "-ar", "48000", "-ac", "2"]
    else:
        args += ["-an"]
    await media.command(*args, "-vf", f"setsar={sar.replace(':', '/')}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "10", "-g", "10", "-crf", "18",
        "-video_track_timescale", "90000", "-t", str(duration), str(path), timeout=30)


def _snapshot(static, paths):
    return {"schema_version": 2, "clips": [{"id": i + 1, "sort_order": i,
        "locator": "/static/" + path.relative_to(static).as_posix(),
        "stamp": media.source_stamp("/static/" + path.relative_to(static).as_posix())} for i, path in enumerate(paths)]}


async def _pixel(settings, path, time):
    raw = await media.command(settings.ffmpeg_path, "-v", "error", "-ss", str(time), "-i", str(path),
        "-vf", "scale=1:1", "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-", timeout=30)
    return tuple(raw[:3])


@pytest.mark.asyncio
async def test_three_color_full_episode_preserves_order_and_duration(local_media, monkeypatch):
    static, cache, uploaded, settings = local_media
    paths = [static / f"clip-{i}.mp4" for i in range(3)]
    for path, color, duration in zip(paths, ("red", "lime", "blue"), (0.6, 0.7, 0.8)):
        await _clip(settings, path, color, duration=duration)
    async def forbidden(*_args):
        raise AssertionError("compatible clips must use lossless concatenation")
    monkeypatch.setattr(media, "_encode", forbidden)
    phases = []
    async def progress(phase):
        phases.append(phase)
    result = await media.prepare_drama_video(_snapshot(static, paths), "marketplace/test/full.mp4", progress)
    assert result["duration_seconds"] == pytest.approx(2.1, abs=0.15)
    assert result["fingerprint"] == media.fingerprint(uploaded)
    assert result["size_bytes"] == uploaded.stat().st_size
    assert phases == ["copying", "composing", "validating"]
    for index, time in enumerate((0.2, 0.9, 1.7)):
        pixel = await _pixel(settings, uploaded, time)
        assert pixel[index] > 180 and all(value < 60 for other, value in enumerate(pixel) if other != index)
    assert not list(cache.iterdir())


@pytest.mark.asyncio
async def test_mixed_sizes_and_audio_use_highest_source_resolution(local_media):
    static, cache, uploaded, settings = local_media
    paths = [static / f"clip-{i}.mp4" for i in range(3)]
    for path, color, size, duration, audio in zip(paths, ("red", "lime", "blue"), ("160x90", "320x180", "160x90"),
                                               (0.6, 0.7, 0.8), (False, True, False)):
        await _clip(settings, path, color, size=size, duration=duration, audio=audio)
    result = await media.prepare_drama_video(_snapshot(static, paths), "marketplace/test/full.mp4")
    info = await media._probe(uploaded)
    assert (info["width"], info["height"]) == (320, 180)
    assert info["audio"]
    assert result["duration_seconds"] == pytest.approx(2.1, abs=0.15)
    for index, time in enumerate((0.2, 0.9, 1.7)):
        pixel = await _pixel(settings, uploaded, time)
        assert pixel[index] > 180 and all(value < 60 for other, value in enumerate(pixel) if other != index)
    volumes = []
    for time in (0.2, 0.9, 1.7):
        raw = await media.command(settings.ffmpeg_path, "-v", "error", "-ss", str(time), "-i", str(uploaded),
            "-t", "0.1", "-vn", "-ac", "1", "-f", "f32le", "-", timeout=30)
        samples = struct.unpack("<" + "f" * (len(raw) // 4), raw)
        volumes.append(max(abs(value) for value in samples))
    assert volumes[1] > 0.05
    assert volumes[0] < 0.005 and volumes[2] < 0.005
    assert not list(cache.iterdir())


@pytest.mark.asyncio
async def test_small_landscape_ratio_difference_pads_without_stretching_or_cropping(local_media):
    """真实832/854宽度兼容：完整画面等比居中补边，镜序、时长及源文件不变。"""
    static, cache, uploaded, settings = local_media
    narrow, wide = static / "narrow.mp4", static / "wide.mp4"
    # 图案和四边标记能检出拉伸或裁切，避免纯色测试误判画面保真。
    pattern = (
        "testsrc2=s=832x480:r=10:d=0.6,"
        "drawbox=x=0:y=0:w=8:h=ih:color=yellow:t=fill,"
        "drawbox=x=iw-8:y=0:w=8:h=ih:color=magenta:t=fill,"
        "drawbox=x=0:y=0:w=iw:h=8:color=white:t=fill,"
        "drawbox=x=0:y=ih-8:w=iw:h=8:color=cyan:t=fill"
    )
    await media.command(settings.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i", pattern,
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "10", "-g", "10", "-crf", "18",
        "-video_track_timescale", "90000", str(narrow), timeout=30)
    await _clip(settings, wide, "blue", size="854x480", duration=0.7)
    originals = {path: media.fingerprint(path) for path in (narrow, wide)}

    result = await media.prepare_drama_video(_snapshot(static, [narrow, wide]), "marketplace/test/padded.mp4")
    info = await media._probe(uploaded)
    assert (info["width"], info["height"]) == (854, 480)
    assert info["video"]["sample_aspect_ratio"] == "1:1"
    assert result["duration_seconds"] == pytest.approx(1.3, abs=0.15)

    frames = []
    for path in (narrow, uploaded):
        frames.append(await media.command(settings.ffmpeg_path, "-v", "error", "-ss", "0.2", "-i", str(path),
            "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-", timeout=30))
    original, composed = frames
    assert len(original) == 832 * 480 * 3
    assert len(composed) == 854 * 480 * 3
    # 黑边左右差最多2px，兼容yuv420p对奇数居中坐标的色度对齐。
    for x in (1, 852):
        pixel = composed[(240 * 854 + x) * 3:(240 * 854 + x + 1) * 3]
        assert max(pixel) < 20
    errors = {}
    for left in (10, 11, 12):
        cropped = b"".join(composed[(row * 854 + left) * 3:(row * 854 + left + 832) * 3] for row in range(480))
        errors[left] = sum(abs(a - b) for a, b in zip(original, cropped)) / len(original)
    # 有效区与原始解码帧逐像素比对；仅允许高质量二次编码的小幅误差。
    assert min(errors.values()) < 5, errors
    blue = await _pixel(settings, uploaded, 0.9)
    assert blue[2] > 180 and blue[0] < 60 and blue[1] < 60
    assert {path: media.fingerprint(path) for path in (narrow, wide)} == originals
    assert not list(cache.iterdir())


@pytest.mark.asyncio
async def test_single_clip_is_not_reencoded(local_media, monkeypatch):
    static, _cache, uploaded, settings = local_media
    source = static / "single.mp4"
    await _clip(settings, source, "red", size="320x180")
    async def forbidden(*_args):
        raise AssertionError("single clip must not be encoded")
    monkeypatch.setattr(media, "_encode", forbidden)
    await media.prepare_drama_video(_snapshot(static, [source]), "marketplace/test/single.mp4")
    before, after = await media._probe(source), await media._probe(uploaded)
    assert before["video"]["extradata"] == after["video"]["extradata"]
    assert (after["width"], after["height"]) == (320, 180)


@pytest.mark.asyncio
async def test_different_aspect_ratios_fail_without_upload(local_media):
    static, cache, uploaded, settings = local_media
    paths = [static / "portrait.mp4", static / "landscape.mp4"]
    await _clip(settings, paths[0], "red", size="90x160")
    await _clip(settings, paths[1], "blue", size="160x90")
    with pytest.raises(ValueError, match="MARKETPLACE_SOURCE_INCOMPATIBLE") as error:
        await media.prepare_drama_video(_snapshot(static, paths), "marketplace/test/invalid.mp4")
    assert "第1镜（分镜编号1，90×160，显示9:16）" in str(error.value)
    assert "第2镜（分镜编号2，160×90，显示16:9）" in str(error.value)
    assert not uploaded.exists()
    assert not list(cache.iterdir())


@pytest.mark.asyncio
async def test_four_by_three_and_widescreen_still_fail_without_upload(local_media):
    """小偏差补边不能放行明显不同的4:3和16:9横屏画幅。"""
    static, cache, uploaded, settings = local_media
    paths = [static / "four-three.mp4", static / "widescreen.mp4"]
    await _clip(settings, paths[0], "red", size="320x240")
    await _clip(settings, paths[1], "blue", size="320x180")
    with pytest.raises(ValueError, match="MARKETPLACE_SOURCE_INCOMPATIBLE") as error:
        await media.prepare_drama_video(_snapshot(static, paths), "marketplace/test/incompatible.mp4")
    assert "显示4:3" in str(error.value) and "显示16:9" in str(error.value)
    assert not uploaded.exists()
    assert not list(cache.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("rotation", [0, 90])
async def test_sar_sources_keep_display_aspect_without_extra_borders(local_media, rotation):
    """真实编码验证：等效画幅可合成，非方形像素不会被压窄或额外补黑边。"""
    static, cache, uploaded, settings = local_media
    source = static / "sar.mp4"
    await _clip(settings, source, "red", size="180x144", sar="16:15")
    if rotation:
        rotated = static / "rotated.mp4"
        await media.command(settings.ffmpeg_path, "-y", "-v", "error", "-display_rotation", str(rotation),
            "-i", str(source), "-c", "copy", str(rotated), timeout=30)
        source = rotated
    peer = static / "peer.mp4"
    dimensions = (144, 192) if rotation else (192, 144)
    await _clip(settings, peer, "blue", size=f"{dimensions[0]}x{dimensions[1]}")
    before = media.fingerprint(source)
    await media.prepare_drama_video(_snapshot(static, [source, peer]), "marketplace/test/sar-full.mp4")
    output = await media._probe(uploaded)
    assert media._dimensions(output) == dimensions
    assert output["video"]["sample_aspect_ratio"] == "1:1"
    raw = await media.command(settings.ffmpeg_path, "-v", "error", "-ss", "0.2", "-i", str(uploaded),
        "-vf", "crop=2:2:0:0,scale=1:1", "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-", timeout=30)
    assert raw[0] > 180 and raw[1] < 60 and raw[2] < 60
    assert media.fingerprint(source) == before
    assert not list(cache.iterdir())


@pytest.mark.asyncio
async def test_project_video_cover_extracts_first_frame_and_normalizes_display_shape(local_media, monkeypatch, tmp_path):
    """项目卡片以视频首帧展示时，生成相同画幅的独立 PNG，不返回源视频充当图片。"""
    static, cache, _uploaded, settings = local_media
    source = static / "cover-video.mp4"
    await _clip(settings, source, "blue", size="180x144", sar="16:15")
    captured = tmp_path / "cover.png"
    def upload(key, path, content_type):
        assert key == "marketplace/test/cover.png" and content_type == "image/png"
        assert cache in path.parents
        shutil.copyfile(path, captured)
    monkeypatch.setattr(media.storage, "upload", upload)
    # 模拟视频大于图片上传上限；来源仍按视频上限检查，输出按图片上限检查。
    original_limits = media.get_marketplace_settings()
    limits = original_limits.model_copy(update={"max_document_bytes": 1000})
    monkeypatch.setattr(media, "get_marketplace_settings", lambda: limits)
    assert source.stat().st_size > limits.max_document_bytes
    before = media.fingerprint(source)
    result = await media.prepare_drama_cover("/static/cover-video.mp4", "marketplace/test/cover.png")
    assert (result["width"], result["height"]) == (192, 144)
    assert result["fingerprint"] == media.fingerprint(captured)
    pixel = await _pixel(settings, captured, 0)
    assert pixel[2] > 180 and pixel[0] < 60 and pixel[1] < 60
    assert media.fingerprint(source) == before
    assert not list(cache.iterdir())


@pytest.mark.asyncio
async def test_cover_uses_private_copy_and_validates_image(local_media, monkeypatch):
    static, cache, _uploaded, settings = local_media
    source = static / "cover.png"
    await media.command(settings.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=120x80",
        "-frames:v", "1", str(source), timeout=30)
    captured = {}
    def upload(key, path, content_type):
        captured.update(key=key, content_type=content_type, size=path.stat().st_size)
        assert cache in path.parents
    monkeypatch.setattr(media.storage, "upload", upload)
    stamp = media.source_stamp("/static/cover.png")
    result = await media.prepare_drama_cover("/static/cover.png", "marketplace/test/cover.png", stamp)
    assert (result["width"], result["height"]) == (120, 80)
    assert captured["content_type"] == "image/png"
    assert captured["size"] == result["size_bytes"]
    assert not list(cache.iterdir())


@pytest.mark.asyncio
async def test_invalid_cover_does_not_upload(local_media):
    static, cache, uploaded, _settings = local_media
    (static / "fake.png").write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError, match="MARKETPLACE_SOURCE_NOT_READY"):
        await media.prepare_drama_cover("/static/fake.png", "marketplace/test/cover.png")
    assert not uploaded.exists()
    assert not list(cache.iterdir())
