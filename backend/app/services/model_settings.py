"""Load, cache, and persist model routing + flat runtime settings."""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import delete, select
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


# 解密敏感字段
def _decrypt_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    token = value[len(ENCRYPTED_PREFIX) :]
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


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
    _overlay = {
        field: flat[field]
        for field in model_config_field_names()
        if field in flat and flat[field] is not None and flat[field] != ""
    }


# 刷新路由快照
def _refresh_routing_snapshot(
    channels: list[SystemModelChannel],
    logical_models: list[LogicalModel],
    default_models: DefaultModels,
) -> None:
    global _routing_snapshot
    _routing_snapshot = RoutingSnapshot(
        channels=channels,
        logical_models=logical_models,
        default_models=default_models,
    )


# 从 env 构建默认渠道
def _bootstrap_channels_from_env(settings: Settings | None = None) -> list[SystemModelChannel]:
    src = settings or get_settings()
    channels: list[SystemModelChannel] = []
    if (src.openai_api_key or src.openai_base_url) and src.model_llm:
        channels.append(
            SystemModelChannel(
                id="openai-default",
                name="OpenAI 兼容 LLM",
                base_url=(src.openai_base_url or "https://api.openai.com/v1").rstrip("/"),
                api_key=src.openai_api_key or "",
                has_api_key=bool(src.openai_api_key),
                api_format="openai",
                protocol="openai",
                models=[src.model_llm],
                enabled=True,
                sort_order=0,
            )
        )
    ark_models = [m for m in [src.model_image, src.model_image_45, src.model_video] if m]
    if src.ark_api_key and ark_models:
        channels.append(
            SystemModelChannel(
                id="ark-default",
                name="火山方舟 ARK",
                base_url=(src.ark_base_url or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/"),
                api_key=src.ark_api_key or "",
                has_api_key=bool(src.ark_api_key),
                api_format="ark",
                protocol="ark",
                models=list(dict.fromkeys(ark_models)),
                enabled=True,
                sort_order=1,
            )
        )
    tts_models = [m for m in [src.model_audio, src.volc_tts_speaker] if m]
    if (src.volc_tts_api_key or (src.volc_tts_app_id and src.volc_tts_access_key)) and tts_models:
        channels.append(
            SystemModelChannel(
                id="volc-tts-default",
                name="豆包语音 TTS",
                base_url=(src.volc_tts_url or "").rstrip("/"),
                api_key=src.volc_tts_api_key or src.volc_tts_access_key or "",
                has_api_key=bool(src.volc_tts_api_key or src.volc_tts_access_key),
                api_format="openai",
                protocol="volc_tts",
                models=list(dict.fromkeys(tts_models)),
                enabled=True,
                sort_order=2,
            )
        )
    return channels


# 从 env 构建默认逻辑模型与默认模型 ID
def _bootstrap_logical_from_channels(channels: list[SystemModelChannel]) -> tuple[list[LogicalModel], DefaultModels]:
    logical_models = synchronize_logical_models_with_channels([], channels)
    settings = get_settings()
    alias_models: list[LogicalModel] = []

    def _bindings_for_upstream(upstream: str) -> list:
        from app.schemas_routing import LogicalModelBinding

        result = []
        for model in logical_models:
            for binding in model.bindings:
                if binding.upstream_model == upstream:
                    result.append(binding.model_copy())
        return result

    if settings.model_image:
        bindings = _bindings_for_upstream(settings.model_image)
        if bindings:
            alias_models.append(
                LogicalModel(
                    id="seedream-5.0",
                    name="Seedream 5.0",
                    capability="image",
                    enabled=True,
                    bindings=bindings,
                )
            )
    if settings.model_image_45:
        bindings = _bindings_for_upstream(settings.model_image_45)
        if bindings:
            alias_models.append(
                LogicalModel(
                    id="seedream-4.5",
                    name="Seedream 4.5",
                    capability="image",
                    enabled=True,
                    bindings=bindings,
                )
            )
    if settings.model_video:
        bindings = _bindings_for_upstream(settings.model_video)
        if bindings:
            alias_models.append(
                LogicalModel(
                    id="seedance-2.5",
                    name="Seedance 2.5",
                    capability="video",
                    enabled=True,
                    bindings=bindings,
                )
            )
    merged = synchronize_logical_models_with_channels(logical_models + alias_models, channels)
    defaults = DefaultModels(
        text_model=settings.model_llm,
        image_model="seedream-5.0" if settings.model_image else "",
        video_model="seedance-2.5" if settings.model_video else "",
        audio_model=settings.model_audio or settings.volc_tts_speaker,
    )
    return merged, normalize_default_models(defaults, merged, channels)


# ORM 行转领域模型（admin 视图，密钥打码）
def _channel_row_to_admin(row: SystemModelChannelRow) -> SystemModelChannel:
    api_key = _decrypt_secret(row.api_key_ciphertext or "")
    return SystemModelChannel(
        id=row.id,
        name=row.name,
        base_url=row.base_url or "",
        api_key="",
        has_api_key=bool(api_key),
        api_format=row.api_format or "openai",
        protocol=row.protocol or "auto",
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
    row = AppSettings(id="default", config_json={"flat": _settings_to_dict()})
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
        return existing
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
    app_row.config_json = {
        "flat": _settings_to_dict(),
        "logical_models": [model.model_dump() for model in logical_models],
        "default_models": default_models_to_dict(defaults),
    }
    await db.commit()
    return rows


def _settings_to_dict(settings: Settings | None = None) -> dict[str, Any]:
    src = settings or get_settings()
    return {field: getattr(src, field) for field in model_config_field_names()}


def _decrypt_flat_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict((raw or {}).get("flat") or raw or {})
    for field in SECRET_FIELDS:
        if field in data and data[field]:
            try:
                data[field] = _decrypt_secret(str(data[field]))
            except Exception:  # noqa: BLE001
                logger.warning("failed to decrypt flat settings field %s", field)
                data[field] = ""
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
    default_models = normalize_default_models(default_models, logical_models, channels)
    flat = _effective_flat(_decrypt_flat_config(config))
    if default_models.text_model:
        flat["model_llm"] = default_models.text_model
    return channels, logical_models, default_models, flat, app_row


async def load_model_settings_cache(db: AsyncSession) -> None:
    """加载路由快照；若与渠道不同步则回写 healed 配置，避免默认仍钉死旧模型名。"""
    channels, logical_models, default_models, flat, app_row = await _compose_runtime_state(db)
    config = dict(app_row.config_json or {})
    old_ids = {(item or {}).get("id") for item in (config.get("logical_models") or [])}
    new_ids = {model.id for model in logical_models}
    old_defaults = default_models_from_dict(config.get("default_models"))
    if old_ids != new_ids or old_defaults != default_models:
        config["logical_models"] = [model.model_dump() for model in logical_models]
        config["default_models"] = default_models_to_dict(default_models)
        flat_cfg = dict(config.get("flat") or {})
        if default_models.text_model:
            flat_cfg["model_llm"] = default_models.text_model
            config["flat"] = flat_cfg
        app_row.config_json = config
        await db.commit()
    _refresh_routing_snapshot(channels, logical_models, default_models)
    _refresh_overlay({"flat": flat})
    reload_settings()


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
        cap = capability  # type: LogicalModelCapability
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
    payload = {field: flat.get(field) for field in model_config_field_names()}
    for field, flag in SECRET_FIELD_FLAGS.items():
        payload[field] = ""
        payload[flag] = bool(str(flat.get(field) or "").strip())
    payload["source"] = source
    payload["updated_at"] = updated_at
    payload["readiness"] = _build_readiness(channels, logical_models, defaults)
    return AdminModelSettingsOut.model_validate(payload)


async def get_admin_model_settings(db: AsyncSession) -> AdminModelSettingsOut:
    channels, logical_models, defaults, flat, app_row = await _compose_runtime_state(db)
    admin_channels = await _load_channels(db, runtime=False)
    source = "db" if app_row.config_json else "env"
    return _to_admin_flat_out(flat, source=source, updated_at=app_row.updated_at, channels=admin_channels, logical_models=logical_models, defaults=defaults)


async def get_admin_routing_settings(db: AsyncSession) -> AdminRoutingSettingsOut:
    channels, logical_models, defaults, _, app_row = await _compose_runtime_state(db)
    admin_channels = await _load_channels(db, runtime=False)
    errors = model_routing_validation_errors(logical_models, admin_channels, defaults)
    return AdminRoutingSettingsOut(
        system_channels=admin_channels,
        logical_models=logical_models,
        default_models=defaults,
        validation_errors=errors,
        updated_at=app_row.updated_at,
    )


async def patch_admin_model_settings(
    db: AsyncSession,
    body: AdminModelSettingsPatch,
) -> tuple[AdminModelSettingsOut, list[str]]:
    app_row = await _get_or_create_app_row(db)
    config = dict(app_row.config_json or {})
    stored_flat = _decrypt_flat_config(config)
    current = _effective_flat(stored_flat if stored_flat else None)
    patch = body.model_dump(exclude_unset=True)
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

    config["flat"] = _encrypt_flat_config(current)
    app_row.config_json = config
    await db.commit()
    await load_model_settings_cache(db)
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
    app_row = await _get_or_create_app_row(db)
    applied: list[str] = []
    existing_rows = {
        row.id: row
        for row in (await db.execute(select(SystemModelChannelRow))).scalars().all()
    }

    if body.system_channels is not None:
        seen_ids: set[str] = set()
        for index, channel_in in enumerate(body.system_channels):
            channel_id = (channel_in.id or "").strip() or f"channel-{uuid.uuid4().hex[:8]}"
            seen_ids.add(channel_id)
            prev = existing_rows.get(channel_id)
            prev_key = _decrypt_secret(prev.api_key_ciphertext or "") if prev else ""
            api_key = prev_key
            if channel_in.clear_api_key:
                api_key = ""
            elif channel_in.api_key is not None and str(channel_in.api_key).strip():
                api_key = str(channel_in.api_key).strip()
            row = existing_rows.get(channel_id) or SystemModelChannelRow(id=channel_id)
            row.name = channel_in.name.strip() or channel_id
            row.base_url = (channel_in.base_url or "").strip()
            row.api_key_ciphertext = _encrypt_secret(api_key) if api_key else None
            row.api_format = channel_in.api_format
            row.protocol = channel_in.protocol
            row.models = [str(item).strip() for item in channel_in.models if str(item).strip()]
            row.enabled = bool(channel_in.enabled)
            row.sort_order = channel_in.sort_order if channel_in.sort_order else index
            row.advanced_config = channel_in.advanced_config.model_dump() if channel_in.advanced_config else None
            db.add(row)
        stale_ids = [cid for cid in existing_rows if cid not in seen_ids]
        if stale_ids:
            await db.execute(delete(SystemModelChannelRow).where(SystemModelChannelRow.id.in_(stale_ids)))
        applied.append("system_channels")

    config = dict(app_row.config_json or {})
    channels_after = await _load_channels(db, runtime=False)
    logical_models = [LogicalModel.model_validate(item) for item in config.get("logical_models") or []]

    if body.logical_models is not None:
        logical_models = body.logical_models
        applied.append("logical_models")
    elif body.system_channels is not None:
        bootstrapped, _ = _bootstrap_logical_from_channels(channels_after)
        alias_ids = {"seedream-5.0", "seedream-4.5", "seedance-2.5"}
        extras = [model for model in bootstrapped if model.id in alias_ids]
        logical_models = logical_models + extras

    # 无论前端是否提交逻辑模型，最终都以渠道 models 为准同步（通用 OpenAI 兼容）
    logical_models = synchronize_logical_models_with_channels(logical_models, channels_after)

    defaults = default_models_from_dict(config.get("default_models"))
    if body.default_models is not None:
        defaults = body.default_models
        applied.append("default_models")
    defaults = normalize_default_models(defaults, logical_models, channels_after)

    errors = model_routing_validation_errors(logical_models, channels_after, defaults)
    if errors:
        raise ValueError("；".join(errors[:5]))

    config["logical_models"] = [model.model_dump() for model in logical_models]
    config["default_models"] = default_models_to_dict(defaults)
    if "flat" not in config:
        config["flat"] = _encrypt_flat_config(_settings_to_dict())
    app_row.config_json = config
    await db.commit()
    await load_model_settings_cache(db)
    out = await get_admin_routing_settings(db)
    return out, applied
