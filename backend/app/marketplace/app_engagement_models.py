"""运营初始值、分享事实及维护任务；与支付和内容发布版本独立。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .models import MarketBase, Record


class MetricsBaseline(Record, MarketBase):
    __tablename__ = "marketplace_app_metrics_baselines"
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    like_count: Mapped[int] = mapped_column(BigInteger, default=0)
    favorite_count: Mapped[int] = mapped_column(BigInteger, default=0)
    share_count: Mapped[int] = mapped_column(BigInteger, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    initialized_by: Mapped[str] = mapped_column(String(24), default="automatic")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("target_type", "target_id"),)


class MetricsAudit(Record, MarketBase):
    __tablename__ = "marketplace_app_metrics_audits"
    target_type: Mapped[str] = mapped_column(String(24), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    operator_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(300))
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)


class MetricsInitializationJob(Record, MarketBase):
    __tablename__ = "marketplace_app_metrics_initialization_jobs"
    operator_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    targets: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    initialized: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShareLink(Record, MarketBase):
    __tablename__ = "marketplace_app_share_links"
    public_id: Mapped[str] = mapped_column(String(40), unique=True)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("target_type", "target_id"),)


class ShareSession(Record, MarketBase):
    __tablename__ = "marketplace_app_share_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    actor_key: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action: Mapped[str | None] = mapped_column(String(16), nullable=True)


class ShareCredit(Record, MarketBase):
    __tablename__ = "marketplace_app_share_credits"
    actor_key: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    last_shared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("actor_key", "target_type", "target_id"),)


class ShareEvent(Record, MarketBase):
    __tablename__ = "marketplace_app_share_events"
    session_id: Mapped[int] = mapped_column(Integer, unique=True)
    target_type: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    __table_args__ = (Index("marketplace_app_share_events_target", "target_type", "target_id"),)


class EngagementMaintenance(Record, MarketBase):
    """持久游标让真实统计对账在重启、多 API 进程间继续推进。"""
    __tablename__ = "marketplace_app_engagement_maintenance"
    key: Mapped[str] = mapped_column(String(40), unique=True)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
