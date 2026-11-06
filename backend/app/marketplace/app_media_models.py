"""App 播放派生物独立任务；不改变 Web 发布文件和原 AI 任务。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import MarketBase, Record


class AppMedia(Record, MarketBase):
    """每个内容版本、用途保存独立的不可变 HLS 结果和可恢复租约。"""
    __tablename__ = "marketplace_app_media"
    __table_args__ = (UniqueConstraint("content_type", "content_id", "version", "variant"),)
    content_type: Mapped[str] = mapped_column(String(24))
    content_id: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    variant: Mapped[str] = mapped_column(String(16))
    asset_id: Mapped[int] = mapped_column(ForeignKey("marketplace_assets.id"))
    source_key: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    manifest_key: Mapped[str | None] = mapped_column(String(512))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(Text, default="")
