"""Apple 身份映射、购买意向和可靠通知收件箱。"""
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import MarketBase, Record


class AppleAccountToken(Record, MarketBase):
    """稳定 UUID 仅映射 PrintFilm 账号；不可认领其他账号的交易。"""
    __tablename__ = "marketplace_apple_account_tokens"
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    token: Mapped[str] = mapped_column(String(36), unique=True)
    consumption_data_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplePurchaseIntent(Record, MarketBase):
    """意向不代表付款；过期意向不能成为拒绝真实已付款履约的理由。"""
    __tablename__ = "marketplace_apple_purchase_intents"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    environment: Mapped[str] = mapped_column(String(16))
    product_id: Mapped[str] = mapped_column(String(200))
    recharge_order_id: Mapped[int | None] = mapped_column(Integer, index=True)
    fulfilled_transaction_id: Mapped[str | None] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "environment", "idempotency_key"),)


class AppleNotification(Record, MarketBase):
    """验签后持久化再应答 Apple；租约允许进程重启及多实例恢复。"""
    __tablename__ = "marketplace_apple_notifications"
    environment: Mapped[str] = mapped_column(String(16), index=True)
    notification_uuid: Mapped[str] = mapped_column(String(36))
    notification_type: Mapped[str] = mapped_column(String(80))
    transaction_id: Mapped[str] = mapped_column(String(100), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("environment", "notification_uuid"),)


class AppleNotificationCursor(Record, MarketBase):
    """通知补偿游标持久化，停机后继续查询而不是只看最近几分钟。"""
    __tablename__ = "marketplace_apple_notification_cursors"
    environment: Mapped[str] = mapped_column(String(16), unique=True)
    last_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pagination_token: Mapped[str | None] = mapped_column(String(4000))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(Text, default="")
