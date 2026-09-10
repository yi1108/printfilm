"""Pydantic schemas for admin-managed model settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ModelCapabilityReadiness(BaseModel):
    """One generation capability readiness summary."""

    capability: str
    label: str
    model: str
    ready: bool
    message: str


class AdminModelSettingsOut(BaseModel):
    """Admin-readable model settings; secrets are masked."""

    openai_api_key: str = ""
    openai_base_url: str = ""
    model_llm: str = ""
    has_openai_api_key: bool = False

    ark_api_key: str = ""
    ark_base_url: str = ""
    model_image: str = ""
    model_image_45: str = ""
    model_video: str = ""
    model_audio: str = ""
    has_ark_api_key: bool = False

    volc_tts_app_id: str = ""
    volc_tts_access_key: str = ""
    volc_tts_api_key: str = ""
    volc_tts_resource_id: str = ""
    volc_tts_speaker: str = ""
    volc_tts_url: str = ""
    volc_tts_voice_design_url: str = ""
    volc_tts_voice_design_speaker_ids: str = ""
    has_volc_tts_access_key: bool = False
    has_volc_tts_api_key: bool = False

    ark_image_size: str = ""
    ark_video_resolution: str = ""
    ark_video_ratio: str = ""
    seedance_duration_min: int = 4
    seedance_duration_max: int = 30
    ark_video_poll_interval: float = 8.0
    ark_video_poll_timeout: float = 900.0

    pipeline_image_concurrency: int = 3
    pipeline_video_concurrency: int = 10
    pipeline_audio_concurrency: int = 4
    task_runtime_max_concurrency: int = 4
    task_user_max_concurrency: int = 4
    task_poll_max_concurrency: int = 20
    drama_user_video_job_limit: int = 12
    drama_fragment_max_attempts: int = 3

    ark_mock: bool = False

    # Aliyun OSS
    oss_enabled: bool = False
    oss_endpoint: str = ""
    oss_region: str = ""
    oss_bucket: str = ""
    oss_folder: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_public_base: str = ""
    oss_upload_async: bool = True
    oss_upload_queue: str = "oss"
    has_oss_access_key_id: bool = False
    has_oss_access_key_secret: bool = False

    # Volcengine TOS（可选）
    tos_endpoint: str = ""
    tos_bucket: str = ""
    tos_access_key: str = ""
    tos_secret_key: str = ""
    has_tos_access_key: bool = False
    has_tos_secret_key: bool = False
    cdn_base: str = ""

    # Epay 易支付
    epay_api_url: str = ""
    epay_pid: str = ""
    epay_key: str = ""
    epay_notify_url: str = ""
    epay_return_url: str = ""
    has_epay_key: bool = False

    # Token 计费
    billing_enabled: bool = False
    billing_markup: float = 1.5
    billing_estimate_buffer: float = 1.2
    billing_seedance_video0: float = 46.0
    billing_seedance_video1: float = 28.0
    billing_llm_per_m: float = 5.0
    billing_seedream_per_m: float = 8.0
    billing_tts_per_m: float = 2.0
    billing_est_llm_tokens: int = 80_000
    billing_est_seedream_tokens: int = 45_000
    billing_est_tts_tokens: int = 5_000
    billing_est_seedance_tokens_per_sec: int = 32_000
    billing_signup_grant_fen: int = 500
    quota_enabled: bool = False
    new_user_quota: int = 5

    # 额度告警
    billing_user_alert_enabled: bool = True
    billing_user_alert_interval_fen: int = 1000
    billing_admin_cost_alert_enabled: bool = False
    billing_admin_cost_alert_threshold_fen: int = 0
    billing_admin_cost_alert_emails: str = ""
    billing_admin_cost_alert_period: str = "monthly"
    billing_admin_cost_alert_last_period_key: str = ""
    billing_admin_cost_alert_last_level: int = 0

    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    has_smtp_password: bool = False

    # 火山管控面用量查询（GetInferenceUsage，后台配置，不入 .env）
    volc_access_key_id: str = ""
    volc_secret_access_key: str = ""
    volc_ark_region: str = "cn-beijing"
    volc_ark_usage_enabled: bool = True
    has_volc_access_key_id: bool = False
    has_volc_secret_access_key: bool = False

    # 站点与工具
    public_base_url: str = ""
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    source: str = "env"
    updated_at: datetime | None = None
    readiness: list[ModelCapabilityReadiness] = Field(default_factory=list)


class AdminModelSettingsPatch(BaseModel):
    """Partial update for admin model settings."""

    openai_api_key: str | None = None
    openai_base_url: str | None = None
    model_llm: str | None = None
    clear_openai_api_key: bool = False

    ark_api_key: str | None = None
    ark_base_url: str | None = None
    model_image: str | None = None
    model_image_45: str | None = None
    model_video: str | None = None
    model_audio: str | None = None
    clear_ark_api_key: bool = False

    volc_tts_app_id: str | None = None
    volc_tts_access_key: str | None = None
    volc_tts_api_key: str | None = None
    volc_tts_resource_id: str | None = None
    volc_tts_speaker: str | None = None
    volc_tts_url: str | None = None
    volc_tts_voice_design_url: str | None = None
    volc_tts_voice_design_speaker_ids: str | None = None
    clear_volc_tts_access_key: bool = False
    clear_volc_tts_api_key: bool = False

    ark_image_size: str | None = None
    ark_video_resolution: str | None = None
    ark_video_ratio: str | None = None
    seedance_duration_min: int | None = None
    seedance_duration_max: int | None = None
    ark_video_poll_interval: float | None = None
    ark_video_poll_timeout: float | None = None

    pipeline_image_concurrency: int | None = None
    pipeline_video_concurrency: int | None = None
    pipeline_audio_concurrency: int | None = None
    task_runtime_max_concurrency: int | None = None
    task_user_max_concurrency: int | None = None
    task_poll_max_concurrency: int | None = None
    drama_user_video_job_limit: int | None = None
    drama_fragment_max_attempts: int | None = None

    ark_mock: bool | None = None

    oss_enabled: bool | None = None
    oss_endpoint: str | None = None
    oss_region: str | None = None
    oss_bucket: str | None = None
    oss_folder: str | None = None
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    oss_public_base: str | None = None
    oss_upload_async: bool | None = None
    oss_upload_queue: str | None = None
    clear_oss_access_key_id: bool = False
    clear_oss_access_key_secret: bool = False

    tos_endpoint: str | None = None
    tos_bucket: str | None = None
    tos_access_key: str | None = None
    tos_secret_key: str | None = None
    clear_tos_access_key: bool = False
    clear_tos_secret_key: bool = False
    cdn_base: str | None = None

    epay_api_url: str | None = None
    epay_pid: str | None = None
    epay_key: str | None = None
    epay_notify_url: str | None = None
    epay_return_url: str | None = None
    clear_epay_key: bool = False

    billing_enabled: bool | None = None
    billing_markup: float | None = None
    billing_estimate_buffer: float | None = None
    billing_seedance_video0: float | None = None
    billing_seedance_video1: float | None = None
    billing_llm_per_m: float | None = None
    billing_seedream_per_m: float | None = None
    billing_tts_per_m: float | None = None
    billing_est_llm_tokens: int | None = None
    billing_est_seedream_tokens: int | None = None
    billing_est_tts_tokens: int | None = None
    billing_est_seedance_tokens_per_sec: int | None = None
    billing_signup_grant_fen: int | None = None
    quota_enabled: bool | None = None
    new_user_quota: int | None = None

    billing_user_alert_enabled: bool | None = None
    billing_user_alert_interval_fen: int | None = None
    billing_admin_cost_alert_enabled: bool | None = None
    billing_admin_cost_alert_threshold_fen: int | None = None
    billing_admin_cost_alert_emails: str | None = None
    billing_admin_cost_alert_period: str | None = None

    smtp_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool | None = None
    clear_smtp_password: bool = False

    volc_access_key_id: str | None = None
    volc_secret_access_key: str | None = None
    volc_ark_region: str | None = None
    volc_ark_usage_enabled: bool | None = None
    clear_volc_access_key_id: bool = False
    clear_volc_secret_access_key: bool = False

    public_base_url: str | None = None
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None


class AdminModelSettingsSaveOut(BaseModel):
    """Save response with refreshed admin view."""

    ok: bool = True
    settings: AdminModelSettingsOut
    applied_fields: list[str] = Field(default_factory=list)


class AdminModelSettingsImportEnvOut(BaseModel):
    """Import-from-env response."""

    ok: bool = True
    settings: AdminModelSettingsOut
    imported_fields: list[str] = Field(default_factory=list)
    skipped_secret_fields: list[str] = Field(default_factory=list)


def model_config_field_names() -> tuple[str, ...]:
    """Return Settings fields managed via admin model config."""
    return (
        "openai_api_key",
        "openai_base_url",
        "model_llm",
        "ark_api_key",
        "ark_base_url",
        "model_image",
        "model_image_45",
        "model_video",
        "model_audio",
        "volc_tts_app_id",
        "volc_tts_access_key",
        "volc_tts_api_key",
        "volc_tts_resource_id",
        "volc_tts_speaker",
        "volc_tts_url",
        "volc_tts_voice_design_url",
        "volc_tts_voice_design_speaker_ids",
        "ark_image_size",
        "ark_video_resolution",
        "ark_video_ratio",
        "seedance_duration_min",
        "seedance_duration_max",
        "ark_video_poll_interval",
        "ark_video_poll_timeout",
        "pipeline_image_concurrency",
        "pipeline_video_concurrency",
        "pipeline_audio_concurrency",
        "task_runtime_max_concurrency",
        "task_user_max_concurrency",
        "task_poll_max_concurrency",
        "drama_user_video_job_limit",
        "drama_fragment_max_attempts",
        "ark_mock",
        "oss_enabled",
        "oss_endpoint",
        "oss_region",
        "oss_bucket",
        "oss_folder",
        "oss_access_key_id",
        "oss_access_key_secret",
        "oss_public_base",
        "oss_upload_async",
        "oss_upload_queue",
        "tos_endpoint",
        "tos_bucket",
        "tos_access_key",
        "tos_secret_key",
        "cdn_base",
        "epay_api_url",
        "epay_pid",
        "epay_key",
        "epay_notify_url",
        "epay_return_url",
        "billing_enabled",
        "billing_markup",
        "billing_estimate_buffer",
        "billing_seedance_video0",
        "billing_seedance_video1",
        "billing_llm_per_m",
        "billing_seedream_per_m",
        "billing_tts_per_m",
        "billing_est_llm_tokens",
        "billing_est_seedream_tokens",
        "billing_est_tts_tokens",
        "billing_est_seedance_tokens_per_sec",
        "billing_signup_grant_fen",
        "quota_enabled",
        "new_user_quota",
        "billing_user_alert_enabled",
        "billing_user_alert_interval_fen",
        "billing_admin_cost_alert_enabled",
        "billing_admin_cost_alert_threshold_fen",
        "billing_admin_cost_alert_emails",
        "billing_admin_cost_alert_period",
        "billing_admin_cost_alert_last_period_key",
        "billing_admin_cost_alert_last_level",
        "smtp_enabled",
        "smtp_host",
        "smtp_port",
        "smtp_user",
        "smtp_password",
        "smtp_from",
        "smtp_use_tls",
        "volc_access_key_id",
        "volc_secret_access_key",
        "volc_ark_region",
        "volc_ark_usage_enabled",
        "public_base_url",
        "ffmpeg_path",
        "ffprobe_path",
    )


SECRET_FIELD_FLAGS: dict[str, str] = {
    "openai_api_key": "has_openai_api_key",
    "ark_api_key": "has_ark_api_key",
    "volc_tts_access_key": "has_volc_tts_access_key",
    "volc_tts_api_key": "has_volc_tts_api_key",
    "oss_access_key_id": "has_oss_access_key_id",
    "oss_access_key_secret": "has_oss_access_key_secret",
    "tos_access_key": "has_tos_access_key",
    "tos_secret_key": "has_tos_secret_key",
    "epay_key": "has_epay_key",
    "volc_access_key_id": "has_volc_access_key_id",
    "volc_secret_access_key": "has_volc_secret_access_key",
    "smtp_password": "has_smtp_password",
}

SECRET_FIELDS = tuple(SECRET_FIELD_FLAGS.keys())
