"""App 与 Apple 支付渠道配置；统一余额复用原钱包，停新购不停止已付款履约。"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarketplaceAppSettings(BaseSettings):
    """Apple 等渠道仍使用 MARKETPLACE_ 前缀。App 总开关只认 MARKETPLACE_APP_ENABLED，避免和市场总开关 MARKETPLACE_ENABLED 重名。没有 .env 文件时读取进程环境变量，缺文件不影响启动。"""
    model_config = SettingsConfigDict(
        env_prefix="MARKETPLACE_", extra="ignore",
        env_file=Path(__file__).resolve().parents[2] / ".env", env_file_encoding="utf-8",
    )
    enabled: bool = Field(False, validation_alias=AliasChoices("MARKETPLACE_APP_ENABLED", "enabled"))
    social_enabled: bool = True
    comments_enabled: bool = True
    apple_iap_enabled: bool = False
    apple_environment: Literal["Production", "Sandbox"] = "Production"
    apple_bundle_id: str = ""
    apple_app_id: int | None = Field(None, gt=0)
    apple_issuer_id: str = ""
    apple_key_id: str = ""
    apple_private_key_path: str = ""
    apple_private_key: str = ""
    apple_root_certificates: str = ""
    # 多个 Apple Root CA DER 文件使用分号分隔；不得使用客户端提交的证书。
    apple_root_cert_paths: str = ""
    apple_online_checks: bool = True
    apple_notification_poll_seconds: float = Field(3, ge=1, le=60)
    apple_reconciliation_seconds: int = Field(300, ge=30, le=3600)
    playback_idle_seconds: int = Field(1800, ge=60, le=1800)
    playback_max_seconds: int = Field(7200, ge=1800, le=7200)

    @field_validator("apple_app_id", mode="before")
    @classmethod
    def empty_apple_app_id(cls, value):
        """示例配置保留空 App ID 时仍允许启动原项目。"""
        return None if value == "" else value

    def certificate_paths(self) -> list[Path]:
        """解析管理员配置的服务器证书文件，不访问网络下载证书。"""
        return [Path(part.strip()) for part in self.apple_root_cert_paths.split(";") if part.strip()]


@lru_cache
def get_app_settings() -> MarketplaceAppSettings:
    """配置默认关闭；生产密钥只存在服务端环境或私密文件中。"""
    from app.services.model_settings import get_overlay_dict
    config = MarketplaceAppSettings()
    overlay = {key: value for key, value in get_overlay_dict().items()
               if key.startswith("apple_") and key in MarketplaceAppSettings.model_fields}
    if "apple_app_id" in overlay:
        overlay["apple_app_id"] = overlay["apple_app_id"] or None
    # An explicit cleared database credential must not revive a legacy file.
    if "apple_private_key" in overlay:
        overlay["apple_private_key_path"] = ""
    if "apple_root_certificates" in overlay:
        overlay["apple_root_cert_paths"] = ""
    return config.model_copy(update=overlay)


def is_app_enabled() -> bool:
    """App 视频开关以系统设置里保存的值为准；还没保存过时回落到 MARKETPLACE_APP_ENABLED。"""
    from app.config import get_settings
    return bool(get_settings().marketplace_app_enabled)
