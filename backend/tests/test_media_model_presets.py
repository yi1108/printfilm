"""站点预设模型与按模型参数白名单。"""

from __future__ import annotations

from app.services.media_model_presets import (
    all_preset_channel_models,
    clamp_default_to_preset,
    is_preset_model,
    model_generation_options,
    preset_ids,
)
from app.services.seedance_resolutions import (
    allowed_video_resolutions,
    clamp_video_duration,
    clamp_video_resolution,
    video_duration_bounds,
)


def test_all_preset_channel_models_covers_four_caps() -> None:
    models = all_preset_channel_models()
    assert set(preset_ids("text")) == {"gpt-6.1-sol", "gpt-6-astra", "deepseek-v4-pro"}
    assert "kimi-k2.6" not in models and "gpt-5.5" not in models
    assert "seedream-5.0-pro" not in models
    assert "seedream-5.0" in models
    assert "seedream-5.0-flash" not in models
    assert "gpt-image-2" not in models
    assert "gpt-image-2.5" in models
    assert "seedance-2.5" in models
    assert "seedance-2.0-fast" in models
    assert "MiniMax-H3" in models
    assert "qwen-tts-2025-05-22" in models
    assert "gemini-3.1-flash-tts" not in models
    assert len(models) == sum(len(preset_ids(c)) for c in ("text", "image", "video", "audio"))
    assert preset_ids("image") == [
        "seedream-5.0",
        "gpt-image-2.5",
    ]
    assert preset_ids("audio") == ["qwen-tts-2025-05-22"]
    assert set(preset_ids("video")) == {
        "seedance-2.5",
        "seedance-2.0",
        "seedance-2.0-fast",
        "MiniMax-H3",
    }
    assert "seedance-2.0-mini" not in models
    assert clamp_default_to_preset("video", "seedance-2.0-mini") == "seedance-2.0"


def test_clamp_default_audio_only_qwen() -> None:
    assert clamp_default_to_preset("audio", "qwen-tts-2025-05-22") == "qwen-tts-2025-05-22"
    assert clamp_default_to_preset("audio", "gemini-3.1-flash-tts") == "qwen-tts-2025-05-22"
    assert is_preset_model("audio", "qwen-tts-2025-05-22") is True
    assert is_preset_model("audio", "elevenlabs-tts") is False


def test_clamp_seedance_aliases_to_canonical() -> None:
    assert clamp_default_to_preset("video", "seedance-2-5") == "seedance-2.5"
    assert clamp_default_to_preset("video", "seedance-2") == "seedance-2.0"
    assert clamp_default_to_preset("video", "seedance-2-0-fast") == "seedance-2.0-fast"
    assert is_preset_model("video", "seedance-2.5") is True


def test_clamp_seedream_aliases_to_canonical() -> None:
    assert clamp_default_to_preset("image", "seedream-5-0-pro") == "seedream-5.0"
    assert clamp_default_to_preset("image", "seedream-5-0") == "seedream-5.0"
    assert clamp_default_to_preset("image", "seedream-5.0-flash") == "seedream-5.0"
    assert clamp_default_to_preset("image", "gpt-image-2") == "gpt-image-2.5"
    assert clamp_default_to_preset("image", "gpt-image-2.5") == "gpt-image-2.5"
    assert clamp_default_to_preset("image", "gpt-image-2-5") == "gpt-image-2.5"
    assert clamp_default_to_preset("image", "gpt-image-2.5-sunburst") == "gpt-image-2.5"
    assert is_preset_model("image", "gpt-image-2") is False
    assert is_preset_model("image", "gpt-image-2.5") is True
    assert is_preset_model("image", "seedream-5.0") is True
    assert is_preset_model("image", "nano-banana-2") is False


def test_build_body_clamps_minimax_duration() -> None:
    """请求体组装时 MiniMax 时长不得超过 15。"""
    from app.services.drama.build_seedance_generate_body import build_seedance_generate_body

    body = build_seedance_generate_body(
        {
            "content": "测试镜头",
            "model_id": "MiniMax-H3",
            "duration_fallback": 30,
            "resolution": "1080p",
            "aspect_ratio": "9:16",
        }
    )
    assert body["duration"] == 15
    assert body["resolution"] == "768p"


def test_image_options_standard_1k_2k() -> None:
    for mid in ("seedream-5.0-pro", "seedream-5.0", "seedream-5.0-flash", "gpt-image-2"):
        opts = model_generation_options(mid)
        assert opts["capability"] == "image"
        assert opts["allowed_resolutions"] == ["1K", "2K"]
        assert "3:4" in opts["allowed_aspect_ratios"]
    opts25 = model_generation_options("gpt-image-2.5")
    assert opts25["allowed_resolutions"] == ["1K", "2K", "4K"]


def test_minimax_h3_video_options() -> None:
    opts = model_generation_options("MiniMax-H3")
    assert opts["capability"] == "video"
    assert opts["allowed_resolutions"] == ["480p", "768p"]
    assert opts["duration_min"] == 4
    assert opts["duration_max"] == 15
    assert allowed_video_resolutions("MiniMax-H3") == ["480p", "768p"]
    assert video_duration_bounds("MiniMax-H3") == (4, 15)
    assert clamp_video_duration("MiniMax-H3", 30) == 15
    assert clamp_video_duration("MiniMax-H3", 8) == 8
    assert clamp_video_resolution("MiniMax-H3", "1080p") == "768p"
    assert clamp_video_resolution("MiniMax-H3", "720p") == "768p"
    assert clamp_video_resolution("MiniMax-H3", "480p") == "480p"
    assert clamp_video_resolution("MiniMax-H3", "768p") == "768p"


def test_seedance_20_options_safe() -> None:
    opts = model_generation_options("seedance-2.0")
    assert opts["allowed_resolutions"] == ["480p", "720p"]
    assert opts["duration_max"] == 15
    assert video_duration_bounds("seedance-2.0") == (4, 15)
    assert clamp_video_duration("seedance-2.0", 30) == 15
    assert clamp_video_duration("doubao-seedance-2-0", 16) == 15
    opts25 = model_generation_options("seedance-2.5")
    assert opts25["allowed_resolutions"] == ["480p", "720p", "1080p"]
    assert opts25["duration_max"] == 30
    assert clamp_video_duration("seedance-2.5", 30) == 30
    opts_fast = model_generation_options("seedance-2.0-fast")
    assert opts_fast["allowed_resolutions"] == ["480p", "720p"]
    assert opts_fast["duration_max"] == 15


def test_seedance_mini_safe_resolutions() -> None:
    opts = model_generation_options("seedance-2.0-mini")
    assert opts["allowed_resolutions"] == ["480p", "720p"]
    # mini 别名钳到 2.0，时长上限同为 15s
    assert opts["duration_max"] == 15


def test_catalog_image_row_has_allowed_params() -> None:
    from app.schemas_routing import DefaultModels, LogicalModel
    from app.services.media_catalog import build_media_catalog

    payload = build_media_catalog(
        logical_models=[
            LogicalModel(
                id="seedream-5.0",
                name="Seedream 5.0",
                capability="image",
                enabled=True,
                bindings=[],
            ),
            LogicalModel(
                id="MiniMax-H3",
                name="MiniMax H3",
                capability="video",
                enabled=True,
                bindings=[],
            ),
        ],
        channels=[],
        defaults=DefaultModels(image_model="seedream-5.0", video_model="MiniMax-H3"),
    )
    img = {row["id"]: row for row in payload["image_models"]}["seedream-5.0"]
    assert img["allowed_resolutions"] == ["1K", "2K"]
    assert "3:4" in img["allowed_aspect_ratios"]
    assert img["description"]
    assert img["pricing_hint"]
    vid = {row["id"]: row for row in payload["video_models"]}["MiniMax-H3"]
    assert vid["duration_max"] == 15
    assert vid["allowed_resolutions"] == ["480p", "768p"]
    assert "MiniMax" in vid["description"] or vid["description"]
    assert vid["pricing_hint"]
    assert vid["eta_hint"]
    assert "分钟" in vid["eta_hint"]
