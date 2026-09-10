"""参考音色时长：下限与补足。"""

from app.services.drama.voice_reference_audio import (
    SEEDANCE_REFERENCE_AUDIO_MAX_SEC,
    SEEDANCE_REFERENCE_AUDIO_MIN_SEC,
    VOICE_REFERENCE_MIN_SEC,
    VOICE_REFERENCE_TARGET_SEC,
    is_voice_duration_too_short,
    patch_params_voice_url,
)
from app.services.drama.voice_synthesis import build_voice_sample_line_short


def test_voice_reference_min_meets_seedance_api():
    assert VOICE_REFERENCE_MIN_SEC >= SEEDANCE_REFERENCE_AUDIO_MIN_SEC
    assert VOICE_REFERENCE_TARGET_SEC < SEEDANCE_REFERENCE_AUDIO_MAX_SEC
    assert SEEDANCE_REFERENCE_AUDIO_MAX_SEC <= 30.2


def test_is_voice_duration_too_short():
    assert is_voice_duration_too_short(1.2) is True
    assert is_voice_duration_too_short(1.79) is True
    assert is_voice_duration_too_short(2.0) is False
    assert is_voice_duration_too_short(None) is False


def test_sample_line_long_enough_for_tts():
    line = build_voice_sample_line_short("双龙")
    # 中文 TTS 约 3–4 字/秒；两句应明显长于 1.8s
    assert len(line) >= 20
    assert "双龙" in line


def test_patch_params_voice_url():
    params = {
        "voiceAudio": {"sourceAssetId": 1, "url": "/static/old.mp3", "label": "禹音色"},
        "canvas": {"voiceAudio": {"sourceAssetId": 1, "url": "/static/old.mp3"}},
    }
    next_params = patch_params_voice_url(params, "/static/new.mp3")
    assert next_params["voiceAudio"]["url"] == "/static/new.mp3"
    assert next_params["canvas"]["voiceAudio"]["url"] == "/static/new.mp3"
