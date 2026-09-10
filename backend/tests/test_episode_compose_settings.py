"""分集合成：目标像素与片段筛选。"""

from app.services.drama.output_settings import target_pixel_size


# 竖屏 1080p 目标尺寸
def test_target_pixel_size_portrait_1080() -> None:
    assert target_pixel_size("9:16", "1080p") == (1080, 1920)


# 横屏 1080p 目标尺寸
def test_target_pixel_size_landscape_1080() -> None:
    assert target_pixel_size("16:9", "1080p") == (1920, 1080)
