"""i2v 兜底静帧尺寸必须跟随目标画幅，避免横屏首帧传染。"""

from app.services.drama.output_settings import seedream_still_size_for_video_ratio
from app.services.drama.build_seedance_generate_body import resolve_seedance_ratio


# 竖屏目标应对应竖屏 Seedream 像素
def test_seedream_still_size_portrait() -> None:
    assert seedream_still_size_for_video_ratio("9:16") == "2304x4096"
    assert seedream_still_size_for_video_ratio(None) == "2304x4096"


# 横屏 / 方形映射
def test_seedream_still_size_other_ratios() -> None:
    assert seedream_still_size_for_video_ratio("16:9") == "4096x2304"
    assert seedream_still_size_for_video_ratio("1:1") == "3072x3072"


# Seedance ratio 缺省与漫剧默认竖屏一致
def test_resolve_seedance_ratio_defaults_portrait() -> None:
    assert resolve_seedance_ratio(None) == "9:16"
    assert resolve_seedance_ratio("") == "9:16"
    assert resolve_seedance_ratio("16:9") == "16:9"
