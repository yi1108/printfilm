"""Resolve logical model requests to concrete upstream channels."""

from __future__ import annotations

from app.schemas_routing import DefaultModels, LogicalModel, LogicalModelCapability, ResolvedModelRoute, SystemModelChannel
from app.services.model_routing_config import (
    channel_connection_ready,
    channel_supports_model,
    infer_model_capability,
    resolve_channel_model_capability,
)
from app.services.model_settings import get_routing_snapshot


# 解析某逻辑模型的可用路由
def _routes_for_logical_model(
    logical: LogicalModel,
    capability: LogicalModelCapability,
    channels: list[SystemModelChannel],
    *,
    preferred_channel_id: str = "",
) -> list[ResolvedModelRoute]:
    bindings = sorted(
        [binding for binding in logical.bindings if binding.enabled],
        key=lambda binding: (
            0 if preferred_channel_id and binding.channel_id == preferred_channel_id else 1,
            binding.priority,
            -(binding.weight or 100),
            binding.id,
        ),
    )
    routes: list[ResolvedModelRoute] = []
    for binding in bindings:
        channel = next((item for item in channels if item.id == binding.channel_id), None)
        if not channel or not channel_connection_ready(channel):
            continue
        if not channel_supports_model(channel, binding.upstream_model):
            continue
        route = _build_route(capability, logical.id, binding.upstream_model, channel)
        if route:
            routes.append(route)
    return routes


# 解析逻辑模型到运行时路由（含 failover 候选列表）
def resolve_logical_model_candidates(
    capability: LogicalModelCapability,
    requested_model_id: str,
    *,
    preferred_channel_id: str = "",
) -> list[ResolvedModelRoute]:
    """按请求 ID 解析；不可用时回落到同能力任一可解析逻辑模型（通用模型）。"""
    snapshot = get_routing_snapshot()
    requested = (requested_model_id or "").strip()
    if not requested:
        requested = _default_model_id(snapshot.default_models, capability)

    if requested:
        logical = next(
            (
                model
                for model in snapshot.logical_models
                if model.enabled
                and model.capability == capability
                and model.id.lower() == requested.lower()
            ),
            None,
        )
        if logical:
            routes = _routes_for_logical_model(
                logical,
                capability,
                snapshot.channels,
                preferred_channel_id=preferred_channel_id,
            )
            if routes:
                return routes

    # 默认/请求模型失效时，回落到同能力第一个可解析模型（DeepSeek / Kimi / 其它兼容均可）
    for model in snapshot.logical_models:
        if not model.enabled or model.capability != capability:
            continue
        if requested and model.id.lower() == requested.lower():
            continue
        routes = _routes_for_logical_model(
            model,
            capability,
            snapshot.channels,
            preferred_channel_id=preferred_channel_id,
        )
        if routes:
            return routes

    if snapshot.logical_models:
        return []

    if not requested:
        return []
    ordered = snapshot.channels
    if preferred_channel_id:
        ordered = [
            *([item for item in snapshot.channels if item.id == preferred_channel_id]),
            *[item for item in snapshot.channels if item.id != preferred_channel_id],
        ]
    routes = []
    for channel in ordered:
        if not channel.enabled or not channel_connection_ready(channel):
            continue
        if not channel_supports_model(channel, requested):
            continue
        if resolve_channel_model_capability(channel, requested) != capability:
            continue
        route = _build_route(capability, requested, requested, channel)
        if route:
            routes.append(route)
    return routes


# 解析首选逻辑模型路由
def resolve_logical_model(
    capability: LogicalModelCapability,
    requested_model_id: str,
    *,
    preferred_channel_id: str = "",
) -> ResolvedModelRoute | None:
    candidates = resolve_logical_model_candidates(
        capability,
        requested_model_id,
        preferred_channel_id=preferred_channel_id,
    )
    return candidates[0] if candidates else None


# 将前端 alias 映射为逻辑模型 ID
def resolve_logical_model_id(
    capability: LogicalModelCapability,
    model_id: str | None,
) -> str:
    raw = (model_id or "").strip()
    aliases = _capability_aliases(capability)
    if not raw:
        snapshot = get_routing_snapshot()
        return _default_model_id(snapshot.default_models, capability) or raw
    return aliases.get(raw.lower(), raw)


# 解析上游 endpoint（兼容旧 alias 逻辑）
def resolve_upstream_model(
    capability: LogicalModelCapability,
    model_id: str | None,
) -> str:
    logical_id = resolve_logical_model_id(capability, model_id)
    route = resolve_logical_model(capability, logical_id)
    if route:
        return route.upstream_model
    snapshot = get_routing_snapshot()
    fallback = _legacy_upstream_fallback(capability, model_id, snapshot.default_models)
    if fallback:
        return fallback
    from app.config import get_settings

    settings = get_settings()
    if capability == "text":
        return settings.model_llm
    if capability == "image":
        return settings.model_image
    if capability == "video":
        return settings.model_video
    return settings.model_audio


def _build_route(
    capability: LogicalModelCapability,
    logical_model_id: str,
    upstream_model: str,
    channel: SystemModelChannel,
) -> ResolvedModelRoute | None:
    api_key = channel.api_key or ""
    if channel.protocol != "volc_tts" and not api_key:
        return None
    protocol = channel.protocol if channel.protocol != "auto" else _auto_protocol(channel, upstream_model)
    return ResolvedModelRoute(
        capability=capability,
        logical_model_id=logical_model_id,
        upstream_model=upstream_model,
        channel_id=channel.id,
        channel_name=channel.name,
        base_url=(channel.base_url or "").rstrip("/"),
        api_key=api_key,
        protocol=protocol,
        api_format=channel.api_format,
    )


def _auto_protocol(channel: SystemModelChannel, upstream_model: str) -> str:
    explicit = (channel.protocol or "auto").lower()
    if explicit != "auto":
        return explicit
    cap = infer_model_capability(upstream_model)
    if cap == "audio":
        return "volc_tts"
    if cap in {"image", "video"}:
        return "ark"
    return "openai"


def _default_model_id(defaults: DefaultModels, capability: LogicalModelCapability) -> str:
    if capability == "text":
        return defaults.text_model
    if capability == "image":
        return defaults.image_model
    if capability == "video":
        return defaults.video_model
    return defaults.audio_model


def _capability_aliases(capability: LogicalModelCapability) -> dict[str, str]:
    if capability == "image":
        return {
            "seedream-5.0": "seedream-5.0",
            "seedream-5": "seedream-5.0",
            "5.0": "seedream-5.0",
            "seedream-4.5": "seedream-4.5",
            "seedream-4": "seedream-4.5",
            "4.5": "seedream-4.5",
        }
    if capability == "video":
        return {
            "seedance-2.5": "seedance-2.5",
            "seedance-2": "seedance-2.5",
            "seedance-1.5": "seedance-2.5",
            "seedance-1": "seedance-2.5",
        }
    return {}


def _legacy_upstream_fallback(
    capability: LogicalModelCapability,
    model_id: str | None,
    defaults: DefaultModels,
) -> str:
    from app.config import get_settings

    settings = get_settings()
    raw = (model_id or "").strip()
    if capability == "image":
        mid = raw.lower()
        if mid in {"", "seedream-5.0", "seedream-5", "5.0"}:
            route = resolve_logical_model("image", defaults.image_model or "seedream-5.0")
            return route.upstream_model if route else settings.model_image
        if mid in {"seedream-4.5", "seedream-4", "4.5"}:
            route = resolve_logical_model("image", "seedream-4.5")
            return route.upstream_model if route else ((settings.model_image_45 or "").strip() or settings.model_image)
        return raw or settings.model_image
    if capability == "video":
        aliases = _capability_aliases("video")
        logical = aliases.get(raw.lower(), raw) if raw else defaults.video_model
        route = resolve_logical_model("video", logical or defaults.video_model)
        return route.upstream_model if route else settings.model_video
    return raw
