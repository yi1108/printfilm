"""Seedream size 解析：Pro 不得超过 4624220 总像素。"""

from app.services.drama.seedream_options import (
    SEEDREAM_PRO_MAX_PIXELS,
    clamp_seedream_pixel_size,
    is_seedream_pro_model,
    resolve_seedream_size,
)


def test_pro_clamps_3k_to_2k_pixel() -> None:
    size = resolve_seedream_size(
        aspect_ratio="9:16",
        resolution="3K",
        model_id="doubao-seedream-5-0-pro-260628",
    )
    assert size == "1584x2816"
    w, h = map(int, size.lower().split("x"))
    assert w * h <= SEEDREAM_PRO_MAX_PIXELS


def test_pro_character_default_ratio() -> None:
    size = resolve_seedream_size(
        aspect_ratio="3:4",
        resolution="3K",
        model_id="doubao-seedream-5-0-pro-260628",
    )
    assert size == "1776x2368"


def test_clamp_oversized_pixels() -> None:
    assert clamp_seedream_pixel_size("2304x4096") != "2304x4096"
    w, h = map(int, clamp_seedream_pixel_size("2304x4096").lower().split("x"))
    assert w * h <= SEEDREAM_PRO_MAX_PIXELS


def test_pro_detection() -> None:
    assert is_seedream_pro_model("doubao-seedream-5-0-pro-260628")
    assert not is_seedream_pro_model("doubao-seedream-4-5")
    assert not is_seedream_pro_model("kie-seedream-5")
    assert not is_seedream_pro_model("z-image-turbo")
    assert not is_seedream_pro_model("gpt-image-2")


def test_compact_models_force_1k() -> None:
    """z-image 等非 Seedream 模型强制 1K，避免大像素触发协议失败。"""
    size = resolve_seedream_size(
        aspect_ratio="3:4",
        resolution="3K",
        model_id="z-image-turbo",
    )
    assert size == "864x1152"
