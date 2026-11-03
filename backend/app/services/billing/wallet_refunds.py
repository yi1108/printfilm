"""来源退款、退款撤销及偿还反向链；不直接操作视频权益或 TaskRun。"""
from sqlalchemy import select

from app.models_wallet import WalletAllocation, WalletDebt, WalletRepayment, WalletTaskNotice
from .wallet_base import WalletError, get_source, lock_account, post
from .wallet_debts import create_debt, release_repayment, sweep_debts
from . import wallet_ranges as ranges


async def revoke_source(db, user_id, source_type, source_ref, environment=None):
    """先停用来源，再由调用者撤视频权益；最后统一收回不可逆消费。"""
    user = await lock_account(db, user_id, environment)
    lot = await get_source(db, user_id, source_type, source_ref, environment)
    if lot is None:
        raise WalletError("WALLET_SOURCE_UNKNOWN", "未找到该笔充值的资金来源，请先补验单。")
    affected = []
    items = list((await db.execute(select(WalletAllocation).where(WalletAllocation.lot_id == lot.id)
                                  .order_by(WalletAllocation.id))).scalars())
    if not lot.active:
        return {"lot_id": lot.id, "affected_business_refs": [
            {"business_type": item.business_type, "business_ref": item.business_ref}
            for item in items if item.business_type == "video_unlock" and item.state == "consumed"],
            "duplicate": True}
    removed = ranges.units(lot.available_ranges)
    lot.active, lot.revision = False, lot.revision + 1
    lot.settlement_status = "pending"
    lot.void_ranges = ranges.normalize(lot.total_units, lot.void_ranges + lot.available_ranges)
    lot.available_ranges = []
    await post(db, user, -removed, "source_refund", f"source:{lot.id}:refund:{lot.revision}")
    for item in items:
        if item.state not in ("consumed", "reserved"):
            continue
        if item.state == "reserved":
            task_id = int(item.business_ref) if item.business_type == "ai_task" else None
            if task_id:
                existing = await db.scalar(select(WalletTaskNotice).where(
                    WalletTaskNotice.task_id == task_id, WalletTaskNotice.lot_id == lot.id))
                if existing:
                    existing.status = "pending"
                else:
                    db.add(WalletTaskNotice(user_id=user_id, task_id=task_id, lot_id=lot.id, status="pending"))
        elif item.business_type == "debt_repayment":
            repayment = await db.scalar(select(WalletRepayment).where(WalletRepayment.allocation_id == item.id))
            if repayment and repayment.active:
                repayment.active, item.state = False, "returned"
                ranges.put(lot, item.ranges)
                await post(db, user, 0, "repayment_void", f"repay:{item.id}:void:{lot.revision}",
                           details={"debt_id": repayment.debt_id, "units": item.units})
        elif item.business_type == "ai_task":
            await create_debt(db, user, item.units, "source_refund", str(item.id), origin_lot_id=lot.id)
        elif item.business_type == "video_unlock":
            affected.append({"business_type": item.business_type, "business_ref": item.business_ref})
        elif item.business_type == "admin_adjustment":
            # 调减没有可追偿的服务，但原扣减仍有效，退款撤销也不能恢复该额度。
            continue
    await db.flush()
    return {"lot_id": lot.id, "affected_business_refs": affected, "duplicate": False}


async def reverse_source(db, user_id, source_type, source_ref, environment=None):
    """取消原追偿并返还代偿来源；不可把实际已消费额度整批再加回。"""
    user = await lock_account(db, user_id, environment)
    lot = await get_source(db, user_id, source_type, source_ref, environment)
    if lot is None:
        raise WalletError("WALLET_SOURCE_UNKNOWN", "未找到该笔充值的资金来源。")
    if lot.active:
        return {"lot_id": lot.id, "duplicate": True, "restored_units": 0}
    lot.active, lot.revision = True, lot.revision + 1
    lot.settlement_status = "pending"
    restored = ranges.units(lot.void_ranges)
    lot.available_ranges = ranges.normalize(lot.total_units, lot.available_ranges + lot.void_ranges)
    lot.void_ranges = []
    await post(db, user, restored, "refund_reversed", f"source:{lot.id}:reverse:{lot.revision}")
    for debt in (await db.execute(select(WalletDebt).where(WalletDebt.user_id == user_id,
        WalletDebt.origin_lot_id == lot.id, WalletDebt.active.is_(True)).order_by(WalletDebt.id))).scalars():
        debt.active = False
        for repayment in (await db.execute(select(WalletRepayment).where(WalletRepayment.debt_id == debt.id,
            WalletRepayment.active.is_(True)).order_by(WalletRepayment.id))).scalars():
            await release_repayment(db, user, repayment,
                reference=f"source:{lot.id}:reverse:{lot.revision}:repay:{repayment.id}")
        await post(db, user, 0, "debt_cancelled", f"debt:{debt.id}:cancel:{lot.revision}",
                   details={"units": debt.units})
    # 恢复来源后保留视频撤销状态，待用户重新购买；资金可先偿还其他真实欠费。
    await db.flush()
    await sweep_debts(db, user_id, environment)
    return {"lot_id": lot.id, "duplicate": False, "restored_units": restored}
