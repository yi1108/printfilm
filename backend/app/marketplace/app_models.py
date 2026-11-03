"""App 支付凭证及权益历史；消费余额由统一钱包管理。"""
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .models import MarketBase, Record


class AppleProduct(Record, MarketBase):
    """商品币数映射永久保存，停用商品仍可履约历史交易。"""
    __tablename__ = "marketplace_apple_products"
    product_id: Mapped[str] = mapped_column(String(200), unique=True)
    sku_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sku_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    coins: Mapped[int] = mapped_column(BigInteger)
    price_fen: Mapped[int] = mapped_column(BigInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (CheckConstraint("coins > 0 AND price_fen > 0"),)


class AppleTransaction(Record, MarketBase):
    """一笔经过 Apple 验证的真实付款；环境参与全局唯一性。"""
    __tablename__ = "marketplace_apple_transactions"
    environment: Mapped[str] = mapped_column(String(16), index=True)
    recharge_order_id: Mapped[int | None] = mapped_column(Integer, index=True)
    transaction_id: Mapped[str] = mapped_column(String(100))
    original_transaction_id: Mapped[str] = mapped_column(String(100), default="")
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[str] = mapped_column(String(200))
    app_account_token: Mapped[str] = mapped_column(String(36))
    coins: Mapped[int] = mapped_column(BigInteger)
    amount_fen: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    status: Mapped[str] = mapped_column(String(24), default="paid", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    anomaly: Mapped[str] = mapped_column(Text, default="")
    settlement_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    __table_args__ = (UniqueConstraint("environment", "transaction_id"), CheckConstraint("coins > 0 AND amount_fen >= 0"))


class AppleTransactionRevision(Record, MarketBase):
    """不可变充值财务事件；先收到退款时首个净额为0，后续撤销与退款独立记录。"""
    __tablename__ = "marketplace_apple_transaction_revisions"
    transaction_id: Mapped[int] = mapped_column(ForeignKey("marketplace_apple_transactions.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    delta_gross_fen: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("transaction_id", "revision"), CheckConstraint("revision >= 0"))


class CoinWallet(Record, MarketBase):
    """历史独立钱包，只供迁移核对；运行时不得写入。"""
    __tablename__ = "marketplace_coin_wallets"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    environment: Mapped[str] = mapped_column(String(16))
    balance_coins: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("user_id", "environment"), CheckConstraint("balance_coins >= 0"))


class CoinLot(Record, MarketBase):
    """历史币来源与精确成本区间，迁移后保留只读。"""
    __tablename__ = "marketplace_coin_lots"
    wallet_id: Mapped[int] = mapped_column(ForeignKey("marketplace_coin_wallets.id"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("marketplace_apple_transactions.id"), unique=True)
    total_coins: Mapped[int] = mapped_column(BigInteger)
    remaining_coins: Mapped[int] = mapped_column(BigInteger)
    total_amount_fen: Mapped[int] = mapped_column(BigInteger)
    remaining_amount_fen: Mapped[int] = mapped_column(BigInteger)
    available_ranges: Mapped[list[list[int]]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (CheckConstraint("remaining_coins >= 0 AND remaining_coins <= total_coins"), CheckConstraint("remaining_amount_fen >= 0 AND remaining_amount_fen <= total_amount_fen"))


class CoinEntry(Record, MarketBase):
    """历史独立币流水，只读；新消费改用统一资金事件。"""
    __tablename__ = "marketplace_coin_entries"
    wallet_id: Mapped[int] = mapped_column(ForeignKey("marketplace_coin_wallets.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    environment: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(30))
    coins_delta: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    reference: Mapped[str] = mapped_column(String(200), unique=True)


class CoinUnlock(Record, MarketBase):
    """扣币解锁历史；重新购买创建新记录，旧记录只作冲正。"""
    __tablename__ = "marketplace_coin_unlocks"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    environment: Mapped[str] = mapped_column(String(16), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("marketplace_content_orders.id"), unique=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("marketplace_publications.id"), index=True)
    coins: Mapped[int] = mapped_column(BigInteger)
    amount_fen: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="paid", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    __table_args__ = (UniqueConstraint("user_id", "environment", "idempotency_key"),)


class CoinAllocation(Record, MarketBase):
    """每次消费分摊到充值批次，退款时可恢复其他有效来源。"""
    __tablename__ = "marketplace_coin_allocations"
    unlock_id: Mapped[int] = mapped_column(ForeignKey("marketplace_coin_unlocks.id"), index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("marketplace_coin_lots.id"), index=True)
    coins: Mapped[int] = mapped_column(BigInteger)
    amount_fen: Mapped[int] = mapped_column(BigInteger)
    cost_ranges: Mapped[list[list[int]]] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint("unlock_id", "lot_id"),)


class CoinGrant(Record, MarketBase):
    """环境隔离的权益来源历史，不用共享 active 位代表沙箱权益。"""
    __tablename__ = "marketplace_coin_grants"
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    environment: Mapped[str] = mapped_column(String(16))
    publication_id: Mapped[int] = mapped_column(ForeignKey("marketplace_publications.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("marketplace_content_orders.id"))
    unlock_id: Mapped[int] = mapped_column(ForeignKey("marketplace_coin_unlocks.id"), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (Index("marketplace_one_active_coin_grant", "user_id", "environment", "publication_id", unique=True, postgresql_where=text("active = true")),)


class RevenueAdjustment(Record, MarketBase):
    """不可变负向收入，不回写原始收入或历史打款金额。"""
    __tablename__ = "marketplace_app_revenue_adjustments"
    unlock_id: Mapped[int] = mapped_column(ForeignKey("marketplace_coin_unlocks.id"), unique=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    environment: Mapped[str] = mapped_column(String(16))
    gross_fen: Mapped[int] = mapped_column(BigInteger)
    platform_fen: Mapped[int] = mapped_column(BigInteger)
    creator_fen: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(300))


class CreatorAccount(Record, MarketBase):
    """人工打款与退款追回共同持有的结算锁。"""
    __tablename__ = "marketplace_app_creator_accounts"
    owner_id: Mapped[int] = mapped_column(Integer)
    environment: Mapped[str] = mapped_column(String(16))
    debt_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (UniqueConstraint("owner_id", "environment"), CheckConstraint("debt_fen >= 0"))


class AppleSettlement(Record, MarketBase):
    """管理员按苹果财务报告核对，渠道成本由平台承担。"""
    __tablename__ = "marketplace_apple_settlements"
    environment: Mapped[str] = mapped_column(String(16))
    month: Mapped[str] = mapped_column(String(7))
    gross_fen: Mapped[int] = mapped_column(BigInteger)
    channel_fee_fen: Mapped[int] = mapped_column(BigInteger)
    tax_fen: Mapped[int] = mapped_column(BigInteger)
    received_fen: Mapped[int] = mapped_column(BigInteger)
    operator_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)


class AppleSettlementItem(Record, MarketBase):
    """每个财务事件只对账一次，历史报表不随交易后续退款而变化。"""
    __tablename__ = "marketplace_apple_settlement_items"
    settlement_id: Mapped[int] = mapped_column(ForeignKey("marketplace_apple_settlements.id"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("marketplace_apple_transactions.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    gross_fen: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("transaction_id", "revision"),)


class AppPayout(Record, MarketBase):
    """已核对的线下打款存档，不执行自动转账。"""
    __tablename__ = "marketplace_app_payouts"
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    environment: Mapped[str] = mapped_column(String(16))
    amount_fen: Mapped[int] = mapped_column(BigInteger)
    debt_offset_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(24), default="paid")
    operator_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)


class AppPayoutItem(Record, MarketBase):
    """一条创作者收入只能纳入一笔打款。"""
    __tablename__ = "marketplace_app_payout_items"
    payout_id: Mapped[int] = mapped_column(ForeignKey("marketplace_app_payouts.id"), index=True)
    ledger_id: Mapped[int] = mapped_column(ForeignKey("marketplace_revenue_ledger.id"), unique=True)


class AuthorBlock(Record, MarketBase):
    """个人发现屏蔽，不能撤销已购权益。"""
    __tablename__ = "marketplace_app_author_blocks"
    user_id: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("user_id", "author_id"),)
