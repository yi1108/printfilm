"""下游独立配置；未配置 OSS 时禁止存储降级。"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarketplaceSettings(BaseSettings):
    """只读取 MARKETPLACE_ 命名空间，保留上游配置语义。"""

    model_config = SettingsConfigDict(
        env_prefix="MARKETPLACE_", extra="ignore",
        env_file=Path(__file__).resolve().parents[2] / ".env", env_file_encoding="utf-8",
    )
    enabled: bool = False
    signed_url_seconds: int = Field(300, ge=30, le=300)
    max_video_bytes: int = Field(500 * 1024 * 1024, gt=0)
    max_document_bytes: int = Field(20 * 1024 * 1024, gt=0)
    max_duration_seconds: int = Field(1800, gt=0)
    part_size: int = Field(8 * 1024 * 1024, ge=1024 * 1024, le=16 * 1024 * 1024)
    watermark_font: str = "C:/Windows/Fonts/msyh.ttc"
    worker_poll_seconds: float = Field(3, ge=1)
    worker_max_attempts: int = Field(3, ge=1, le=5)


@lru_cache
def get_marketplace_settings() -> MarketplaceSettings:
    """缓存独立配置；生产使用环境变量，本地可保持为空。"""
    return MarketplaceSettings()


def is_marketplace_enabled() -> bool:
    """菜单和接口以系统设置里的开关为准；还没保存过时回落到 MARKETPLACE_ENABLED。"""
    from app.config import get_settings
    return bool(get_settings().marketplace_enabled)


def video_duration_limit() -> int:
    """完整视频最长秒数。系统设置保存后以数据库为准，未保存时用 MARKETPLACE_MAX_DURATION_SECONDS。"""
    from app.config import get_settings
    value = int(get_settings().marketplace_max_duration_seconds or 0)
    return value if value > 0 else 1800


def resolve_cjk_font() -> str:
    """优先使用已配置且存在的字体；否则用仓库内置或系统中的中文字体。"""
    configured = Path(get_marketplace_settings().watermark_font)
    if configured.is_file():
        return str(configured)
    from app.services.ffmpeg_compose import _find_cjk_font
    found = _find_cjk_font()
    if not found:
        raise FileNotFoundError("未找到中文字体")
    return found
