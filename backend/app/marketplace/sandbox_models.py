"""同部署沙箱专用账本；永不写 users 余额或生产资金来源。"""
from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import MarketBase, Record


class SandboxAccount(Record, MarketBase):
    __tablename__ = "marketplace_sandbox_accounts"
    user_id: Mapped[int] = mapped_column(Integer, unique=True)
    balance_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (CheckConstraint("balance_fen >= 0"),)


class SandboxLot(Record, MarketBase):
    __tablename__ = "marketplace_sandbox_lots"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("marketplace_apple_transactions.id"), unique=True)
    total_units: Mapped[int] = mapped_column(BigInteger)
    available_units: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("available_units >= 0 AND available_units <= total_units"),)


class SandboxAllocation(Record, MarketBase):
    __tablename__ = "marketplace_sandbox_allocations"
    unlock_id: Mapped[int] = mapped_column(ForeignKey("marketplace_coin_unlocks.id"), index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("marketplace_sandbox_lots.id"), index=True)
    units: Mapped[int] = mapped_column(BigInteger)
    returned: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("unlock_id", "lot_id"), CheckConstraint("units > 0"))


class SandboxEntry(Record, MarketBase):
    __tablename__ = "marketplace_sandbox_entries"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    reference: Mapped[str] = mapped_column(String(240), unique=True)
    kind: Mapped[str] = mapped_column(String(32))
    delta_fen: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
