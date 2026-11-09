"""FFmpeg 5.1 起才有 -fps_mode；旧版只接受 -vsync。用真实探针结果选择参数。"""
import subprocess

import pytest

from app.config import get_settings
from app.marketplace import preview_worker


def _independent_probe(ffmpeg_path: str) -> str:
    """独立的同步探针：直接执行真实二进制，不复用产品实现。"""
    try:
        subprocess.run(
            [ffmpeg_path, "-hide_banner", "-v", "error",
             "-f", "lavfi", "-i", "color=size=16x16:duration=0.1:rate=1",
             "-frames:v", "1", "-fps_mode", "passthrough", "-f", "null", "-"],
            capture_output=True, check=True, timeout=30)
        return "-fps_mode"
    except Exception:
        return "-vsync"


async def test_probe_failure_falls_back_to_vsync(monkeypatch):
    async def boom(*args, **kwargs):
        raise ValueError("Unrecognized option 'fps_mode'.")
    monkeypatch.setattr("app.marketplace.worker.command", boom)
    preview_worker._FPS_FLAG_BY_BINARY.clear()
    assert await preview_worker._fps_passthrough_args("/nonexistent/ffmpeg") == ["-vsync", "passthrough"]


async def test_probe_success_uses_fps_mode(monkeypatch):
    calls = []

    async def ok(*args, **kwargs):
        calls.append(args)
        return b""
    monkeypatch.setattr("app.marketplace.worker.command", ok)
    preview_worker._FPS_FLAG_BY_BINARY.clear()
    assert await preview_worker._fps_passthrough_args("/nonexistent/ffmpeg") == ["-fps_mode", "passthrough"]
    assert "-fps_mode" in calls[0]


async def test_result_matches_independent_probe_of_real_binary():
    """产品探针与独立同步探针对同一真实二进制必须给出同一参数。"""
    preview_worker._FPS_FLAG_BY_BINARY.clear()
    ffmpeg = get_settings().ffmpeg_path
    expected = _independent_probe(ffmpeg)
    assert await preview_worker._fps_passthrough_args(ffmpeg) == [expected, "passthrough"]
