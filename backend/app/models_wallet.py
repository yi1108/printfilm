"""统一资金来源、消费、欠费和偿还；余额只保存在 users。"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class WalletBase(DeclarativeBase):
    """独立元数据，禁止随原业务启动自动迁移财务结构。"""


class WalletRecord(WalletBase):
    """财务记录只追加事件；可变状态供可靠处理和查询。"""
    __abstract__ = True
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WalletAccount(WalletRecord):
    """已完成来源核对的账户标记，不保存第二份余额。"""
    __tablename__ = "wallet_accounts"
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(16))
    migration_reference: Mapped[str] = mapped_column(String(200), default="new-account")
    __table_args__ = (CheckConstraint("environment IN ('Production', 'Sandbox')", name="wallet_account_environment"),)


class WalletFundingLot(WalletRecord):
    """每个来源保留额度序号区间，精确追溯实付成本及退款。"""
    __tablename__ = "wallet_funding_lots"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    environment: Mapped[str] = mapped_column(String(16))
    source_type: Mapped[str] = mapped_column(String(32))
    source_ref: Mapped[str] = mapped_column(String(200))
    total_units: Mapped[int] = mapped_column(BigInteger)
    total_amount_fen: Mapped[int] = mapped_column(BigInteger)
    available_ranges: Mapped[list] = mapped_column(JSON, default=list)
    void_ranges: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    settlement_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    __table_args__ = (UniqueConstraint("user_id", "source_type", "source_ref"),
                     CheckConstraint("total_units > 0 AND total_amount_fen >= 0 AND revision >= 0", name="wallet_source_amounts"))


class WalletAllocation(WalletRecord):
    """冻结、实际消费、偿还共用来源分摊；返还原区间而非重估。"""
    __tablename__ = "wallet_allocations"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("wallet_funding_lots.id"), index=True)
    business_type: Mapped[str] = mapped_column(String(32), index=True)
    business_ref: Mapped[str] = mapped_column(String(160), index=True)
    units: Mapped[int] = mapped_column(BigInteger)
    amount_fen: Mapped[int] = mapped_column(BigInteger)
    ranges: Mapped[list] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), default="consumed")
    __table_args__ = (CheckConstraint("units > 0 AND amount_fen >= 0", name="wallet_allocation_amounts"),
                     CheckConstraint("state IN ('consumed', 'reserved', 'returned')", name="wallet_allocation_state"))


class WalletEvent(WalletRecord):
    """不可变资金事件，reference 在同一用户下唯一。"""
    __tablename__ = "wallet_events"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    reference: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(32))
    delta_fen: Mapped[int] = mapped_column(BigInteger)
    frozen_delta_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    frozen_after: Mapped[int] = mapped_column(BigInteger)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("user_id", "reference"),
                     CheckConstraint("balance_after >= 0 AND frozen_after >= 0", name="wallet_event_nonnegative"))


class WalletDebt(WalletRecord):
    """原始欠费不可覆盖；未偿金额由仍有效的偿还关系计算。"""
    __tablename__ = "wallet_debts"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    cause_type: Mapped[str] = mapped_column(String(32))
    cause_ref: Mapped[str] = mapped_column(String(160))
    origin_lot_id: Mapped[int | None] = mapped_column(ForeignKey("wallet_funding_lots.id"), nullable=True, index=True)
    units: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("user_id", "cause_type", "cause_ref"), CheckConstraint("units > 0", name="wallet_debt_positive"))


class WalletRepayment(WalletRecord):
    """资金来源失效时撤销偿还，重新打开原债务而非重复记欠款。"""
    __tablename__ = "wallet_repayments"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    debt_id: Mapped[int] = mapped_column(ForeignKey("wallet_debts.id"), index=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("wallet_allocations.id"), unique=True)
    units: Mapped[int] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("units > 0", name="wallet_repayment_positive"),)


class WalletTaskSettlement(WalletRecord):
    """任务资金生命周期的幂等门闩，核心服务不锁 TaskRun。"""
    __tablename__ = "wallet_task_settlements"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    task_id: Mapped[int] = mapped_column(Integer, unique=True)
    reserved_units: Mapped[int] = mapped_column(BigInteger, default=0)
    charged_units: Mapped[int] = mapped_column(BigInteger, default=0)
    refunded_units: Mapped[int] = mapped_column(BigInteger, default=0)
    state: Mapped[str] = mapped_column(String(16), default="reserved")
    __table_args__ = (CheckConstraint("reserved_units >= 0 AND charged_units >= 0 AND refunded_units >= 0", name="wallet_task_amounts"),)


class WalletTaskNotice(WalletRecord):
    """退款事务发出可靠待办；任务运行时自行按 TaskRun→User 处理。"""
    __tablename__ = "wallet_task_notices"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("wallet_funding_lots.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    __table_args__ = (UniqueConstraint("task_id", "lot_id"),)


class WalletMigrationResolution(WalletRecord):
    """Immutable administrator-approved baseline; historical entries are never deleted."""
    __tablename__ = "wallet_migration_resolutions"
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    backup_reference: Mapped[str] = mapped_column(String(200))
    operator_id: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    snapshot: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
