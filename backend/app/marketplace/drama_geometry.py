"""统一解释分镜显示画幅，避免像素比例和旋转元数据导致误判或画面变形。"""
from __future__ import annotations

from fractions import Fraction
import math

# 模型返回的同画幅视频可能存在小幅尺寸偏差；最多接受整集 5% 的显示比例跨度。
_MAX_ASPECT_SPREAD = Fraction(1, 20)


def _pixel_ratio(video: dict) -> Fraction:
    """缺失或无效的像素宽高比按方形像素解释。"""
    try:
        ratio = Fraction(str(video.get("sample_aspect_ratio") or "1:1").replace(":", "/"))
        return ratio if ratio > 0 else Fraction(1)
    except (ValueError, ZeroDivisionError):
        return Fraction(1)


def _quarter_turn(video: dict) -> bool:
    """识别 FFmpeg 自动旋转使用的直角元数据，拒绝悄悄误算任意角度。"""
    rotation = video.get("tags", {}).get("rotate") or 0
    for side in video.get("side_data_list", []):
        if "rotation" in side:
            rotation = side["rotation"]
    try:
        angle = float(rotation)
        turns = round(angle / 90)
        if not math.isfinite(angle) or abs(angle - turns * 90) > 0.1:
            raise ValueError("unsupported rotation")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("MARKETPLACE_SOURCE_INCOMPATIBLE:分镜旋转角度不受支持，请先导出为标准横屏或竖屏视频") from exc
    return bool(turns % 2)


def display_ratio(info: dict) -> Fraction:
    """先应用原始轴上的像素比例，再旋转；不让尺寸取整影响画幅判断。"""
    ratio = Fraction(info["width"], info["height"]) * _pixel_ratio(info["video"])
    return 1 / ratio if _quarter_turn(info["video"]) else ratio


def stream_display_size(stream: dict) -> tuple[int, int]:
    """把探测流换成播放时的宽高；不支持的旋转角退回编码尺寸，避免误判成竖屏。"""
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    try:
        return display_dimensions({"width": width, "height": height, "video": stream})
    except ValueError:
        return width, height


def orientation_name(width: int | None, height: int | None) -> str | None:
    """宽大于高为横版，高大于宽为竖版，相等为方形；未知尺寸不猜测。"""
    if not width or not height or width < 1 or height < 1:
        return None
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def display_dimensions(info: dict) -> tuple[int, int]:
    """只扩大像素尺寸来还原显示画幅，最后应用旋转，不缩小源画面。"""
    width, height = info["width"], info["height"]
    ratio = _pixel_ratio(info["video"])
    if ratio > 1:
        width = math.ceil(width * ratio)
    elif ratio < 1:
        height = math.ceil(height / ratio)
    return (height, width) if _quarter_turn(info["video"]) else (width, height)


def validate_aspects(infos: list[dict], clips: list[dict]) -> list[tuple[int, int]]:
    """允许小幅比例偏差交给等比补边；按整集极值校验，结果不依赖首镜选择。"""
    ratios = [display_ratio(info) for info in infos]
    low = min(range(len(ratios)), key=ratios.__getitem__)
    high = max(range(len(ratios)), key=ratios.__getitem__)
    if ratios[high] / ratios[low] - 1 > _MAX_ASPECT_SPREAD:
        def describe(position):
            """把真实来源规格映射回发布时的分镜顺序。"""
            info, clip = infos[position], clips[position]
            value = ratios[position].limit_denominator(10000)
            return (f"第{position + 1}镜（分镜编号{clip['id']}，{info['width']}×{info['height']}，"
                    f"显示{value.numerator}:{value.denominator}）")
        raise ValueError("MARKETPLACE_SOURCE_INCOMPATIBLE:分镜画幅比例不一致："
            f"{describe(low)}与{describe(high)}；差异超过5%的自动补边范围，请先统一画幅后发布")
    return [display_dimensions(info) for info in infos]


def fit_dimensions(info: dict, width: int, height: int) -> tuple[int, int]:
    """按显示画幅适配偶数像素画布，供方形像素编码使用，避免 SAR 被重置后压扁。"""
    ratio = display_ratio(info)
    if Fraction(width, height) > ratio:
        return max(2, math.floor(height * ratio / 2) * 2), height
    return width, max(2, math.floor(width / ratio / 2) * 2)
