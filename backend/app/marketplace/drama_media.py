"""只读漫剧来源，独立制作市场成片；不调用原漫剧合成或公开发布函数。"""
from __future__ import annotations

import asyncio
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import tempfile
from urllib.parse import unquote, urlparse

from app.config import get_settings
from app.services.storage import STATIC_ROOT
from . import storage
from .config import get_marketplace_settings
from .drama_geometry import display_dimensions as _dimensions, fit_dimensions, validate_aspects
from .worker import cache_root, command, fingerprint

_FORMATS = "mov,mp4,matroska,webm"
_VIDEO_FIELDS = ("codec_name", "profile", "level", "codec_tag_string", "width", "height", "pix_fmt",
                 "sample_aspect_ratio", "r_frame_rate", "avg_frame_rate", "time_base", "field_order",
                 "color_range", "color_space", "color_transfer", "color_primaries", "extradata")
_AUDIO_FIELDS = ("codec_name", "profile", "codec_tag_string", "sample_rate", "channels", "channel_layout",
                 "sample_fmt", "time_base", "extradata")


def _error(code: str, message: str) -> ValueError:
    return ValueError(f"MARKETPLACE_{code}:{message}")


def _local_source(locator: str) -> Path | None:
    """仅解释本站 static URL 或 static 根内的绝对路径，不根据任意远程路径猜本地文件。"""
    text = locator.strip()
    raw = ""
    if text.startswith("/static/"):
        raw = unquote(text[len("/static/"):].split("?", 1)[0])
    elif text.startswith(("http://", "https://")):
        parsed, base = urlparse(text), urlparse(get_settings().public_base_url.rstrip("/"))
        prefix = base.path.rstrip("/") + "/static/"
        if parsed.scheme == base.scheme and parsed.netloc == base.netloc and parsed.path.startswith(prefix):
            raw = unquote(parsed.path[len(prefix):])
        else:
            return None
    else:
        candidate = Path(text)
        if not candidate.is_absolute():
            return None
        path = candidate.resolve()
        try:
            path.relative_to(STATIC_ROOT.resolve())
        except ValueError as exc:
            raise _error("SOURCE_NOT_READY", "不允许读取项目媒体目录之外的文件") from exc
        return path
    if not raw or "\\" in raw or ".." in Path(raw).parts:
        raise _error("SOURCE_NOT_READY", "源视频路径无效")
    path = (STATIC_ROOT / raw).resolve()
    try:
        path.relative_to(STATIC_ROOT.resolve())
    except ValueError as exc:
        raise _error("SOURCE_NOT_READY", "源视频路径超出项目媒体目录") from exc
    return path


def _source_key(locator: str) -> str:
    """只接受当前配置的 OSS 桶或 CDN。目录名可以和现在的 oss_folder 不同。"""
    settings = get_settings()
    text = locator.strip()
    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        if parsed.username or parsed.password or parsed.fragment:
            raise _error("SOURCE_NOT_READY", "源视频地址无效")
        endpoint = urlparse(settings.oss_endpoint if "://" in settings.oss_endpoint else "https://" + settings.oss_endpoint)
        endpoint_host = (endpoint.hostname or "").lower()
        hosts = {f"{settings.oss_bucket}.{endpoint_host}"}
        if "-internal" in endpoint_host:
            hosts.add(f"{settings.oss_bucket}.{endpoint_host.replace('-internal', '')}")
        public = urlparse(settings.oss_public_base.rstrip("/")) if settings.oss_public_base else None
        if public and parsed.scheme == public.scheme and parsed.netloc == public.netloc:
            base_path = public.path.rstrip("/") + "/"
            if not parsed.path.startswith(base_path):
                raise _error("SOURCE_NOT_READY", "源视频不属于配置的媒体目录")
            key = unquote(parsed.path[len(base_path):])
        elif parsed.scheme == "https" and parsed.hostname in hosts and parsed.port in (None, 443):
            key = unquote(parsed.path.lstrip("/"))
        else:
            raise _error("SOURCE_NOT_READY", "源视频不属于配置的 OSS 桶")
    else:
        key = text
    if not settings.oss_bucket or not key or "\\" in key or ".." in key.split("/") or "?" in key or "#" in key:
        raise _error("SOURCE_NOT_READY", "源视频不属于当前 OSS")
    return key


def _generated_local(locator: str) -> Path | None:
    """当前 OSS 或 CDN 地址若能对上 static 里已有的 generated 文件，就当本地成片。"""
    text = locator.strip()
    if not text.startswith(("http://", "https://")):
        return None
    try:
        key = _source_key(text)
    except ValueError:
        return None
    parts = key.split("/")
    if "generated" not in parts:
        return None
    rest = "/".join(parts[parts.index("generated"):])
    path = (STATIC_ROOT / rest).resolve()
    try:
        path.relative_to(STATIC_ROOT.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _local_stamp(path: Path) -> dict:
    """读取本地成片的大小和指纹。文件在读取过程中变化则要求重新选择。"""
    before = _stat_stamp(path)
    digest = fingerprint(path)
    if before != _stat_stamp(path):
        raise _error("SOURCE_CHANGED", "源视频正在更新，请稍后重新选择")
    return {"kind": "local", "locator": str(path), **before, "fingerprint": digest}


def _stat_stamp(path: Path) -> dict:
    if not path.is_file():
        raise _error("SOURCE_NOT_READY", "源视频文件不存在")
    stat = path.stat()
    return {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "file_id": f"{stat.st_dev}:{stat.st_ino}"}


def source_stamp(locator: str) -> dict:
    """冻结源文件版本，结果仅保存在服务端，不向浏览器暴露文件路径或对象键。"""
    text = (locator or "").strip()
    if not text:
        raise _error("SOURCE_NOT_READY", "分镜视频尚未生成")
    local = _local_source(text)
    if local is None:
        local = _generated_local(text)
    if local is not None:
        result = _local_stamp(local)
    else:
        key = _source_key(text)
        result = {"kind": "oss", "locator": key, "key": key, **storage.source_metadata(key)}
    if not 0 < result["size_bytes"] <= get_marketplace_settings().max_video_bytes:
        raise _error("SOURCE_NOT_READY", "源视频为空或超过市场视频大小限制")
    return result


def stamp_version(stamp: dict) -> str:
    """签名 URL 过期时间不参与版本；只散列安全解析后的地址和文件身份。"""
    payload = {key: stamp.get(key) for key in ("kind", "locator", "key", "size_bytes", "mtime_ns", "file_id", "etag", "fingerprint")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def _thread(function, *args):
    """取消任务时先等待本地文件操作结束，再清理临时目录。"""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


def _copy_source(clip: dict, output: Path) -> None:
    expected = clip.get("stamp") or {}
    current = source_stamp(str(clip.get("locator") or ""))
    if stamp_version(current) != stamp_version(expected):
        raise _error("SOURCE_CHANGED", "源视频已更新，请重新选择分集")
    if current["kind"] == "local":
        digest = hashlib.sha256()
        with Path(current["locator"]).open("rb") as source, output.open("wb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                target.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != current["fingerprint"]:
            raise _error("SOURCE_CHANGED", "复制过程中源视频发生变化")
    else:
        storage.download_version(current["key"], output, current["etag"])
    after = source_stamp(str(clip["locator"]))
    if stamp_version(after) != stamp_version(expected) or output.stat().st_size != expected["size_bytes"]:
        raise _error("SOURCE_CHANGED", "复制过程中源视频发生变化")


async def _probe(path: Path) -> dict:
    settings = get_settings()
    try:
        probe = json.loads(await command(settings.ffprobe_path, "-v", "error", "-protocol_whitelist", "file,pipe",
            "-format_whitelist", _FORMATS, "-show_streams", "-show_format", "-show_data", "-of", "json", str(path), timeout=60))
        video = next(stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic"))
        duration = float(probe.get("format", {}).get("duration", 0))
        width, height = int(video["width"]), int(video["height"])
        if width < 2 or height < 2 or width * height > 50_000_000 or not math.isfinite(duration) or duration <= 0:
            raise ValueError("invalid media")
        audio = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), None)
        return {"video": video, "audio": audio, "duration": duration, "width": width, "height": height}
    except (ValueError, KeyError, StopIteration) as exc:
        raise _error("SOURCE_NOT_READY", "分镜视频无法解析或尺寸无效") from exc


def _signature(info: dict) -> tuple:
    video, audio = info["video"], info["audio"]
    return (tuple(video.get(key) for key in _VIDEO_FIELDS), tuple(audio.get(key) for key in _AUDIO_FIELDS) if audio else None,
            video.get("side_data_list", []), video.get("tags", {}).get("rotate"))


async def _concat(paths: list[Path], output: Path, timeout: float) -> None:
    listing = output.with_suffix(".txt")
    listing.write_text("\n".join(f"file '{path.name}'" for path in paths), encoding="utf-8")
    await command(get_settings().ffmpeg_path, "-y", "-v", "error", "-protocol_whitelist", "file,pipe", "-f", "concat",
        "-safe", "1", "-i", str(listing), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-c", "copy",
        "-movflags", "+faststart", str(output), timeout=timeout)


async def _encode(paths: list[Path], infos: list[dict], output: Path, timeout: float) -> None:
    """保持显示比例与最大源尺寸，等比补边兼容小幅尺寸偏差并统一编码。"""
    sizes = [_dimensions(info) for info in infos]
    width = math.ceil(max(size[0] for size in sizes) / 2) * 2
    height = math.ceil(max(size[1] for size in sizes) / 2) * 2
    if width * height > 50_000_000:
        raise _error("SOURCE_INCOMPATIBLE", "合成画面尺寸超出限制")
    fps = Fraction(1, 1)
    for info in infos:
        try:
            value = Fraction(info["video"].get("avg_frame_rate") or info["video"].get("r_frame_rate") or "30")
        except (ValueError, ZeroDivisionError):
            value = Fraction(30, 1)
        fps = max(fps, value)
    if fps > 240:
        raise _error("SOURCE_INCOMPATIBLE", "分镜帧率超出支持范围")
    audio = any(info["audio"] for info in infos)
    normalized = []
    for index, (source, info) in enumerate(zip(paths, infos)):
        dest = output.parent / f"normalized-{index:04d}.mp4"
        args = [get_settings().ffmpeg_path, "-y", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", _FORMATS, "-i", str(source)]
        if audio and not info["audio"]:
            args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        args += ["-map", "0:v:0"]
        if audio:
            args += ["-map", "0:a:0" if info["audio"] else "1:a:0", "-af",
                     f"aresample=48000:async=1:first_pts=0,apad,atrim=duration={info['duration']}",
                     "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        # 模型实际尺寸略有偏差时等比补边，避免裁切或拉伸人物画面。
        fit_width, fit_height = fit_dimensions(info, width, height)
        args += ["-sn", "-dn", "-t", str(info["duration"]), "-vf",
                 f"scale={fit_width}:{fit_height}:flags=lanczos,setsar=1,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setpts=PTS-STARTPTS", "-r", str(fps),
                 "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-threads", "2", "-video_track_timescale", "90000", "-movflags", "+faststart", str(dest)]
        await command(*args, timeout=timeout)
        normalized.append(dest)
    await _concat(normalized, output, timeout)


async def prepare_drama_video(snapshot: dict, dest_key: str, progress=None) -> dict:
    """制作全部分镜的独立成片，上传成功后才返回可绑定的媒体元数据。"""
    if snapshot.get("schema_version") != 2 or not snapshot.get("clips"):
        raise _error("SOURCE_NOT_READY", "漫剧来源快照无效，请重新选择分集")
    if not dest_key.startswith("marketplace/") or ".." in dest_key.split("/") or "\\" in dest_key:
        raise _error("SOURCE_NOT_READY", "市场目标目录无效")
    clips = list(snapshot["clips"])
    if clips != sorted(clips, key=lambda clip: (clip["sort_order"], clip["id"])) or len({clip["id"] for clip in clips}) != len(clips):
        raise _error("SOURCE_NOT_READY", "分镜顺序快照无效")
    settings = get_marketplace_settings()
    if sum(int((clip.get("stamp") or {}).get("size_bytes", 0)) for clip in clips) > settings.max_video_bytes:
        raise _error("SOURCE_NOT_READY", "整集视频超过市场视频大小限制")
    async def phase(value):
        if progress:
            await progress(value)
    with tempfile.TemporaryDirectory(prefix="job-", dir=cache_root()) as directory:
        root = Path(directory)
        await phase("copying")
        sources, infos = [], []
        for index, clip in enumerate(clips):
            source = root / f"source-{index:04d}.mp4"
            await _thread(_copy_source, clip, source)
            sources.append(source)
            infos.append(await _probe(source))
        total = sum(info["duration"] for info in infos)
        if total > settings.max_duration_seconds:
            raise _error("SOURCE_NOT_READY", "整集视频超过市场视频时长限制")
        output = root / "episode.mp4"
        timeout = min(7200, max(120, total * 8 + 60))
        await phase("composing")
        if len(sources) == 1:
            # 单镜头只重新封装，不重新编码或降低画质。
            try:
                await command(get_settings().ffmpeg_path, "-y", "-v", "error", "-protocol_whitelist", "file,pipe",
                    "-format_whitelist", _FORMATS, "-i", str(sources[0]), "-map", "0:v:0", "-map", "0:a:0?",
                    "-sn", "-dn", "-c", "copy", "-movflags", "+faststart", str(output), timeout=timeout)
            except ValueError as exc:
                raise _error("SOURCE_INCOMPATIBLE", "分镜编码无法无损封装为市场视频") from exc
        else:
            validate_aspects(infos, clips)
            compatible = all(_signature(info) == _signature(infos[0]) for info in infos[1:])
            copied = False
            if compatible:
                try:
                    await _concat(sources, output, timeout)
                    combined = await _probe(output)
                    copied = abs(combined["duration"] - total) <= max(0.25, total * 0.002)
                except ValueError:
                    copied = False
            if not copied:
                await _encode(sources, infos, output, timeout)
        await phase("validating")
        result = await _probe(output)
        if abs(result["duration"] - total) > max(0.25, total * 0.002):
            raise _error("SOURCE_INCOMPATIBLE", "整集合成时长与分镜总时长不一致")
        size = output.stat().st_size
        if not 0 < size <= settings.max_video_bytes:
            raise _error("SOURCE_NOT_READY", "完整成片超过市场视频大小限制")
        if result["duration"] > settings.max_duration_seconds:
            raise _error("SOURCE_NOT_READY", "完整成片超过市场视频时长限制")
        try:
            width, height = _dimensions(result)
        except ValueError as exc:
            raise _error("SOURCE_INCOMPATIBLE", "成片旋转角度不受支持，请先导出为标准横屏或竖屏视频") from exc
        digest = await _thread(fingerprint, output)
        await _thread(storage.upload, dest_key, output, "video/mp4")
        return {"size_bytes": size, "content_type": "video/mp4", "fingerprint": digest, "duration_seconds": result["duration"],
                "width": width, "height": height}


async def prepare_drama_cover(locator: str, dest_key: str, stamp: dict | None = None) -> dict:
    """安全复制项目封面；卡片以视频展示时取首帧，统一保存为市场私有 PNG。"""
    if not dest_key.startswith("marketplace/") or ".." in dest_key.split("/") or "\\" in dest_key:
        raise _error("SOURCE_NOT_READY", "市场封面目标目录无效")
    expected = stamp if stamp is not None else await _thread(source_stamp, locator)
    limits = get_marketplace_settings()
    if not 0 < int(expected.get("size_bytes", 0)) <= limits.max_video_bytes:
        raise _error("SOURCE_NOT_READY", "源封面为空或超过媒体大小限制")
    with tempfile.TemporaryDirectory(prefix="job-", dir=cache_root()) as directory:
        root = Path(directory)
        source, output = root / "cover-source", root / "cover.png"
        await _thread(_copy_source, {"locator": locator, "stamp": expected}, source)
        try:
            formats = "png_pipe,jpeg_pipe,webp_pipe,image2," + _FORMATS
            probe = json.loads(await command(get_settings().ffprobe_path, "-v", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", formats, "-show_streams", "-show_format", "-of", "json", str(source), timeout=60))
            image = next(stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"
                         and not stream.get("disposition", {}).get("attached_pic"))
            width, height = int(image["width"]), int(image["height"])
            video_source = bool(set(probe.get("format", {}).get("format_name", "").split(",")) & set(_FORMATS.split(",")))
            if min(width, height) < 2 or width * height > 50_000_000:
                raise ValueError("invalid image")
            if not video_source and (image.get("codec_name") not in ("png", "mjpeg", "webp")
                                     or expected["size_bytes"] > limits.max_document_bytes):
                raise ValueError("invalid image")
            if video_source:
                duration = float(probe.get("format", {}).get("duration", 0))
                if not math.isfinite(duration) or not 0 < duration <= limits.max_duration_seconds:
                    raise ValueError("invalid video")
            width, height = _dimensions({"video": image, "width": width, "height": height})
            if width * height > 50_000_000:
                raise ValueError("invalid display size")
            await command(get_settings().ffmpeg_path, "-y", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", formats, "-i", str(source), "-map", f"0:{image['index']}", "-an", "-sn", "-dn",
                "-vf", f"scale={width}:{height}:flags=lanczos,setsar=1", "-frames:v", "1", str(output), timeout=60)
        except (ValueError, KeyError, StopIteration) as exc:
            raise _error("SOURCE_NOT_READY", "源封面不是有效图片或项目视频，请重新上传封面") from exc
        size = output.stat().st_size
        if not 0 < size <= get_marketplace_settings().max_document_bytes:
            raise _error("SOURCE_NOT_READY", "处理后的封面超过图片大小限制")
        digest = await _thread(fingerprint, output)
        await _thread(storage.upload, dest_key, output, "image/png")
        return {"size_bytes": size, "content_type": "image/png", "fingerprint": digest, "width": width, "height": height}
