"""漫剧输出规格：分集 params 优先，回退项目 params。"""

from __future__ import annotations

from typing import Any

VALID_RATIOS = frozenset({"9:16", "16:9", "1:1"})
VALID_RESOLUTIONS = frozenset({"480p", "720p", "1080p"})


def _pick_ratio(raw: Any) -> str | None:
    value = str(raw or "").strip()
    return value if value in VALID_RATIOS else None


def _pick_resolution(raw: Any) -> str | None:
    value = str(raw or "").strip()
    return value if value in VALID_RESOLUTIONS else None


# 解析分集画幅与清晰度（分集 → 项目 → 默认）
def resolve_episode_video_output(
    episode_params: dict | None,
    project_params: dict | None,
) -> tuple[str, str]:
    ep = episode_params if isinstance(episode_params, dict) else {}
    proj = project_params if isinstance(project_params, dict) else {}
    ratio = _pick_ratio(ep.get("aspect_ratio")) or _pick_ratio(proj.get("aspect_ratio")) or "9:16"
    resolution = (
        _pick_resolution(ep.get("resolution"))
        or _pick_resolution(proj.get("resolution"))
        or "480p"
    )
    return ratio, resolution


# Seedance / 成片常用像素（偶数边）
_RATIO_RES_PIXELS: dict[tuple[str, str], tuple[int, int]] = {
    ("9:16", "480p"): (480, 854),
    ("9:16", "720p"): (720, 1280),
    ("9:16", "1080p"): (1080, 1920),
    ("16:9", "480p"): (854, 480),
    ("16:9", "720p"): (1280, 720),
    ("16:9", "1080p"): (1920, 1080),
    ("1:1", "480p"): (480, 480),
    ("1:1", "720p"): (720, 720),
    ("1:1", "1080p"): (1080, 1080),
}


# 分集目标成片宽高（用于拼接时统一缩放）
def target_pixel_size(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    key = (aspect_ratio if aspect_ratio in VALID_RATIOS else "9:16",
           resolution if resolution in VALID_RESOLUTIONS else "480p")
    return _RATIO_RES_PIXELS.get(key, (480, 854))


# 根据像素尺寸推断最接近的标准画幅标签
def infer_aspect_ratio_from_pixels(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "9:16"
    ratio = width / height
    candidates = (("9:16", 9 / 16), ("16:9", 16 / 9), ("1:1", 1.0))
    best = min(candidates, key=lambda item: abs(ratio - item[1]))
    if abs(ratio - best[1]) <= 0.08:
        return best[0]
    return f"{width}×{height}"


# i2v 兜底静帧：按目标画幅生成，避免 Seedance「跟首帧比例」变成横屏
def seedream_still_size_for_video_ratio(aspect_ratio: str | None) -> str:
    ratio = _pick_ratio(aspect_ratio) or "9:16"
    mapping = {
        "9:16": "2304x4096",
        "16:9": "4096x2304",
        "1:1": "3072x3072",
    }
    return mapping.get(ratio, "2304x4096")
