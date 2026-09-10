"""Seedream 前端选项 → 方舟 model / size 解析。"""

from __future__ import annotations

from app.config import get_settings
from app.services.logical_model_router import resolve_logical_model_id, resolve_upstream_model

# SeedreamAspectRatio 支持的比例
SeedreamAspectRatio = str
# SeedreamResolution 清晰度
SeedreamResolution = str

# SEEDREAM_SIZE_MAP 清晰度 + 比例 → Ark size
SEEDREAM_SIZE_MAP: dict[str, dict[str, str]] = {
    "3K": {
        "auto": "3K",
        "1:1": "3072x3072",
        "16:9": "4096x2304",
        "21:9": "4704x2016",
        "9:16": "2304x4096",
        "4:3": "3456x2592",
        "3:4": "2592x3456",
    },
    "4K": {
        "auto": "4K",
        "1:1": "4096x4096",
        "16:9": "5404x3040",
        "21:9": "6198x2656",
        "9:16": "3040x5404",
        "4:3": "4694x3520",
        "3:4": "3520x4694",
    },
}


# 将前端模型 ID 解析为方舟推理接入点
def resolve_seedream_model_endpoint(model_id: str | None) -> str:
    settings = get_settings()
    mid = (model_id or "").strip().lower()
    logical_id = resolve_logical_model_id("image", model_id)
    routed = resolve_upstream_model("image", logical_id)
    if routed and routed != logical_id:
        return routed
    if mid in {"", "seedream-5.0", "seedream-5", "5.0"}:
        return resolve_upstream_model("image", "seedream-5.0") or settings.model_image
    if mid in {"seedream-4.5", "seedream-4", "4.5"}:
        return resolve_upstream_model("image", "seedream-4.5") or (settings.model_image_45 or "").strip() or settings.model_image
    return model_id or settings.model_image


# 将清晰度 + 比例解析为 Ark size 参数
def resolve_seedream_size(
    *,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
) -> str:
    settings = get_settings()
    res = (resolution or "3K").strip().upper()
    if res not in SEEDREAM_SIZE_MAP:
        res = "3K"
    ratio = (aspect_ratio or "3:4").strip() or "3:4"
    mapped = SEEDREAM_SIZE_MAP[res].get(ratio)
    if mapped:
        return mapped
    return settings.ark_image_size or "2k"
