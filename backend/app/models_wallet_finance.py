"""统一余额资金核对记录，服务端只允许管理员登记有凭据的实收。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .models_wallet import WalletBase, WalletRecord


class WalletFundingReview(WalletRecord):
    """一批来源核对记录；不修改用户余额，只决定收益能否结算。"""
    __tablename__ = "wallet_funding_reviews"
    source_type: Mapped[str] = mapped_column(String(32))
    source_ref: Mapped[str] = mapped_column(String(200))
    gross_fen: Mapped[int] = mapped_column(BigInteger)
    channel_fee_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    tax_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    received_fen: Mapped[int] = mapped_column(BigInteger)
    operator_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("source_type", "source_ref"),)
