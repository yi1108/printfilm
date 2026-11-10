"""统一钱包共用锁、环境校验、资金事件及来源分摊。"""
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from app.config import get_settings
from app.models import User, WalletLedger
from app.models_wallet import WalletAccount, WalletAllocation, WalletDebt, WalletEvent, WalletFundingLot, WalletRepayment
from . import wallet_ranges as ranges


class WalletError(ValueError):
    """既适用于 AI 执行前检查，也可由接口转为稳定业务错误。"""
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def enabled():
    """旧环境默认不切换；来源迁移和配置必须明确完成。"""
    return bool(getattr(get_settings(), "unified_wallet_enabled", False))


def environment(value=None):
    """生产、Sandbox 必须使用不同部署和数据库，不能共用余额。"""
    from app.marketplace.app_settings import get_app_settings
    configured = get_app_settings().apple_environment
    if value is not None and value != configured:
        raise WalletError("WALLET_ENVIRONMENT_MISMATCH", "交易环境与当前服务不一致，未计入余额。", 403)
    return configured


async def lock_account(db, user_id, environment=None):
    """唯一资金锁是 users 行；绝不反向访问或锁任务。"""
    if not enabled():
        raise WalletError("UNIFIED_WALLET_UNAVAILABLE", "统一余额尚未开放。", 503)
    env = globals()["environment"](environment)
    user = (await db.execute(select(User).where(User.id == user_id).with_for_update()
                             .execution_options(populate_existing=True))).scalar_one_or_none()
    if user is None:
        raise WalletError("WALLET_ACCOUNT_NOT_FOUND", "账号不存在。", 404)
    try:
        marker = (await db.execute(select(WalletAccount).where(WalletAccount.user_id == user_id))).scalar_one_or_none()
    except ProgrammingError as error:
        if getattr(error.orig, "sqlstate", None) in ("42P01", "42703"):
            raise WalletError("WALLET_SCHEMA_REQUIRED", "统一余额结构尚未准备，请联系管理员完成迁移。", 503) from error
        raise
    if marker is None or marker.environment != env:
        raise WalletError("WALLET_MIGRATION_REQUIRED", "账户资金尚未完成核对，请联系管理员。", 503)
    return user


async def initialize_account(db, user, environment=None):
    """仅创建明确的新零余额账户；历史账户必须经过迁移核对。"""
    if not enabled():
        raise WalletError("UNIFIED_WALLET_UNAVAILABLE", "统一余额尚未开放。", 503)
    env = globals()["environment"](environment)
    existing = await db.scalar(select(WalletAccount).where(WalletAccount.user_id == user.id))
    if existing:
        if existing.environment != env:
            raise WalletError("WALLET_ENVIRONMENT_MISMATCH", "账户属于其他交易环境。", 403)
        return existing
    if int(user.balance_fen or 0) or int(user.frozen_fen or 0):
        raise WalletError("WALLET_MIGRATION_REQUIRED", "已有余额必须先核对资金来源。", 503)
    marker = WalletAccount(user_id=user.id, environment=env)
    db.add(marker)
    await db.flush()
    return marker


async def post(db, user, delta, kind, reference, *, frozen_delta=0, details=None):
    """余额、冻结、不可变新事件和兼容原流水在同一事务中更新。"""
    balance = int(user.balance_fen or 0) + delta
    frozen = int(user.frozen_fen or 0) + frozen_delta
    if balance < 0 or frozen < 0:
        raise WalletError("WALLET_ACCOUNT_INCONSISTENT", "资金记录不一致，操作已回滚。", 503)
    user.balance_fen, user.frozen_fen = balance, frozen
    db.add(WalletEvent(user_id=user.id, reference=reference, kind=kind, delta_fen=delta,
                       frozen_delta_fen=frozen_delta, balance_after=balance, frozen_after=frozen,
                       details=details or {}))
    db.add(WalletLedger(user_id=user.id, delta_fen=delta, balance_after=balance, kind=kind,
                        ref_type="unified_wallet", ref_id=reference[:64],
                        note=str((details or {}).get("note") or reference)[:255]))
    await db.flush()


async def allocations(db, user_id, business_type, business_ref):
    """同一用户已持资金锁，后续按编号顺序读取来源。"""
    return list((await db.execute(select(WalletAllocation).where(
        WalletAllocation.user_id == user_id, WalletAllocation.business_type == business_type,
        WalletAllocation.business_ref == str(business_ref)).order_by(WalletAllocation.id))).scalars())


async def get_source(db, user_id, source_type, source_ref, environment=None):
    """来源编号由服务器订单或已验签交易决定。"""
    await lock_account(db, user_id, environment)
    return await db.scalar(select(WalletFundingLot).where(WalletFundingLot.user_id == user_id,
        WalletFundingLot.source_type == source_type, WalletFundingLot.source_ref == str(source_ref))
        .with_for_update().execution_options(populate_existing=True))


async def debt_units(db, user_id):
    """欠费只汇总仍有效原债务，偿还被撤销后自然重新打开。"""
    debts = list((await db.execute(select(WalletDebt).where(WalletDebt.user_id == user_id,
                                                           WalletDebt.active.is_(True)))).scalars())
    total = 0
    for debt in debts:
        repayments = list((await db.execute(select(WalletRepayment).where(
            WalletRepayment.debt_id == debt.id, WalletRepayment.active.is_(True)))).scalars())
        paid = sum(item.units for item in repayments)
        if paid > debt.units:
            raise WalletError("WALLET_ACCOUNT_INCONSISTENT", "欠费偿还记录不一致。", 503)
        total += debt.units - paid
    return total


async def allocate(db, user, amount, business_type, business_ref, *, state="consumed", partial=False):
    """FIFO 来源分摊不依赖客户端余额，纯赠额实收成本为零。"""
    lots = list((await db.execute(select(WalletFundingLot).where(WalletFundingLot.user_id == user.id,
        WalletFundingLot.active.is_(True)).order_by(WalletFundingLot.id).with_for_update()
        .execution_options(populate_existing=True))).scalars())
    available = sum(ranges.units(lot.available_ranges) for lot in lots)
    if available != int(user.balance_fen or 0):
        raise WalletError("WALLET_ACCOUNT_INCONSISTENT", "余额与来源记录不一致，请联系管理员。", 503)
    if amount > available and not partial:
        raise WalletError("WALLET_BALANCE_INSUFFICIENT", "余额不足，请先充值。")
    remaining, result = min(amount, available), []
    for lot in lots:
        count = min(remaining, ranges.units(lot.available_ranges))
        if not count:
            continue
        selected, cash = ranges.take(lot, count)
        item = WalletAllocation(user_id=user.id, lot_id=lot.id, business_type=business_type,
                                business_ref=str(business_ref), units=count, amount_fen=cash,
                                ranges=selected, state=state)
        db.add(item)
        result.append(item)
        remaining -= count
    await db.flush()
    return result


async def ensure_can_spend(db, user):
    """欠费和待结算退款冻结资金均阻止新付费操作。"""
    if await debt_units(db, user.id):
        raise WalletError("WALLET_DEBT_OUTSTANDING", "账户有待补齐欠费，请先充值。")
    invalid = await db.scalar(select(WalletAllocation.id).join(WalletFundingLot,
        WalletFundingLot.id == WalletAllocation.lot_id).where(WalletAllocation.user_id == user.id,
        WalletAllocation.state == "reserved", WalletFundingLot.active.is_(False)).limit(1))
    if invalid:
        raise WalletError("WALLET_REFUND_PENDING", "退款关联任务正在结算，请稍后重试。")
