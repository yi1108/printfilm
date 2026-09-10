# -*- coding: utf-8 -*-
"""科普分阶段预扣：确认分镜时不应一次锁全片视频费用。"""
from __future__ import annotations

from types import SimpleNamespace

from app.config import get_settings
from app.services.billing.estimates import estimate_phase_fen
from app.services.kepu_stages import (
    normalize_kepu_pipeline_phase,
    resolve_kepu_billing_phase,
)


def _shot(**kwargs):
    defaults = {
        "image_url": None,
        "image_ark_url": None,
        "audio_url": None,
        "video_url": None,
        "duration": 10.0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _project(shots, pipeline_mode="full", project_id=1):
    return SimpleNamespace(id=project_id, shots=shots, pipeline_mode=pipeline_mode)


def test_resolve_phase_script_when_no_shots() -> None:
    assert resolve_kepu_billing_phase(_project([])) == "script"


def test_resolve_phase_assets_after_storyboard() -> None:
    shots = [_shot() for _ in range(7)]
    assert resolve_kepu_billing_phase(_project(shots)) == "assets"


def test_resolve_phase_videos_after_assets(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.kepu_stages.project_audio_ready",
        lambda _project: True,
    )
    shots = [_shot(image_url="/i.png", audio_url="/a.wav") for _ in range(7)]
    assert resolve_kepu_billing_phase(_project(shots)) == "videos"


def test_resolve_phase_videos_when_continuous_audio_ok(monkeypatch) -> None:
    """整片旁白文件就绪但 shot.audio_url 为空时，应与 pipeline 一样进入 videos。"""
    monkeypatch.setattr(
        "app.services.kepu_stages.continuous_narration_ok",
        lambda _pid: True,
    )
    shots = [_shot(image_url="/i.png") for _ in range(3)]
    assert resolve_kepu_billing_phase(_project(shots)) == "videos"


def test_resolve_phase_assets_when_audio_url_but_file_bad(monkeypatch) -> None:
    """仅有 audio_url 字符串但文件不可用时，仍应留在 assets，避免误冻视频款。"""
    monkeypatch.setattr(
        "app.services.kepu_stages.continuous_narration_ok",
        lambda _pid: False,
    )
    monkeypatch.setattr(
        "app.services.kepu_stages.shot_audio_file_ok",
        lambda _shot: False,
    )
    shots = [_shot(image_url="/i.png", audio_url="/missing.wav") for _ in range(2)]
    assert resolve_kepu_billing_phase(_project(shots)) == "assets"


def test_resolve_phase_compose_when_full_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.kepu_stages.project_audio_ready",
        lambda _project: True,
    )
    shots = [
        _shot(image_url="/i.png", audio_url="/a.wav", video_url="/v.mp4") for _ in range(3)
    ]
    assert resolve_kepu_billing_phase(_project(shots)) == "compose"


def test_produce_estimate_is_assets_not_full_video() -> None:
    """确认分镜时 phase=produce 应只估出图段，远小于含视频的全片预扣。"""
    settings = get_settings()
    shots = [_shot(duration=10.0) for _ in range(7)]
    project = _project(shots)
    assets = estimate_phase_fen(project, "assets", settings=settings)
    videos = estimate_phase_fen(project, "videos", settings=settings)
    produce = estimate_phase_fen(project, "produce", settings=settings)
    legacy_full = assets + videos
    assert produce == assets
    assert produce < legacy_full
    assert videos > assets


def test_videos_estimate_only_remaining_shots() -> None:
    settings = get_settings()
    shots = [
        _shot(image_url="/i.png", audio_url="/a.wav", video_url="/done.mp4", duration=10),
        _shot(image_url="/i.png", audio_url="/a.wav", duration=10),
        _shot(image_url="/i.png", audio_url="/a.wav", duration=10),
    ]
    one = estimate_phase_fen(
        _project([_shot(image_url="/i.png", audio_url="/a.wav", duration=10)]),
        "videos",
        settings=settings,
    )
    two = estimate_phase_fen(_project(shots), "videos", settings=settings)
    assert two == one * 2


def test_normalize_produce_maps_to_current_phase(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.kepu_stages.project_audio_ready",
        lambda _project: True,
    )
    shots = [_shot(image_url="/i.png", audio_url="/a.wav") for _ in range(2)]
    project = _project(shots)
    assert normalize_kepu_pipeline_phase("produce", project) == "videos"
    assert normalize_kepu_pipeline_phase("assets", project) == "assets"
