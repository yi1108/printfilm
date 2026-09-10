"""Synchronize and validate logical models against upstream channels."""

from __future__ import annotations

import re

from app.schemas_routing import (
    DefaultModels,
    LogicalModel,
    LogicalModelBinding,
    LogicalModelCapability,
    SystemModelChannel,
)

CAPABILITY_DEFAULT_KEYS: dict[LogicalModelCapability, str] = {
    "text": "text_model",
    "image": "image_model",
    "video": "video_model",
    "audio": "audio_model",
}


# 规范化模型名用于比较
def normalize_model_name(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


# 从模型名推断能力类型
def infer_model_capability(model: str) -> LogicalModelCapability:
    mid = normalize_model_name(model)
    if not mid:
        return "text"
    if "tts" in mid or mid.startswith("zh_") or "speaker" in mid or mid.startswith("s_"):
        return "audio"
    if "seedance" in mid or "video" in mid or "i2v" in mid:
        return "video"
    if "seedream" in mid or "dream" in mid or "image" in mid:
        return "image"
    return "text"


# 判断渠道是否具备连接信息
def channel_connection_ready(channel: SystemModelChannel) -> bool:
    if not channel.enabled:
        return False
    if channel.protocol == "volc_tts":
        return bool(channel.has_api_key or channel.base_url)
    return bool(channel.base_url and channel.has_api_key)


# 判断渠道是否包含指定上游模型
def channel_supports_model(channel: SystemModelChannel, upstream_model: str) -> bool:
    target = normalize_model_name(upstream_model)
    if not target:
        return False
    return any(normalize_model_name(item) == target for item in channel.models)


# 解析渠道下单模型的能力
def resolve_channel_model_capability(channel: SystemModelChannel, upstream_model: str) -> LogicalModelCapability:
    protocol = (channel.protocol or "auto").lower()
    if protocol == "openai":
        return "text"
    if protocol == "ark":
        return infer_model_capability(upstream_model)
    if protocol == "volc_tts":
        return "audio"
    advanced = channel.advanced_config
    if advanced:
        if advanced.text_model and normalize_model_name(upstream_model) == normalize_model_name(advanced.text_model):
            return "text"
        if advanced.image_model and normalize_model_name(upstream_model) == normalize_model_name(advanced.image_model):
            return "image"
        if advanced.video_model and normalize_model_name(upstream_model) == normalize_model_name(advanced.video_model):
            return "video"
    return infer_model_capability(upstream_model)


# 根据渠道列表同步逻辑模型
def synchronize_logical_models_with_channels(
    existing_models: list[LogicalModel],
    channels: list[SystemModelChannel],
) -> list[LogicalModel]:
    catalog: dict[str, dict] = {}
    for channel_index, channel in enumerate(channels):
        if not channel.enabled:
            continue
        for upstream_model in channel.models:
            raw = (upstream_model or "").strip()
            if not raw:
                continue
            key = normalize_model_name(raw)
            entry = catalog.get(key)
            if not entry:
                entry = {
                    "upstream_model": raw,
                    "capability": resolve_channel_model_capability(channel, raw),
                    "bindings": [],
                }
                catalog[key] = entry
            if not any(item["channel"].id == channel.id for item in entry["bindings"]):
                entry["bindings"].append(
                    {"channel": channel, "channel_index": channel_index, "upstream_model": raw}
                )

    used_existing_ids: set[str] = set()
    used_model_ids: set[str] = set()
    result: list[LogicalModel] = []
    for model_key, catalog_model in sorted(catalog.items(), key=lambda item: item[0]):
        matching = [
            model
            for model in existing_models
            if any(
                normalize_model_name(binding.upstream_model) == model_key
                for binding in model.bindings
            )
        ]
        existing = next(
            (
                model
                for model in matching
                if normalize_model_name(model.id) == model_key and model.id.lower() not in used_existing_ids
            ),
            None,
        ) or next((model for model in matching if model.id.lower() not in used_existing_ids), None)
        if existing:
            used_existing_ids.add(existing.id.lower())
        logical_id = _unique_logical_model_id(existing.id if existing else catalog_model["upstream_model"], used_model_ids)
        bindings: list[LogicalModelBinding] = []
        for item in catalog_model["bindings"]:
            channel: SystemModelChannel = item["channel"]
            upstream = item["upstream_model"]
            stored = _find_stored_binding(existing_models, channel.id, upstream)
            bindings.append(
                LogicalModelBinding(
                    id=(stored.id if stored else f"{channel.id}:{upstream}"),
                    channel_id=channel.id,
                    upstream_model=upstream,
                    enabled=stored.enabled if stored else True,
                    priority=stored.priority if stored else int(item["channel_index"]) + 1,
                    weight=stored.weight if stored else None,
                )
            )
        bindings.sort(key=lambda binding: (binding.priority, binding.id))
        result.append(
            LogicalModel(
                id=logical_id,
                name=(existing.name if existing and existing.name else catalog_model["upstream_model"]),
                capability=(existing.capability if existing else catalog_model["capability"]),
                enabled=existing.enabled if existing else True,
                bindings=bindings,
            )
        )
    return result


# 规范化默认模型 ID
def normalize_default_models(
    defaults: DefaultModels | None,
    logical_models: list[LogicalModel],
    channels: list[SystemModelChannel],
) -> DefaultModels:
    raw = defaults or DefaultModels()
    normalized = DefaultModels()
    for capability, attr in CAPABILITY_DEFAULT_KEYS.items():
        model_id = getattr(raw, attr, "") or ""
        if model_id and is_logical_model_resolvable(logical_models, channels, capability, model_id):
            setattr(normalized, attr, model_id)
            continue
        fallback = next(
            (
                model
                for model in logical_models
                if model.enabled
                and model.capability == capability
                and is_logical_model_resolvable(logical_models, channels, capability, model.id)
            ),
            None,
        )
        setattr(normalized, attr, fallback.id if fallback else "")
    return normalized


# 判断逻辑模型是否可解析到可用渠道
def is_logical_model_resolvable(
    logical_models: list[LogicalModel],
    channels: list[SystemModelChannel],
    capability: LogicalModelCapability,
    model_id: str,
) -> bool:
    return resolve_logical_model_config(logical_models, channels, capability, model_id) is not None


# 解析单条逻辑模型配置
def resolve_logical_model_config(
    logical_models: list[LogicalModel],
    channels: list[SystemModelChannel],
    capability: LogicalModelCapability,
    model_id: str,
):
    requested = (model_id or "").strip()
    if not requested:
        return None
    logical = next(
        (
            model
            for model in logical_models
            if model.enabled
            and model.capability == capability
            and model.id.lower() == requested.lower()
        ),
        None,
    )
    if not logical:
        return None
    bindings = sorted(
        [binding for binding in logical.bindings if binding.enabled],
        key=lambda binding: (binding.priority, binding.id),
    )
    for binding in bindings:
        channel = next((item for item in channels if item.id == binding.channel_id), None)
        if not channel or not channel_connection_ready(channel):
            continue
        if not channel_supports_model(channel, binding.upstream_model):
            continue
        return {"logical_model": logical, "binding": binding, "channel": channel}
    return None


# 校验路由配置
def model_routing_validation_errors(
    logical_models: list[LogicalModel],
    channels: list[SystemModelChannel],
    defaults: DefaultModels,
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    channel_ids = {channel.id for channel in channels}
    for model in logical_models:
        key = (model.id or "").strip().lower()
        if not key:
            errors.append("逻辑模型 ID 不能为空")
        elif key in seen_ids:
            errors.append(f"逻辑模型 ID 重复：{model.id}")
        seen_ids.add(key)
        if not model.bindings:
            errors.append(f"逻辑模型 {model.name or model.id} 至少需要一个渠道绑定")
        binding_keys: set[str] = set()
        for binding in model.bindings:
            binding_key = f"{binding.channel_id}:{normalize_model_name(binding.upstream_model)}"
            if binding.channel_id not in channel_ids:
                errors.append(f"逻辑模型 {model.id} 引用了不存在的渠道 {binding.channel_id}")
            else:
                channel = next(item for item in channels if item.id == binding.channel_id)
                if not channel_supports_model(channel, binding.upstream_model):
                    errors.append(
                        f"渠道 {channel.name} 未启用上游模型 {binding.upstream_model}"
                    )
            if binding_key in binding_keys:
                errors.append(f"逻辑模型 {model.id} 存在重复绑定")
            binding_keys.add(binding_key)
    labels = {"text": "文本", "image": "图片", "video": "视频", "audio": "音频"}
    for capability, attr in CAPABILITY_DEFAULT_KEYS.items():
        model_id = getattr(defaults, attr, "") or ""
        if model_id and not is_logical_model_resolvable(logical_models, channels, capability, model_id):
            errors.append(f"默认{labels[capability]}模型不可解析：{model_id}")
    return list(dict.fromkeys(errors))


def _find_stored_binding(
    models: list[LogicalModel],
    channel_id: str,
    upstream_model: str,
) -> LogicalModelBinding | None:
    key = normalize_model_name(upstream_model)
    for model in models:
        for binding in model.bindings:
            if binding.channel_id == channel_id and normalize_model_name(binding.upstream_model) == key:
                return binding
    return None


def _unique_logical_model_id(value: str, used_ids: set[str]) -> str:
    base = (value or "model").strip() or "model"
    candidate = base
    suffix = 2
    while candidate.lower() in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate.lower())
    return candidate
