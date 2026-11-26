"""离线完整模式验收：参考图生图 → 图片生有声视频 → 真正的 FFmpeg 成片。"""
from __future__ import annotations

import json
import shutil
import subprocess
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.config import get_settings
from app.models import Project, ProjectStatus, Shot, ShotStatus
from app.services import ffmpeg_compose, pipeline, storage


def _run(command):
    """运行本机媒体工具；失败时保留简短诊断。"""
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


async def test_full_reference_images_to_native_audio_videos_and_playable_vertical_final(monkeypatch, tmp_path):
    """全链路保留画风/主体/镜间参考；素材、音轨和成片均为临时目录内真实文件。"""
    settings = get_settings()
    ffmpeg = shutil.which(settings.ffmpeg_path) or shutil.which("ffmpeg")
    ffprobe = shutil.which(settings.ffprobe_path) or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe or not ffmpeg_compose._find_cjk_font():
        pytest.skip("real full-media acceptance requires FFmpeg, ffprobe and a Chinese font")
    for key, value in {"ark_mock": True, "kepu_seedance_native_audio": True, "ffmpeg_path": ffmpeg,
                       "ffprobe_path": ffprobe, "public_base_url": "https://media.example.com"}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(storage, "STATIC_ROOT", tmp_path / "static")
    monkeypatch.setattr(storage, "GENERATED_ROOT", tmp_path / "static/generated")
    monkeypatch.setattr("app.services.oss.oss_enabled", lambda: False)
    network = AsyncMock(side_effect=AssertionError("full-media acceptance must stay offline"))
    monkeypatch.setattr(httpx.AsyncClient, "send", network)
    monkeypatch.setattr(pipeline, "resolve_bgm_path", lambda _mood: None)
    monkeypatch.setattr(pipeline, "_ensure_not_cancelled", AsyncMock())
    for name in ("publish_progress", "_record_seedream_usage", "_record_seedance_usage"):
        monkeypatch.setattr(pipeline, name, AsyncMock())
    external_tts = AsyncMock(side_effect=AssertionError("native-audio mode must not synthesize external TTS"))
    monkeypatch.setattr(pipeline, "_synthesize_continuous_audio", external_tts)

    style = storage.project_dir(98784) / "style.png"
    _run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=144x256:rate=1", "-frames:v", "1", str(style)])
    style_url = storage.publish_local(style)
    template = SimpleNamespace(
        id="anim_3d", style_prefix="统一三维卡通画风", preview_cover=style_url, negative_prompt="模糊",
        seedream_config={"consistency_mode": "character"}, seedance_config={"character_consistency": True},
        audio_config={}, subtitle_config={}, default_ratio="9:16",
    )
    shots = [SimpleNamespace(
        id=no, shot_no=no, duration=4, narration=text, img_prompt="三维角色观察天空",
        video_prompt="@duration:4 同一个角色讲解", segment_script="@duration:4 同一个角色讲解",
        image_url=None, image_ark_url=None, audio_url=None, video_url=None, last_frame_url=None,
        video_skip_reason=None, camera="push-in", bgm_mood="", status=ShotStatus.PENDING,
    ) for no, text in enumerate(("阳光遇到空气。", "天空呈现蓝色。"), 1)]
    subject = storage.to_public_url(style_url)
    project = SimpleNamespace(
        id=98784, user_id=1, pipeline_mode="full", template=template, shots=shots,
        ref_image_url=subject, character_bible="同一个三维卡通角色", style_prompt="统一三维卡通画风",
        voice_id="", image_model="seedream-5.0-pro", video_model="seedance-2.5", image_resolution="2K",
        video_resolution="720p", output_ratio="9:16", resolution_mode="preview", progress=15,
        status=ProjectStatus.SCRIPT_READY, final_video_url=None,
    )
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one=lambda: project)),
                         commit=AsyncMock(), add=Mock())

    async def get_row(model, row_id):
        """持久化替身仅回读本用例的项目与分镜。"""
        return project if model is Project else next(shot for shot in shots if shot.id == row_id)

    @asynccontextmanager
    async def session():
        """隔离数据库，同时让实际阶段逻辑写回同一组素材。"""
        yield db

    db.get = AsyncMock(side_effect=get_row)
    monkeypatch.setattr(pipeline, "AsyncSessionLocal", session)
    image_inputs, video_inputs = [], []

    async def image(prompt, negative, refs, **kwargs):
        """本地图片替代生图模型，并记录画风、主体和镜间参考。"""
        image_inputs.append((prompt, refs, kwargs))
        path = storage.project_dir(project.id) / f"frame_{kwargs['shot_no']}.png"
        shutil.copyfile(style, path)
        return SimpleNamespace(local_url=storage.publish_local(path), remote_url=None)

    async def video(image_ref, prompt, duration, **kwargs):
        """从本镜静帧做缩放动画并合成有声音轨，替代云端图生视频。"""
        video_inputs.append((image_ref, kwargs))
        path = storage.project_dir(project.id) / f"video_{kwargs['shot_no']}.mp4"
        _run([ffmpeg, "-y", "-loop", "1", "-framerate", "12", "-i", str(storage.local_path_from_url(image_ref)),
              "-f", "lavfi", "-i", f"sine=frequency={440 + kwargs['shot_no'] * 100}:sample_rate=24000",
              "-vf", "zoompan=z='min(zoom+0.004,1.5)':d=1:s=144x256:fps=12", "-t", str(duration),
              "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)])
        tail = path.with_name(f"tail_{kwargs['shot_no']}.png")
        _run([ffmpeg, "-y", "-sseof", "-0.1", "-i", str(path), "-frames:v", "1", str(tail)])
        return storage.publish_local(path), SimpleNamespace(last_frame_url=storage.publish_local(tail))

    gateway = SimpleNamespace(gen_image=image, gen_and_wait_video=video,
                              tts=AsyncMock(side_effect=AssertionError("external TTS forbidden")))
    monkeypatch.setattr(pipeline, "get_ark", lambda: gateway)

    await pipeline._parallel_image_and_audio(project.id)
    assert project.status == ProjectStatus.IMAGE_READY
    assert all(call[2]["style_ref_urls"] == [style_url] for call in image_inputs)
    assert all(subject in call[1] and "三维卡通" in call[0] for call in image_inputs)
    assert storage.to_public_url(shots[0].image_url) in image_inputs[1][1]
    await pipeline._parallel_videos(project.id)
    assert project.status == ProjectStatus.VIDEO_READY
    assert [storage.local_path_from_url(call[0]) for call in video_inputs] == [
        storage.local_path_from_url(shot.image_url) for shot in shots
    ]
    assert all(call[1]["generate_audio"] is True for call in video_inputs)
    assert video_inputs[1][1]["extra_image_urls"] == [shots[0].last_frame_url]
    await pipeline._compose_stage(project.id)

    final = storage.local_path_from_url(project.final_video_url)
    assert project.status == ProjectStatus.DONE and final.is_file() and final.stat().st_size > 2000
    probe = json.loads(_run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(final)]))
    visual = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    assert visual["codec_name"] == "h264" and audio["codec_name"] == "aac"
    assert visual["width"] * 16 == visual["height"] * 9
    assert 7.8 <= float(probe["format"]["duration"]) <= 8.5
    assert abs(float(visual["duration"]) - float(audio["duration"])) < 0.2
    assert not ffmpeg_compose.is_near_silent_audio(final)
    try:
        subprocess.run([ffmpeg, "-hide_banner", "-v", "error",
                        "-f", "lavfi", "-i", "color=size=16x16:duration=0.1:rate=1",
                        "-frames:v", "1", "-fps_mode", "passthrough", "-f", "null", "-"],
                       capture_output=True, check=True, timeout=30)
        fps_flag = "-fps_mode"
    except Exception:
        fps_flag = "-vsync"
    frames = _run([ffmpeg, "-v", "error", "-i", str(final), "-an", "-vf", "select='eq(n,0)+eq(n,25)'",
                   fps_flag, "vfr", "-frames:v", "2", "-f", "framemd5", "-"])
    hashes = [line.rsplit(",", 1)[1].strip() for line in frames.splitlines() if line and not line.startswith("#")]
    assert len(hashes) == 2 and hashes[0] != hashes[1]
    assert all(shot.audio_url is None for shot in shots)
    external_tts.assert_not_awaited()
    gateway.tts.assert_not_awaited()
    network.assert_not_awaited()
