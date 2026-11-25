"""Google Play payment records; no client purchase claim is trusted."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import MarketBase, Record


class GoogleSettings(Record, MarketBase):
    __tablename__ = "marketplace_google_settings"
    key: Mapped[str] = mapped_column(String(20), unique=True, default="billing")
    version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    credentials: Mapped[str] = mapped_column(Text, default="")


class GoogleAudit(Record, MarketBase):
    __tablename__ = "marketplace_google_audit"
    operator_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict] = mapped_column(JSON)


class GoogleAccount(Record, MarketBase):
    __tablename__ = "marketplace_google_accounts"
    user_id: Mapped[int] = mapped_column(Integer)
    package_name: Mapped[str] = mapped_column(String(200))
    account_id: Mapped[str] = mapped_column(String(64), unique=True)
    __table_args__ = (UniqueConstraint("user_id", "package_name"),)


class GoogleIntent(Record, MarketBase):
    __tablename__ = "marketplace_google_intents"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    package_name: Mapped[str] = mapped_column(String(200))
    sku_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[str] = mapped_column(String(200))
    account_id: Mapped[str] = mapped_column(String(64))
    profile_id: Mapped[str] = mapped_column(String(64), unique=True)
    intent_key: Mapped[str] = mapped_column(String(64), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSON)
    order_id: Mapped[int] = mapped_column(Integer, unique=True)
    fulfilled_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)


class GooglePurchase(Record, MarketBase):
    __tablename__ = "marketplace_google_purchases"
    package_name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64))
    token_secret: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    intent_id: Mapped[int] = mapped_column(Integer, unique=True)
    order_id: Mapped[int] = mapped_column(Integer, unique=True)
    google_order_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    product_id: Mapped[str] = mapped_column(String(200))
    environment: Mapped[str] = mapped_column(String(16))
    credit_fen: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    was_credited: Mapped[bool] = mapped_column(Boolean, default=False)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Publisher product purchases API has no authoritative price. Never invent it.
    currency: Mapped[str | None] = mapped_column(String(3))
    amount_micros: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("package_name", "token_hash"),)


class GoogleWork(Record, MarketBase):
    """Durable retry queue, including pending purchase and post-commit consume."""
    __tablename__ = "marketplace_google_work"
    package_name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64))
    token_secret: Mapped[str] = mapped_column(Text)
    product_id: Mapped[str] = mapped_column(String(200))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_key: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(100), default="")
    __table_args__ = (UniqueConstraint("package_name", "token_hash"),)


class GoogleNotification(Record, MarketBase):
    __tablename__ = "marketplace_google_notifications"
    message_id: Mapped[str] = mapped_column(String(200), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), default="")
    notification_type: Mapped[str] = mapped_column(String(40))
    # Voided notification is a hint; only Publisher's voided API confirms refund.
    status: Mapped[str] = mapped_column(String(24), default="queued")


class GoogleCursor(Record, MarketBase):
    __tablename__ = "marketplace_google_cursors"
    key: Mapped[str] = mapped_column(String(200), unique=True)
    start_ms: Mapped[str] = mapped_column(String(20))
    end_ms: Mapped[str] = mapped_column(String(20))
    page_token: Mapped[str] = mapped_column(Text, default="")
    lease_key: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GoogleVoid(Record, MarketBase):
    """Permanent tombstone; a late client verification must never resurrect it."""
    __tablename__ = "marketplace_google_voids"
    package_name: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("package_name", "token_hash"),)
