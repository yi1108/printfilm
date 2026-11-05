"""App 互动数据；与作品、支付和播放表解耦。"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .models import MarketBase, Record


class AppContentStats(Record, MarketBase):
    __tablename__ = "marketplace_app_content_stats"
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    like_count: Mapped[int] = mapped_column(BigInteger, default=0)
    comment_count: Mapped[int] = mapped_column(BigInteger, default=0)
    favorite_count: Mapped[int] = mapped_column(BigInteger, default=0)
    share_count: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("target_type", "target_id"),)


class AppLike(Record, MarketBase):
    __tablename__ = "marketplace_app_likes"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    publication_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    __table_args__ = (UniqueConstraint("user_id", "target_type", "target_id"),
                      Index("marketplace_app_likes_target", "target_type", "target_id"))


class AppFavorite(Record, MarketBase):
    __tablename__ = "marketplace_app_favorites"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    publication_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    __table_args__ = (UniqueConstraint("user_id", "target_type", "target_id"),
                      Index("marketplace_app_favorites_target", "target_type", "target_id"))


class AppSocialSetting(Record, MarketBase):
    __tablename__ = "marketplace_app_social_settings"
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    comments_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("target_type", "target_id"),)


class AppComment(Record, MarketBase):
    __tablename__ = "marketplace_app_comments"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="visible", index=True)
    deleted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_reason: Mapped[str] = mapped_column(String(300), default="")
    publication_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("marketplace_app_comments_target_time", "target_type", "target_id", "created_at"),)


class AppCommentReport(Record, MarketBase):
    __tablename__ = "marketplace_app_comment_reports"
    comment_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    operator_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("comment_id", "user_id"),)


class AppCommentAction(Record, MarketBase):
    __tablename__ = "marketplace_app_comment_actions"
    comment_id: Mapped[int] = mapped_column(Integer, index=True)
    operator_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(300), default="")

