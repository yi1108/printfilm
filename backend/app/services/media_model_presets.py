"""站点预设模型清单 + 按模型生成参数白名单。"""

from __future__ import annotations

from typing import Any

from app.schemas_routing import LogicalModelCapability
from app.services.model_routing_config import normalize_model_name

# 管理端四下拉 + 渠道 models 硬编码白名单（含前台展示文案）
# id 与 TokenFree 目录展示名对齐（点分：seedance-2.0 / seedream-5.0-pro）
PRESET_MODELS: dict[LogicalModelCapability, tuple[dict[str, str], ...]] = {
    "text": (
        {
            "id": "gpt-6.1-sol",
            "label": "GPT-6.1 Sol",
            "note": "剧本创作、分镜提示词与日常改写",
            "pricing_hint": "按平台文字任务计费",
        },
        {
            "id": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "note": "推理强、性价比高，适合扩写与润色",
            "pricing_hint": "通常更省",
        },
        {
            "id": "gpt-6-astra",
            "label": "GPT-6 Astra",
            "note": "复杂叙事、细节推敲与多重创作要求",
            "pricing_hint": "按平台文字任务计费",
        },
    ),
    "image": (
        {
            "id": "seedream-5.0",
            "label": "Seedream 5.0",
            "note": "标准静帧，质量与成本均衡",
            "pricing_hint": "按模型与分辨率定价",
            "eta_hint": "约 15–40 秒/张",
        },
        {
            "id": "gpt-image-2.5",
            "label": "GPT Image 2.5",
            "note": "OpenAI 新一代生图，细节与文字更稳，适合定妆与精细静帧",
            "pricing_hint": "按模型与分辨率定价",
            "eta_hint": "约 30–120 秒/张",
        },
    ),
    "video": (
        {
            "id": "seedance-2.5",
            "label": "Seedance 2.5",
            "note": "成片首选，画质更好；4–30 秒，支持到 1080p",
            "pricing_hint": "按模型与分辨率定价",
            "eta_hint": "约 3–8 分钟/镜",
        },
        {
            "id": "seedance-2.0",
            "label": "Seedance 2.0",
            "note": "标准成片，运镜较稳；4–15 秒，最高 720p",
            "pricing_hint": "按模型与分辨率定价",
            "eta_hint": "约 2–5 分钟/镜",
        },
        {
            "id": "seedance-2.0-fast",
            "label": "Seedance 2.0 Fast",
            "note": "2.0 加速档，适合赶进度；4–15 秒，最高 720p",
            "pricing_hint": "按模型与分辨率定价",
            "eta_hint": "约 1–4 分钟/镜",
        },
        # seedance-2.0-mini：TokenFree 会转到 doubao-seedance-2-0-mini-260615，
        # 上游 Ark 未开通 → ModelNotOpen；暂不进预设，别名钳到 2.0
        {
            "id": "MiniMax-H3",
            "label": "MiniMax H3",
            "note": "节奏感强、人物生动；4–15 秒，480p / 768p",
            "pricing_hint": "按模型与分辨率定价",
            "eta_hint": "偏慢，4s 约 15 分钟起",
        },
    ),
    "audio": (
        {
            "id": "qwen-tts-2025-05-22",
            "label": "Qwen TTS",
            "note": "阿里云百炼 Qwen 配音，站点唯一语音预设",
            "pricing_hint": "按 Token 计费",
            "eta_hint": "约数秒～十几秒",
        },
    ),
}

# 生图常用比例（与 Seedream 尺寸表交集）
IMAGE_ASPECT_RATIOS: tuple[str, ...] = (
    "auto",
    "1:1",
    "16:9",
    "9:16",
    "4:3",
    "3:4",
    "3:2",
    "2:3",
    "21:9",
)
# Seedream / GPT Image 2：前端只给 1K/2K，避免选更高档被静默降档
IMAGE_RESOLUTIONS_STANDARD: tuple[str, ...] = ("1K", "2K")
# GPT Image 2.5 支持到 4K
IMAGE_RESOLUTIONS_GPT_IMAGE_25: tuple[str, ...] = ("1K", "2K", "4K")

VIDEO_ASPECT_RATIOS: tuple[str, ...] = ("9:16", "16:9", "1:1")
VIDEO_RESOLUTIONS_FULL: tuple[str, ...] = ("480p", "720p", "1080p")
VIDEO_RESOLUTIONS_SAFE: tuple[str, ...] = ("480p", "720p")
# MiniMax-H3：内部统一小写；不同上游插件的大小写由提交适配层兼容。
VIDEO_RESOLUTIONS_MINIMAX_H3: tuple[str, ...] = ("480p", "768p")


# 历史友好别名 / 旧连字符 id → TokenFree 点分规范 id
PRESET_MODEL_ALIASES: dict[str, str] = {
    "seedance-2-5": "seedance-2.5",
    "seedance2.5": "seedance-2.5",
    "seedance-2": "seedance-2.0",
    "seedance2": "seedance-2.0",
    "seedance-2-0": "seedance-2.0",
    "seedance2.0": "seedance-2.0",
    # Mini 上游未开通：历史选择一律落到 2.0，避免 ModelNotOpen
    "seedance-2-0-mini": "seedance-2.0",
    "seedance-2.0-mini": "seedance-2.0",
    "doubao-seedance-2-0-mini-260615": "seedance-2.0",
    "seedance-2-0-fast": "seedance-2.0-fast",
    "seedance-2.0-fast": "seedance-2.0-fast",
    "seedream-5-0-pro": "seedream-5.0-pro",
    "seedream-5.0-pro": "seedream-5.0-pro",
    "seedream-5-0": "seedream-5.0",
    "seedream-5": "seedream-5.0",
    "seedream5.0": "seedream-5.0",
    "seedream5": "seedream-5.0",
    "seedream-5-0-flash": "seedream-5.0-flash",
    "seedream-5.0-flash": "seedream-5.0-flash",
    "gpt-image-2-5": "gpt-image-2.5",
    "gpt-image-2.5": "gpt-image-2.5",
    "gpt-image-2.5-sunburst": "gpt-image-2.5",
    "gpt-image-2-5-sunburst": "gpt-image-2.5",
    "gpt-image-2.5-flare": "gpt-image-2.5",
    "gpt-image-2-5-flare": "gpt-image-2.5",
    "gemini-3.1-flash-tts": "qwen-tts-2025-05-22",
    "gemini-3.1-flash": "qwen-tts-2025-05-22",
}


def preset_ids(capability: LogicalModelCapability) -> list[str]:
    """某能力下的预设上游 id。"""
    return [str(row["id"]) for row in PRESET_MODELS.get(capability, ())]


def resolve_preset_alias(model_id: str | None) -> str:
    """将历史别名映射到预设规范 id；无映射则原样返回。"""
    raw = (model_id or "").strip()
    if not raw:
        return ""
    key = normalize_model_name(raw)
    for alias, canonical in PRESET_MODEL_ALIASES.items():
        if normalize_model_name(alias) == key:
            return canonical
    return raw


def lookup_preset_row(model_id: str | None) -> dict[str, str] | None:
    """按 id（含别名）查找预设行。"""
    mid = normalize_model_name(resolve_preset_alias(model_id))
    if not mid:
        return None
    for rows in PRESET_MODELS.values():
        for row in rows:
            if normalize_model_name(row["id"]) == mid:
                return dict(row)
    return None


def preset_display_meta(model_id: str | None) -> dict[str, str]:
    """前台目录展示：友好名、介绍、资费与大致出片时长。"""
    row = lookup_preset_row(model_id)
    if not row:
        return {"label": "", "note": "", "pricing_hint": "", "eta_hint": ""}
    return {
        "label": str(row.get("label") or ""),
        "note": str(row.get("note") or ""),
        "pricing_hint": str(row.get("pricing_hint") or ""),
        "eta_hint": str(row.get("eta_hint") or ""),
    }


def all_preset_channel_models() -> list[str]:
    """写入 TokenFree 渠道的全部预设 id（文/图/视/音）。"""
    out: list[str] = []
    seen: set[str] = set()
    for cap in ("text", "image", "video", "audio"):
        for mid in preset_ids(cap):  # type: ignore[arg-type]
            key = normalize_model_name(mid)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(mid)
    return out


def is_preset_model(capability: LogicalModelCapability, model_id: str | None) -> bool:
    """默认模型是否落在对应预设内（含历史别名）。"""
    mid = normalize_model_name(resolve_preset_alias(model_id))
    if not mid:
        return False
    return mid in {normalize_model_name(x) for x in preset_ids(capability)}


def current_model_selection(capability: str, model_id: str | None, fallback: str | None = None) -> str:
    """Replace retired choices only at submission/default selection, never in history."""
    raw = (model_id or '').strip()
    key = raw.lower()
    if capability == 'text' and (key.startswith('kimi-') or key == 'gpt-5.5'):
        candidate = current_model_selection('text', fallback) if fallback and fallback != model_id else ''
        return candidate or 'gpt-6.1-sol'
    if capability == 'image':
        if resolve_preset_alias(raw) in {'seedream-5.0-pro', 'seedream-5.0-flash'}:
            return 'seedream-5.0'
        if key == 'gpt-image-2':
            return 'gpt-image-2.5'
    return raw


def clamp_default_to_preset(capability: LogicalModelCapability, model_id: str | None) -> str:
    """非法或不空缺省时落到该能力第一项预设。"""
    raw = resolve_preset_alias(current_model_selection(capability, model_id))
    if is_preset_model(capability, raw):
        # 返回预设表里的规范写法
        for mid in preset_ids(capability):
            if normalize_model_name(mid) == normalize_model_name(raw):
                return mid
    ids = preset_ids(capability)
    return ids[0] if ids else ""


def model_generation_options(model_id: str | None) -> dict[str, Any]:
    """Compatibility facade; model capabilities are owned by registered strategies."""
    from app.services.media_models import get_strategy
    try:
        return get_strategy(model_id or "").describe()
    except ValueError:
        return {}
