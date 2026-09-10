"""Schemas for channel + logical model routing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

LogicalModelCapability = Literal["text", "image", "video", "audio"]
ChannelProtocol = Literal["openai", "ark", "volc_tts", "auto"]
ApiCallFormat = Literal["openai", "ark"]


class LogicalModelBinding(BaseModel):
    """One upstream binding inside a logical model."""

    id: str = ""
    channel_id: str
    upstream_model: str
    enabled: bool = True
    priority: int = 100
    weight: int | None = None


class LogicalModel(BaseModel):
    """User-facing logical model with multi-channel failover."""

    id: str
    name: str = ""
    capability: LogicalModelCapability
    enabled: bool = True
    bindings: list[LogicalModelBinding] = Field(default_factory=list)


class DefaultModels(BaseModel):
    """Site default logical model ids per capability."""

    text_model: str = ""
    image_model: str = ""
    video_model: str = ""
    audio_model: str = ""


class SystemChannelAdvancedConfig(BaseModel):
    """Optional per-channel protocol hints."""

    protocol: ChannelProtocol = "auto"
    text_model: str = ""
    image_model: str = ""
    video_model: str = ""
    create_path: str = ""
    query_path: str = ""


class SystemModelChannel(BaseModel):
    """Physical upstream gateway."""

    id: str
    name: str
    base_url: str = ""
    api_key: str = ""
    has_api_key: bool = False
    api_format: ApiCallFormat = "openai"
    protocol: ChannelProtocol = "auto"
    models: list[str] = Field(default_factory=list)
    enabled: bool = True
    sort_order: int = 0
    advanced_config: SystemChannelAdvancedConfig | None = None
    clear_api_key: bool = False


class SystemModelChannelIn(BaseModel):
    """Write payload for one channel (admin)."""

    id: str
    name: str
    base_url: str = ""
    api_key: str | None = None
    clear_api_key: bool = False
    api_format: ApiCallFormat = "openai"
    protocol: ChannelProtocol = "auto"
    models: list[str] = Field(default_factory=list)
    enabled: bool = True
    sort_order: int = 0
    advanced_config: SystemChannelAdvancedConfig | None = None


class AdminRoutingSettingsOut(BaseModel):
    """Full routing configuration for admin UI."""

    system_channels: list[SystemModelChannel] = Field(default_factory=list)
    logical_models: list[LogicalModel] = Field(default_factory=list)
    default_models: DefaultModels = Field(default_factory=DefaultModels)
    validation_errors: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class AdminRoutingSettingsPatch(BaseModel):
    """Replace/merge routing layers from admin."""

    system_channels: list[SystemModelChannelIn] | None = None
    logical_models: list[LogicalModel] | None = None
    default_models: DefaultModels | None = None


class AdminRoutingSettingsSaveOut(BaseModel):
    ok: bool = True
    settings: AdminRoutingSettingsOut
    applied: list[str] = Field(default_factory=list)


class ResolvedModelRoute(BaseModel):
    """Runtime resolution result."""

    capability: LogicalModelCapability
    logical_model_id: str
    upstream_model: str
    channel_id: str
    channel_name: str
    base_url: str
    api_key: str
    protocol: ChannelProtocol
    api_format: ApiCallFormat

    model_config = {"frozen": True}


def default_models_to_dict(defaults: DefaultModels) -> dict[str, str]:
    return {
        "textModel": defaults.text_model,
        "imageModel": defaults.image_model,
        "videoModel": defaults.video_model,
        "audioModel": defaults.audio_model,
    }


def default_models_from_dict(raw: dict[str, Any] | None) -> DefaultModels:
    data = raw or {}
    return DefaultModels(
        text_model=str(data.get("textModel") or data.get("text_model") or ""),
        image_model=str(data.get("imageModel") or data.get("image_model") or ""),
        video_model=str(data.get("videoModel") or data.get("video_model") or ""),
        audio_model=str(data.get("audioModel") or data.get("audio_model") or ""),
    )
