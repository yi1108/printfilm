"""分镜视频前动态补齐缺图资产。"""

from types import SimpleNamespace

from app.services.drama.generation import (
    asset_needs_reference_image,
    extract_asset_ids_from_content,
    read_asset_visual_prompt,
)


def test_extract_asset_ids_from_content_dedupes():
    text = "开场 @asset:9 中段 @asset:9 结尾 @asset:3"
    assert extract_asset_ids_from_content(text) == [9, 3]


def test_asset_needs_reference_image():
    empty = SimpleNamespace(type="character", cover="", url=None)
    ready = SimpleNamespace(type="character", cover="/x.png", url="")
    voice = SimpleNamespace(type="voice", cover="", url="")
    assert asset_needs_reference_image(empty) is True
    assert asset_needs_reference_image(ready) is False
    assert asset_needs_reference_image(voice) is False


def test_read_asset_visual_prompt_fallback():
    asset = SimpleNamespace(
        id=7,
        type="scene",
        name="龙门",
        params={"visualPrompt": "  峡谷裂口，云雾，史诗感  "},
    )
    assert "峡谷裂口" in read_asset_visual_prompt(asset)
