"""欠费原始原因、逐来源偿还及反向恢复，禁止重复追偿。"""
from sqlalchemy import select

from app.models_wallet import WalletAllocation, WalletDebt, WalletFundingLot, WalletRepayment
from .wallet_base import allocate, lock_account, post
from . import wallet_ranges as ranges


async def create_debt(db, user, units, cause_type, cause_ref, *, origin_lot_id=None):
    """相同消费的欠费原因唯一，重试不得产生第二笔。"""
    if units <= 0:
        return None
    existing = await db.scalar(select(WalletDebt).where(WalletDebt.user_id == user.id,
        WalletDebt.cause_type == cause_type, WalletDebt.cause_ref == str(cause_ref)))
    if existing:
        # 同一来源再次退款，旧原因重新生效；旧偿还已在撤销时返还。
        existing.active = True
        return existing
    item = WalletDebt(user_id=user.id, units=units, cause_type=cause_type,
                      cause_ref=str(cause_ref), origin_lot_id=origin_lot_id, active=True)
    db.add(item)
    await db.flush()
    await post(db, user, 0, "debt_created", f"debt:{item.id}:created",
               details={"units": units, "cause_type": cause_type, "cause_ref": str(cause_ref)})
    return item


async def sweep_debts(db, user_id, environment=None):
    """只使用有效未冻结来源偿还最早欠费，返还和充值均调用。"""
    user = await lock_account(db, user_id, environment)
    debts = list((await db.execute(select(WalletDebt).where(WalletDebt.user_id == user_id,
        WalletDebt.active.is_(True)).order_by(WalletDebt.id))).scalars())
    for debt in debts:
        paid = sum((await db.execute(select(WalletRepayment.units).where(
            WalletRepayment.debt_id == debt.id, WalletRepayment.active.is_(True)))).scalars())
        amount = min(debt.units - paid, int(user.balance_fen or 0))
        if amount <= 0:
            continue
        items = await allocate(db, user, amount, "debt_repayment", str(debt.id))
        for item in items:
            db.add(WalletRepayment(user_id=user_id, debt_id=debt.id, allocation_id=item.id,
                                   units=item.units, active=True))
            await post(db, user, -item.units, "debt_repay", f"repay:{item.id}",
                       details={"debt_id": debt.id, "allocation_id": item.id})
    await db.flush()


async def release_repayment(db, user, repayment, *, reference):
    """取消欠费时返还仍有效代偿来源；无效来源只恢复待撤销区间。"""
    if not repayment.active:
        return 0
    item = await db.get(WalletAllocation, repayment.allocation_id)
    lot = await db.get(WalletFundingLot, item.lot_id)
    repayment.active = False
    item.state = "returned"
    ranges.put(lot, item.ranges)
    released = item.units if lot.active else 0
    await post(db, user, released, "debt_release", reference,
               details={"debt_id": repayment.debt_id, "allocation_id": item.id})
    return released
