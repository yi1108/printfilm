"""Load, cache, and persist model routing + flat runtime settings."""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings, reload_settings
from app.models_settings import AppSettings, SystemModelChannelRow
from app.schemas_routing import (
    AdminRoutingSettingsOut,
    AdminRoutingSettingsPatch,
    DefaultModels,
    LogicalModel,
    LogicalModelCapability,
    SystemChannelAdvancedConfig,
    SystemModelChannel,
    default_models_from_dict,
    default_models_to_dict,
)
from app.schemas_settings import (
    SECRET_FIELD_FLAGS,
    SECRET_FIELDS,
    AdminModelSettingsOut,
    AdminModelSettingsPatch,
    ModelCapabilityReadiness,
    model_config_field_names,
)
from app.services.model_routing_config import (
    model_routing_validation_errors,
    normalize_default_models,
    resolve_logical_model_config,
    synchronize_logical_models_with_channels,
)

logger = logging.getLogger("app.model_settings")

ENCRYPTED_PREFIX = "enc:"

_overlay: dict[str, Any] = {}


@dataclass
class RoutingSnapshot:
    channels: list[SystemModelChannel]
    logical_models: list[LogicalModel]
    default_models: DefaultModels
    media_reference_limits: dict[str, dict[str, int]] = field(default_factory=dict)


_routing_snapshot = RoutingSnapshot(channels=[], logical_models=[], default_models=DefaultModels())


# 从 secret_key 派生 Fernet 密钥
def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


# 加密敏感字段
def _encrypt_secret(value: str) -> str:
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTED_PREFIX}{token}"


# 解密敏感字段；密钥轮换/错配时返回空串，避免拖垮启动
def _decrypt_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    token = value[len(ENCRYPTED_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("密文字段无法用当前 SECRET_KEY 解密，已忽略（需在管理端重填）")
        return ""


# 返回当前路由快照
def get_routing_snapshot() -> RoutingSnapshot:
    return _routing_snapshot


# 返回 flat overlay
def get_overlay_dict() -> dict[str, Any]:
    return dict(_overlay)


# 刷新 flat overlay
def _refresh_overlay(config: dict[str, Any]) -> None:
    global _overlay
    flat = config.get("flat") if isinstance(config.get("flat"), dict) else config
    # 空串必须保留：它是管理端「清除密钥」写入的显式值，
    # 若在此过滤，get_settings() 会回落 .env 中的旧密钥——界面显示已清除、请求仍带旧 Key。
    # 仅 None（DB 未设置该字段）跳过，让 base Settings 默认值生效。
    _overlay = {
        field: flat[field]
        for field in model_config_field_names()
        if field in flat and flat[field] is not None
    }


# 刷新路由快照
def _refresh_routing_snapshot(
    channels: list[SystemModelChannel],
    logical_models: list[LogicalModel],
    default_models: DefaultModels,
    media_reference_limits: dict | None = None,
) -> None:
    global _routing_snapshot
    _routing_snapshot = RoutingSnapshot(
        channels=channels,
        logical_models=logical_models,
        default_models=default_models,
        media_reference_limits=media_reference_limits or {},
    )


# 从 env 构建默认渠道（开源版仅 TokenFree）
def _bootstrap_channels_from_env(settings: Settings | None = None) -> list[SystemModelChannel]:
    from app.services.tokenfree_gateway import locked_tokenfree_channel
    from app.services.tokenfree_pricing import canonicalize_channel_models

    src = settings or get_settings()
    key = (src.openai_api_key or src.ark_api_key or "").strip()
    models = canonicalize_channel_models(
        [
            src.model_llm,
            src.model_image,
            src.model_image_45,
            src.model_video,
            src.model_video_2,
            src.model_audio,
        ]
    )
    return [locked_tokenfree_channel(api_key=key, models=models, enabled=True)]


def _seedance_logical_meta(upstream: str) -> tuple[str, str]:
    """按接入点 ID 推断 Seedance 逻辑模型（2.0 vs 2.5 vs Mini）；id 与 TokenFree 点分目录对齐。"""
    mid = (upstream or "").strip().lower()
    if "mini" in mid:
        # TokenFree→Ark mini 未开通，逻辑名并入 2.0
        return "seedance-2.0", "Seedance 2.0"
    if "fast" in mid:
        return "seedance-2.0-fast", "Seedance 2.0 Fast"
    if any(token in mid for token in ("2-5", "2.5", "260628")):
        return "seedance-2.5", "Seedance 2.5"
    if any(token in mid for token in ("2-0", "2.0", "260128", "seedance-2")):
        return "seedance-2.0", "Seedance 2.0"
    return "seedance-2.5", "Seedance 2.5"


def _append_seedance_alias(
    alias_models: list[LogicalModel],
    *,
    upstream: str,
    logical_id: str,
    name: str,
    bindings_for_upstream,
) -> None:
    if any(model.id == logical_id for model in alias_models):
        return
    bindings = bindings_for_upstream(upstream)
    if not bindings:
        return
    alias_models.append(
        LogicalModel(
            id=logical_id,
            name=name,
            capability="video",
            enabled=True,
            bindings=bindings,
        )
    )


def _merge_friendly_alias_models(
    synced: list[LogicalModel],
    aliases: list[LogicalModel],
) -> list[LogicalModel]:
    """保留 seedance/seedream 友好别名；去掉与别名同上游的 raw endpoint 重复项。"""
    from app.services.model_routing_config import normalize_model_name

    if not aliases:
        return synced
    alias_ids = {model.id for model in aliases}
    alias_upstream = {
        normalize_model_name(binding.upstream_model)
        for alias in aliases
        for binding in alias.bindings
    }
    merged: list[LogicalModel] = []
    seen_ids: set[str] = set()
    for model in synced:
        model_key = normalize_model_name(model.id)
        binding_keys = {normalize_model_name(b.upstream_model) for b in model.bindings}
        if (
            model.capability in {"video", "image"}
            and model.id not in alias_ids
            and binding_keys
            and binding_keys <= alias_upstream
            and model_key in binding_keys
        ):
            continue
        if model.id.lower() in seen_ids:
            continue
        merged.append(model)
        seen_ids.add(model.id.lower())
    for alias in aliases:
        if alias.id.lower() in seen_ids:
            continue
        merged.append(alias)
        seen_ids.add(alias.id.lower())
    return merged


# TokenFree 价目真实 id（兼容旧前端别名 → 同名逻辑模型，不做换绑）
_TOKENFREE_IMAGE_IDS: dict[str, str] = {
    "seedream-5.0": "seedream-5.0",
    "seedream-5": "seedream-5.0",
    "5.0": "seedream-5-0-pro",
    "seedream-4.5": "seedream-4-5",
    "seedream-4": "seedream-4-5",
    "4.5": "seedream-4-5",
}


# 从 env 构建默认逻辑模型与默认模型 ID
def _bootstrap_logical_from_channels(channels: list[SystemModelChannel]) -> tuple[list[LogicalModel], DefaultModels]:
    logical_models = synchronize_logical_models_with_channels([], channels)
    settings = get_settings()
    alias_models: list[LogicalModel] = []

    def _bindings_for_upstream(upstream: str) -> list:
        from app.services.tokenfree_pricing import canonicalize_channel_model_id

        wanted = {(upstream or "").strip(), canonicalize_channel_model_id(upstream)}
        wanted.discard("")
        result = []
        for model in logical_models:
            for binding in model.bindings:
                raw = (binding.upstream_model or "").strip()
                if raw in wanted or canonicalize_channel_model_id(raw) in wanted:
                    result.append(binding.model_copy())
        return result

    # 图模不再造 seedream-5.0 友好别名；仅视频保留 Seedance 短名
    if settings.model_video:
        logical_id, name = _seedance_logical_meta(settings.model_video)
        _append_seedance_alias(
            alias_models,
            upstream=settings.model_video,
            logical_id=logical_id,
            name=name,
            bindings_for_upstream=_bindings_for_upstream,
        )
    if settings.model_video_2:
        logical_id_2, name_2 = _seedance_logical_meta(settings.model_video_2)
        _append_seedance_alias(
            alias_models,
            upstream=settings.model_video_2,
            logical_id=logical_id_2,
            name=name_2,
            bindings_for_upstream=_bindings_for_upstream,
        )
    default_video = ""
    if settings.model_video:
        default_video, _ = _seedance_logical_meta(settings.model_video)
    elif settings.model_video_2:
        default_video = "seedance-2.0"
    synced = synchronize_logical_models_with_channels(logical_models, channels)
    merged = _merge_friendly_alias_models(synced, alias_models)
    # 默认图模 = 渠道/价目真实名（如 seedream-5-0-pro）
    image_default = (settings.model_image or "").strip()
    image_default = _TOKENFREE_IMAGE_IDS.get(image_default.lower(), image_default)
    defaults = DefaultModels(
        text_model=settings.model_llm,
        image_model=image_default,
        video_model=default_video,
        audio_model=settings.model_audio,
    )
    return merged, normalize_default_models(defaults, merged, channels)


# 历史渠道协议已下线，读库时收成仍支持的值，避免校验失败
_LIVE_CHANNEL_PROTOCOLS = {"openai", "auto"}
_LIVE_API_FORMATS = {"openai"}


def _coerce_channel_protocol(value: str | None) -> str:
    """把已删除的渠道协议收成 auto。"""
    raw = (value or "auto").strip().lower() or "auto"
    return raw if raw in _LIVE_CHANNEL_PROTOCOLS else "auto"


def _coerce_api_format(value: str | None) -> str:
    """把已删除的调用格式收成 openai。"""
    raw = (value or "openai").strip().lower() or "openai"
    return raw if raw in _LIVE_API_FORMATS else "openai"


# ORM 行转领域模型（admin 视图，密钥打码）
def _channel_row_to_admin(row: SystemModelChannelRow) -> SystemModelChannel:
    api_key = _decrypt_secret(row.api_key_ciphertext or "")
    return SystemModelChannel(
        id=row.id,
        name=row.name,
        base_url=row.base_url or "",
        api_key="",
        has_api_key=bool(api_key),
        api_format=_coerce_api_format(row.api_format),
        protocol=_coerce_channel_protocol(row.protocol),
        models=list(row.models or []),
        enabled=bool(row.enabled),
        sort_order=int(row.sort_order or 0),
        advanced_config=SystemChannelAdvancedConfig.model_validate(row.advanced_config)
        if row.advanced_config
        else None,
    )


# 运行时渠道（含明文密钥）
def _channel_row_to_runtime(row: SystemModelChannelRow) -> SystemModelChannel:
    channel = _channel_row_to_admin(row)
    return channel.model_copy(update={"api_key": _decrypt_secret(row.api_key_ciphertext or "")})


async def _get_or_create_app_row(db: AsyncSession) -> AppSettings:
    row = (await db.execute(select(AppSettings).where(AppSettings.id == "default"))).scalar_one_or_none()
    if row:
        return row
    row = AppSettings(id="default", config_json={"flat": _encrypt_flat_config(_settings_to_dict())})
    db.add(row)
    await db.flush()
    return row


async def _load_channels(db: AsyncSession, *, runtime: bool) -> list[SystemModelChannel]:
    rows = list(
        (await db.execute(select(SystemModelChannelRow).order_by(SystemModelChannelRow.sort_order, SystemModelChannelRow.id)))
        .scalars()
        .all()
    )
    if not rows:
        return []
    if runtime:
        return [_channel_row_to_runtime(row) for row in rows]
    return [_channel_row_to_admin(row) for row in rows]


async def _ensure_bootstrapped_channels(db: AsyncSession) -> list[SystemModelChannelRow]:
    existing = list((await db.execute(select(SystemModelChannelRow))).scalars().all())
    if existing:
        await _ensure_tokenfree_channel(db, existing)
        return list((await db.execute(select(SystemModelChannelRow))).scalars().all())
    channels = _bootstrap_channels_from_env()
    rows: list[SystemModelChannelRow] = []
    for channel in channels:
        row = SystemModelChannelRow(
            id=channel.id,
            name=channel.name,
            base_url=channel.base_url,
            api_key_ciphertext=_encrypt_secret(channel.api_key) if channel.api_key else None,
            api_format=channel.api_format,
            protocol=channel.protocol,
            models=channel.models,
            enabled=channel.enabled,
            sort_order=channel.sort_order,
            advanced_config=channel.advanced_config.model_dump() if channel.advanced_config else None,
        )
        db.add(row)
        rows.append(row)
    logical_models, defaults = _bootstrap_logical_from_channels(channels)
    app_row = await _get_or_create_app_row(db)
    # A first direct settings PATCH may have already saved payment values.
    # Preserve them when initializing model channels, and encrypt env secrets.
    config = dict(app_row.config_json or {})
    config["flat"] = _encrypt_flat_config(_effective_flat(_decrypt_flat_config(config)))
    config.setdefault("logical_models", [model.model_dump() for model in logical_models])
    config.setdefault("default_models", default_models_to_dict(defaults))
    app_row.config_json = config
    await db.commit()
    return rows


async def _ensure_tokenfree_channel(db: AsyncSession, existing: list[SystemModelChannelRow]) -> None:
    """锁定唯一 TokenFree 渠道：固定 Base URL，其它渠道停用。"""
    from app.services.tokenfree_gateway import (
        TOKENFREE_BASE_URL,
        TOKENFREE_CHANNEL_ID,
        TOKENFREE_CHANNEL_NAME,
        pick_migratable_api_key,
    )

    runtime = [_channel_row_to_runtime(row) for row in existing]
    migrated_key = pick_migratable_api_key(runtime)
    token_row = next((row for row in existing if row.id == TOKENFREE_CHANNEL_ID), None)
    if token_row is None:
        token_row = SystemModelChannelRow(id=TOKENFREE_CHANNEL_ID)
        db.add(token_row)
    current_key = _decrypt_secret(token_row.api_key_ciphertext or "")
    token_row.name = TOKENFREE_CHANNEL_NAME
    token_row.base_url = TOKENFREE_BASE_URL
    token_row.api_format = "openai"
    token_row.protocol = "auto"
    token_row.enabled = True
    token_row.sort_order = 0
    token_row.advanced_config = None
    if not current_key and migrated_key:
        token_row.api_key_ciphertext = _encrypt_secret(migrated_key)
        current_key = migrated_key
    from app.services.media_model_presets import all_preset_channel_models

    # 渠道 models 固定为站点预设并集（含 gpt-image-2 / gpt-image-2.5 / 仅 qwen-tts）
    preset = all_preset_channel_models()
    if list(token_row.models or []) != preset:
        token_row.models = preset
    for row in existing:
        if row.id != TOKENFREE_CHANNEL_ID:
            row.enabled = False
    await db.commit()


def _settings_to_dict(settings: Settings | None = None) -> dict[str, Any]:
    src = settings or get_settings()
    result = {field: getattr(src, field) for field in model_config_field_names()}
    # Preserve legacy environment/file credentials when first adopting DB settings.
    from app.marketplace.app_settings import get_app_settings
    from app.marketplace.apple_configuration import material
    cfg = get_app_settings()
    for key in result:
        if key.startswith("apple_") and key not in _overlay:
            result[key] = getattr(cfg, key, result[key])
    result["apple_app_id"] = result["apple_app_id"] or 0
    if "apple_private_key" not in _overlay or "apple_root_certificates" not in _overlay:
        try:
            private, roots = material(cfg)
            if "apple_private_key" not in _overlay:
                result["apple_private_key"] = private
            if "apple_root_certificates" not in _overlay and roots:
                from cryptography import x509
                from cryptography.hazmat.primitives import serialization
                result["apple_root_certificates"] = "".join(x509.load_der_x509_certificate(root).public_bytes(serialization.Encoding.PEM).decode() for root in roots)
        except (OSError, ValueError):
            pass
    return result


def _decrypt_flat_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """解密 flat 密钥；解不开则删掉该字段，让运行时回落到 .env，避免空串/坏密文盖住环境变量。"""
    data = dict((raw or {}).get("flat") or raw or {})
    for field in SECRET_FIELDS:
        if field not in data or not data[field]:
            continue
        raw_val = str(data[field])
        plain = _decrypt_secret(raw_val)
        # 仍带 enc: 前缀说明密钥错配/双重加密，丢弃以免污染 overlay
        if raw_val.startswith(ENCRYPTED_PREFIX) and (not plain or plain.startswith(ENCRYPTED_PREFIX)):
            logger.warning("flat 密钥字段 %s 无法解密，已忽略并回落 .env", field)
            data.pop(field, None)
            continue
        data[field] = plain
    return data


def _encrypt_flat_config(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    for field in SECRET_FIELDS:
        value = data.get(field)
        if value:
            data[field] = _encrypt_secret(str(value))
    return data


def _effective_flat(stored: dict[str, Any] | None) -> dict[str, Any]:
    merged = _settings_to_dict()
    if stored:
        for field in model_config_field_names():
            if field in stored and stored[field] is not None:
                merged[field] = stored[field]
    return merged


async def _compose_runtime_state(db: AsyncSession) -> tuple[list[SystemModelChannel], list[LogicalModel], DefaultModels, dict[str, Any], AppSettings]:
    """组装运行时路由：始终按渠道 models 同步逻辑模型，默认文字模型随可用上游回落。"""
    app_row = await _get_or_create_app_row(db)
    await _ensure_bootstrapped_channels(db)
    # 同步能力前预热 TokenFree 价目（tags / endpoints）
    try:
        from app.services.tokenfree_pricing import ensure_official_rates

        await ensure_official_rates()
    except Exception:  # noqa: BLE001
        pass
    channels = await _load_channels(db, runtime=True)
    config = dict(app_row.config_json or {})
    logical_models = [LogicalModel.model_validate(item) for item in config.get("logical_models") or []]
    default_models = default_models_from_dict(config.get("default_models"))
    if not logical_models and channels:
        logical_models, default_models = _bootstrap_logical_from_channels(
            [_channel_row_to_admin(row) for row in (await db.execute(select(SystemModelChannelRow))).scalars().all()]
        )
    # 渠道 models 变更后，丢弃失效绑定并补齐新上游（支持任意 OpenAI 兼容模型）
    logical_models = synchronize_logical_models_with_channels(logical_models, channels)
    boot_logical, boot_defaults = _bootstrap_logical_from_channels(
        [_channel_row_to_admin(row) for row in (await db.execute(select(SystemModelChannelRow))).scalars().all()]
    )
    # 仅合并视频 Seedance 短名；图模一律用 TokenFree 渠道真实 id，不做 seedream-5.0 换绑
    alias_ids = {"seedance-2.5", "seedance-2.0", "seedance-2", "seedance-2.0-mini", "seedance-2.0-fast"}
    logical_models = _merge_friendly_alias_models(
        logical_models,
        [model for model in boot_logical if model.id in alias_ids],
    )
    if not (default_models.video_model or "").strip() and boot_defaults.video_model:
        default_models = default_models.model_copy(update={"video_model": boot_defaults.video_model})
    # 默认图模若仍是旧别名，收到价目真实名
    image_default = (default_models.image_model or boot_defaults.image_model or "").strip()
    image_default = _TOKENFREE_IMAGE_IDS.get(image_default.lower(), image_default)
    if image_default:
        default_models = default_models.model_copy(update={"image_model": image_default})
    from app.services.media_model_presets import clamp_default_to_preset

    # 启动/读缓存时钳回预设（配音 gemini→qwen；非法图模→Seedream Pro 等）
    default_models = default_models.model_copy(
        update={
            "text_model": clamp_default_to_preset("text", default_models.text_model),
            "image_model": clamp_default_to_preset("image", default_models.image_model),
            "video_model": clamp_default_to_preset("video", default_models.video_model),
            "audio_model": clamp_default_to_preset("audio", default_models.audio_model),
        }
    )
    default_models = normalize_default_models(default_models, logical_models, channels)
    flat = _effective_flat(_decrypt_flat_config(config))
    from app.services.tokenfree_gateway import apply_tokenfree_flat_overlay

    flat = apply_tokenfree_flat_overlay(flat, channels)
    if default_models.text_model:
        flat["model_llm"] = default_models.text_model
    if default_models.image_model:
        flat["model_image"] = default_models.image_model
    if default_models.video_model:
        flat["model_video"] = default_models.video_model
    if default_models.audio_model:
        flat["model_audio"] = default_models.audio_model
    # 4.5 档用价目名
    flat["model_image_45"] = (flat.get("model_image_45") or "seedream-4-5").strip()
    flat["model_image_45"] = _TOKENFREE_IMAGE_IDS.get(flat["model_image_45"].lower(), flat["model_image_45"])
    # Initial channel bootstrap can expire the server-updated timestamp. Fetch
    # it explicitly instead of causing async ORM IO while serializing output.
    await db.flush()
    await db.refresh(app_row, attribute_names=["updated_at"])
    return channels, logical_models, default_models, flat, app_row


async def load_model_settings_cache(db: AsyncSession) -> None:
    """加载路由快照；若与渠道不同步则回写 healed 配置，避免默认仍钉死旧模型名。"""
    channels, logical_models, default_models, flat, app_row = await _compose_runtime_state(db)
    config = dict(app_row.config_json or {})
    old_ids = {(item or {}).get("id") for item in (config.get("logical_models") or [])}
    new_ids = {model.id for model in logical_models}
    old_caps = {
        (item or {}).get("id"): (item or {}).get("capability")
        for item in (config.get("logical_models") or [])
    }
    new_caps = {model.id: model.capability for model in logical_models}
    old_defaults = default_models_from_dict(config.get("default_models"))
    flat_cfg = dict(config.get("flat") or {})
    flat_cfg.update({k: v for k, v in flat.items() if v not in (None, "")})
    flat_changed = flat_cfg != dict(config.get("flat") or {})
    if old_ids != new_ids or old_caps != new_caps or old_defaults != default_models or flat_changed:
        config["logical_models"] = [model.model_dump() for model in logical_models]
        config["default_models"] = default_models_to_dict(default_models)
        config["flat"] = _encrypt_flat_config(flat_cfg) if flat_cfg else config.get("flat")
        app_row.config_json = config
        await db.commit()
    from app.services.media_models.reference_limits import reference_limit_settings
    _refresh_routing_snapshot(channels, logical_models, default_models,
                              reference_limit_settings(config.get("media_reference_limits")))
    _refresh_overlay({"flat": flat})
    reload_settings()
    from app.marketplace.app_settings import get_app_settings
    get_app_settings.cache_clear()


def _build_readiness(
    channels: list[SystemModelChannel],
    logical_models: list[LogicalModel],
    defaults: DefaultModels,
) -> list[ModelCapabilityReadiness]:
    labels = {"text": "文本", "image": "图像", "video": "视频", "audio": "语音"}
    items: list[ModelCapabilityReadiness] = []
    for capability, attr in {
        "text": "text_model",
        "image": "image_model",
        "video": "video_model",
        "audio": "audio_model",
    }.items():
        cap: LogicalModelCapability = capability
        model_id = getattr(defaults, attr) or ""
        resolved = resolve_logical_model_config(logical_models, channels, cap, model_id) if model_id else None
        items.append(
            ModelCapabilityReadiness(
                capability=capability,
                label=labels[capability],
                model=model_id,
                ready=bool(resolved),
                message=f"路由至渠道 {resolved['channel'].name}" if resolved else f"需配置默认{labels[capability]}模型与渠道绑定",
            )
        )
    return items


def _to_admin_flat_out(flat: dict[str, Any], *, source: str, updated_at, channels, logical_models, defaults) -> AdminModelSettingsOut:
    from app.services.stripe_payments import is_ready

    payload = {field: flat.get(field) for field in model_config_field_names()}
    for field, flag in SECRET_FIELD_FLAGS.items():
        payload[field] = ""
        payload[flag] = bool(str(flat.get(field) or "").strip())
    payload["source"] = source
    payload["updated_at"] = updated_at
    payload["readiness"] = _build_readiness(channels, logical_models, defaults)
    effective = get_settings().model_copy(update=flat)
    payload["stripe_ready"] = is_ready(effective) and (effective.stripe_currency != "auto" or is_ready(effective, language="en"))
    payload["stripe_webhook_url"] = f"{effective.public_base_url.rstrip('/')}/api/billing/stripe/webhook"
    return AdminModelSettingsOut.model_validate(payload)


async def get_admin_model_settings(db: AsyncSession) -> AdminModelSettingsOut:
    channels, logical_models, defaults, flat, app_row = await _compose_runtime_state(db)
    admin_channels = await _load_channels(db, runtime=False)
    source = "db" if app_row.config_json else "env"
    return _to_admin_flat_out(flat, source=source, updated_at=app_row.updated_at, channels=admin_channels, logical_models=logical_models, defaults=defaults)


async def get_admin_routing_settings(db: AsyncSession) -> AdminRoutingSettingsOut:
    from app.services.tokenfree_gateway import TOKENFREE_CHANNEL_ID
    from app.services.media_models.reference_limits import reference_limit_settings

    channels, logical_models, defaults, _, app_row = await _compose_runtime_state(db)
    admin_channels = [
        item for item in await _load_channels(db, runtime=False) if item.id == TOKENFREE_CHANNEL_ID
    ]
    errors = model_routing_validation_errors(logical_models, admin_channels or channels, defaults)
    return AdminRoutingSettingsOut(
        system_channels=admin_channels,
        logical_models=logical_models,
        default_models=defaults,
        media_reference_limits=reference_limit_settings((app_row.config_json or {}).get("media_reference_limits")),
        validation_errors=errors,
        updated_at=app_row.updated_at,
    )


async def patch_admin_model_settings(
    db: AsyncSession,
    body: AdminModelSettingsPatch,
) -> tuple[AdminModelSettingsOut, list[str]]:
    from app.services.stripe_payments import validate_settings_patch

    patch = body.model_dump(exclude_unset=True)
    validate_settings_patch(patch)
    app_row = await _get_or_create_app_row(db)
    config = dict(app_row.config_json or {})
    stored_flat = _decrypt_flat_config(config)
    current = _effective_flat(stored_flat if stored_flat else None)
    previous_apple_environment = current["apple_environment"]
    applied: list[str] = []

    for field in SECRET_FIELDS:
        clear_flag = f"clear_{field}"
        if patch.pop(clear_flag, False):
            current[field] = ""
            applied.append(clear_flag)
        value = patch.pop(field, None)
        if value is not None and str(value).strip():
            current[field] = str(value).strip()
            applied.append(field)

    for field, value in patch.items():
        if value is None:
            continue
        current[field] = value
        applied.append(field)

    from app.marketplace.sharing_config import validate_android_association
    (current["marketplace_share_android_package_name"],
     current["marketplace_share_android_sha256_fingerprints"]) = validate_android_association(
        current.get("marketplace_share_android_package_name", ""),
        current.get("marketplace_share_android_sha256_fingerprints", ""))
    if current.get("marketplace_sharing_enabled"):
        from app.marketplace.sharing_config import validate_share_origin
        current["marketplace_share_base_url"] = validate_share_origin(current.get("marketplace_share_base_url", ""))
    apple_changed = any(key.startswith(("apple_", "clear_apple_")) for key in applied)
    if apple_changed:
        from app.marketplace.apple_configuration import validate_material, configuration_status
        from app.marketplace.app_settings import get_app_settings
        validate_material(current["apple_private_key"], current["apple_root_certificates"])
        candidate = get_app_settings().model_copy(update={key: value for key, value in current.items() if key.startswith("apple_")})
        if current["apple_iap_enabled"]:
            status = configuration_status(candidate)
            if not status["configured"]:
                raise ValueError("Apple 新购配置不完整：" + "、".join(status["missing"]))
    turning_app_on = (current.get("marketplace_app_enabled") is True and "marketplace_app_enabled" in applied) or (apple_changed and current["apple_iap_enabled"])
    if turning_app_on:
        from app.marketplace.app_bootstrap import ensure_schema
        try:
            missing = await ensure_schema()
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        if missing:
            raise ValueError("App 数据库结构未准备好：" + "，".join(missing))
    config["flat"] = _encrypt_flat_config(current)
    app_row.config_json = config
    await db.commit()
    await load_model_settings_cache(db)
    if apple_changed:
        if current["apple_environment"] != previous_apple_environment:
            from app.marketplace.apple_runtime import stop_apple_runtime
            await stop_apple_runtime()
        from app.marketplace.app_bootstrap import start_app_services
        await start_app_services()
    if "marketplace_enabled" in applied:
        from app.marketplace.bootstrap import apply_marketplace_switch
        await apply_marketplace_switch()
    channels, logical_models, defaults, flat, app_row = await _compose_runtime_state(db)
    admin_channels = await _load_channels(db, runtime=False)
    return _to_admin_flat_out(flat, source="db", updated_at=app_row.updated_at, channels=admin_channels, logical_models=logical_models, defaults=defaults), applied


def _flat_from_env_settings() -> dict[str, Any]:
    # 读取进程环境 / .env（不经 DB overlay）
    env = Settings()
    return {field: getattr(env, field) for field in model_config_field_names()}


async def import_admin_model_settings_from_env(
    db: AsyncSession,
) -> tuple[AdminModelSettingsOut, list[str], list[str]]:
    """将 .env 中可管理字段写入 app_settings.flat（密钥加密存库）。"""
    app_row = await _get_or_create_app_row(db)
    config = dict(app_row.config_json or {})
    current = _effective_flat(_decrypt_flat_config(config))
    env_flat = _flat_from_env_settings()
    imported: list[str] = []
    skipped_secrets: list[str] = []

    for field in model_config_field_names():
        value = env_flat[field]
        if field in SECRET_FIELDS:
            if not str(value or "").strip():
                skipped_secrets.append(field)
                continue
        current[field] = value
        imported.append(field)

    config["flat"] = _encrypt_flat_config(current)
    app_row.config_json = config
    await db.commit()
    await load_model_settings_cache(db)
    channels, logical_models, defaults, flat, app_row = await _compose_runtime_state(db)
    admin_channels = await _load_channels(db, runtime=False)
    out = _to_admin_flat_out(
        flat,
        source="db",
        updated_at=app_row.updated_at,
        channels=admin_channels,
        logical_models=logical_models,
        defaults=defaults,
    )
    logger.info("imported %d fields from env, skipped %d empty secrets", len(imported), len(skipped_secrets))
    return out, imported, skipped_secrets


async def patch_admin_routing_settings(
    db: AsyncSession,
    body: AdminRoutingSettingsPatch,
) -> tuple[AdminRoutingSettingsOut, list[str]]:
    from app.services.media_models.reference_limits import reference_limit_settings
    limits = {key: value.model_dump() for key, value in body.media_reference_limits.items()} if body.media_reference_limits is not None else None
    reference_limit_settings(limits)
    app_row = await _get_or_create_app_row(db)
    applied: list[str] = []
    existing_rows = {
        row.id: row
        for row in (await db.execute(select(SystemModelChannelRow))).scalars().all()
    }

    if body.system_channels is not None:
        from app.services.tokenfree_gateway import (
            TOKENFREE_BASE_URL,
            TOKENFREE_CHANNEL_ID,
            TOKENFREE_CHANNEL_NAME,
            locked_tokenfree_channel,
        )
        from app.services.media_model_presets import all_preset_channel_models

        incoming = next(
            (item for item in body.system_channels if (item.id or "").strip() == TOKENFREE_CHANNEL_ID),
            body.system_channels[0] if body.system_channels else None,
        )
        prev = existing_rows.get(TOKENFREE_CHANNEL_ID)
        prev_key = _decrypt_secret(prev.api_key_ciphertext or "") if prev else ""
        api_key = prev_key
        if incoming is not None:
            if incoming.clear_api_key:
                api_key = ""
            elif incoming.api_key is not None and str(incoming.api_key).strip():
                api_key = str(incoming.api_key).strip()
        # 渠道 models 固定为站点预设并集，忽略前端自由勾选
        models = all_preset_channel_models()
        locked = locked_tokenfree_channel(api_key=api_key, models=models, enabled=True)
        row = prev or SystemModelChannelRow(id=TOKENFREE_CHANNEL_ID)
        row.name = TOKENFREE_CHANNEL_NAME
        row.base_url = TOKENFREE_BASE_URL
        row.api_key_ciphertext = _encrypt_secret(locked.api_key) if locked.api_key else None
        row.api_format = "openai"
        row.protocol = "auto"
        row.models = locked.models
        row.enabled = True
        row.sort_order = 0
        row.advanced_config = None
        db.add(row)
        for cid, stale in existing_rows.items():
            if cid == TOKENFREE_CHANNEL_ID:
                continue
            stale.enabled = False
            db.add(stale)
        await db.flush()
        applied.append("system_channels")
    else:
        # 仅改默认模型时也把渠道 models 纠到预设并集
        from app.services.tokenfree_gateway import TOKENFREE_CHANNEL_ID
        from app.services.media_model_presets import all_preset_channel_models

        prev = existing_rows.get(TOKENFREE_CHANNEL_ID)
        if prev is not None:
            preset = all_preset_channel_models()
            if list(prev.models or []) != preset:
                prev.models = preset
                db.add(prev)
                await db.flush()
                applied.append("system_channels")

    config = dict(app_row.config_json or {})
    channels_after = await _load_channels(db, runtime=False)
    logical_models = [LogicalModel.model_validate(item) for item in config.get("logical_models") or []]
    defaults = default_models_from_dict(config.get("default_models"))

    if body.logical_models is not None:
        logical_models = body.logical_models
        applied.append("logical_models")

    # 无论前端是否提交逻辑模型，最终都以渠道 models 为准同步（通用 OpenAI 兼容）
    try:
        from app.services.tokenfree_pricing import ensure_official_rates

        await ensure_official_rates()
    except Exception:  # noqa: BLE001
        pass
    synced = synchronize_logical_models_with_channels(logical_models, channels_after)
    bootstrapped, boot_defaults = _bootstrap_logical_from_channels(channels_after)
    alias_ids = {"seedance-2.5", "seedance-2.0", "seedance-2", "seedance-2.0-mini", "seedance-2.0-fast"}
    logical_models = _merge_friendly_alias_models(
        synced,
        [model for model in bootstrapped if model.id in alias_ids],
    )
    if body.system_channels is not None and not (defaults.video_model or "").strip() and boot_defaults.video_model:
        defaults = defaults.model_copy(update={"video_model": boot_defaults.video_model})
    if body.default_models is not None:
        defaults = body.default_models
        applied.append("default_models")
    from app.services.media_model_presets import clamp_default_to_preset

    # 四类默认强制落在预设内（配音仅 qwen-tts-2025-05-22）
    defaults = defaults.model_copy(
        update={
            "text_model": clamp_default_to_preset("text", defaults.text_model),
            "image_model": clamp_default_to_preset("image", defaults.image_model),
            "video_model": clamp_default_to_preset("video", defaults.video_model),
            "audio_model": clamp_default_to_preset("audio", defaults.audio_model),
        }
    )
    image_default = (defaults.image_model or "").strip()
    image_default = _TOKENFREE_IMAGE_IDS.get(image_default.lower(), image_default)
    if image_default:
        defaults = defaults.model_copy(
            update={"image_model": clamp_default_to_preset("image", image_default)}
        )
    defaults = normalize_default_models(defaults, logical_models, channels_after)
    # An empty default means this capability has no enabled route. Keep it empty
    # instead of reintroducing a disabled preset when every model is switched off.

    errors = model_routing_validation_errors(logical_models, channels_after, defaults)
    if errors:
        raise ValueError("；".join(errors[:5]))

    config["logical_models"] = [model.model_dump() for model in logical_models]
    config["default_models"] = default_models_to_dict(defaults)
    if limits is not None:
        config["media_reference_limits"] = reference_limit_settings({**(config.get("media_reference_limits") or {}), **limits})
        applied.append("media_reference_limits")
    if "flat" not in config:
        config["flat"] = _encrypt_flat_config(_settings_to_dict())
    app_row.config_json = config
    await db.commit()
    await load_model_settings_cache(db)
    out = await get_admin_routing_settings(db)
    return out, applied
