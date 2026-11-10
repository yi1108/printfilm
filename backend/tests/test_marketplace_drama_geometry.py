"""验证显示画幅，不把编码尺寸、旋转和非方形像素混为一谈。"""
from fractions import Fraction

import pytest

from app.marketplace.drama_geometry import display_dimensions, display_ratio, fit_dimensions, orientation_name, stream_display_size, validate_aspects


def _info(width, height, sar="1:1", rotation=0):
    """构造 FFprobe 的几何相关字段。"""
    return {"width": width, "height": height,
            "video": {"sample_aspect_ratio": sar, "side_data_list": [{"rotation": rotation}]}}


@pytest.mark.parametrize("rotation,dimensions,ratio", [
    (0, (768, 576), Fraction(4, 3)), (90, (576, 768), Fraction(3, 4)),
    (-90, (576, 768), Fraction(3, 4)), (180, (768, 576), Fraction(4, 3)),
])
def test_sar_is_applied_before_rotation(rotation, dimensions, ratio):
    info = _info(720, 576, "16:15", rotation)
    assert display_dimensions(info) == dimensions
    assert display_ratio(info) == ratio
    assert fit_dimensions(info, *dimensions) == dimensions


def test_small_pixel_rounding_and_same_ratio_different_sizes_are_allowed():
    infos = [_info(1920, 1080), _info(1280, 720), _info(854, 480)]
    assert validate_aspects(infos, [{"id": i} for i in (10, 11, 12)]) == [(1920, 1080), (1280, 720), (854, 480)]


@pytest.mark.parametrize("rotation", [0, 90])
def test_model_frame_size_variation_is_allowed_without_distortion(rotation):
    """模型返回832或854宽时可等比补边，旋转后的同类竖屏也适用。"""
    infos = [_info(832, 480, rotation=rotation), _info(854, 480, rotation=rotation)]
    expected = [(480, 832), (480, 854)] if rotation else [(832, 480), (854, 480)]
    sizes = validate_aspects(infos, [{"id": 18708}, {"id": 18711}])
    assert sizes == expected
    canvas = tuple(max(values) for values in zip(*sizes))
    assert fit_dimensions(infos[0], *canvas) == expected[0]
    assert fit_dimensions(infos[1], *canvas) == expected[1]


def test_padding_limit_includes_five_percent_but_rejects_larger_difference():
    infos = [_info(1600, 900), _info(1680, 900)]
    assert validate_aspects(infos, [{"id": 10}, {"id": 11}]) == [(1600, 900), (1680, 900)]
    with pytest.raises(ValueError, match="超过5%的自动补边范围"):
        validate_aspects([infos[0], _info(1682, 900)], [{"id": 10}, {"id": 11}])


@pytest.mark.parametrize("widths", [(880, 840, 920), (840, 920, 880), (920, 880, 840)])
def test_total_aspect_spread_does_not_depend_on_which_shot_is_first(widths):
    """中间尺寸不能掩盖首尾累计偏差，调整分镜顺序也不能绕过限制。"""
    with pytest.raises(ValueError, match="MARKETPLACE_SOURCE_INCOMPATIBLE"):
        validate_aspects([_info(width, 500) for width in widths], [{"id": i} for i in range(3)])


def test_equivalent_sar_and_rotation_are_allowed():
    infos = [_info(720, 576, "16:15", 90), _info(576, 768)]
    assert validate_aspects(infos, [{"id": 10}, {"id": 11}]) == [(576, 768), (576, 768)]


def test_unsupported_rotation_does_not_silently_become_portrait():
    with pytest.raises(ValueError, match="MARKETPLACE_SOURCE_INCOMPATIBLE:分镜旋转角度不受支持"):
        display_ratio(_info(1920, 1080, rotation=45))


def test_subunit_sar_expands_height_without_lowering_source_resolution():
    info = _info(720, 480, "8:9", 90)
    assert display_dimensions(info) == (540, 720)
    assert display_ratio(info) == Fraction(3, 4)


def test_playback_orientation_uses_display_size_after_rotation():
    """横着编码、竖着播放的视频按显示画幅记为竖版，未知尺寸不猜测。"""
    stream = {"width": 1920, "height": 1080, "sample_aspect_ratio": "1:1", "side_data_list": [{"rotation": 90}]}
    assert stream_display_size(stream) == (1080, 1920)
    assert orientation_name(*stream_display_size(stream)) == "portrait"
    assert orientation_name(1920, 1080) == "landscape"
    assert orientation_name(100, 100) == "square"
    assert orientation_name(0, 0) is None
    assert orientation_name(None, None) is None


def test_unsupported_rotation_keeps_coded_size_instead_of_guessing_portrait():
    stream = {"width": 1920, "height": 1080, "side_data_list": [{"rotation": 45}]}
    assert stream_display_size(stream) == (1920, 1080)
