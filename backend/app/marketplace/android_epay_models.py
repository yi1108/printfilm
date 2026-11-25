"""Android cashier sessions and gateway receipt uniqueness, independent of balances."""
from datetime import datetime
from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import MarketBase, Record

class AndroidEpayCheckout(Record, MarketBase):
    __tablename__ = "marketplace_android_epay_checkouts"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"), UniqueConstraint("order_id"))
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    package_name: Mapped[str] = mapped_column(String(200))
    merchant_pid: Mapped[str] = mapped_column(String(100))
    merchant_namespace: Mapped[str] = mapped_column(String(64))
    signing_secret: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), default="creating")
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str] = mapped_column(String(80), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class EpayReceipt(Record, MarketBase):
    __tablename__ = "marketplace_epay_receipts"
    __table_args__ = (UniqueConstraint("merchant_namespace", "trade_no"), UniqueConstraint("order_id"))
    merchant_namespace: Mapped[str] = mapped_column(String(64))
    merchant_pid: Mapped[str] = mapped_column(String(100))
    trade_no: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[int] = mapped_column(Integer)
    payment_client: Mapped[str] = mapped_column(String(32))
    pay_type: Mapped[str] = mapped_column(String(16))
    amount_fen: Mapped[int] = mapped_column(Integer)
