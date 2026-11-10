"""AI 冻结和按真实用量结算，不访问 TaskRun，保持上层锁顺序。"""
from sqlalchemy import select

from app.models_wallet import WalletAllocation, WalletFundingLot, WalletTaskNotice, WalletTaskSettlement
from .wallet_base import WalletError, allocations, allocate, debt_units, ensure_can_spend, lock_account, post
from .wallet_debts import create_debt, sweep_debts
from . import wallet_ranges as ranges


async def reserve_task(db, user_id, task_id, units, *, note=""):
    """同一任务只冻结一次，已冻结任务仍需再次验证来源。"""
    user = await lock_account(db, user_id)
    item = await db.scalar(select(WalletTaskSettlement).where(WalletTaskSettlement.task_id == task_id).with_for_update())
    if item:
        if item.user_id != user_id:
            raise WalletError("WALLET_TASK_PAYER_CHANGED", "任务付款账户与资金记录不一致。")
        if item.state == "reserved":
            await validate_task_funding(db, user_id, task_id)
        return item.reserved_units
    if type(units) is not int or units < 0:
        raise WalletError("WALLET_AMOUNT_INVALID", "任务预扣额度不正确。", 400)
    await ensure_can_spend(db, user)
    if units:
        await allocate(db, user, units, "ai_task", str(task_id), state="reserved")
    db.add(WalletTaskSettlement(user_id=user_id, task_id=task_id, reserved_units=units,
                                charged_units=0, refunded_units=0, state="reserved"))
    await post(db, user, -units, "freeze", f"task:{task_id}:freeze", frozen_delta=units, details={"note": note})
    return units


async def validate_task_funding(db, user_id, task_id):
    """上游调用前检查欠费和本次冻结来源，退款后不可再启动新调用。"""
    user = await lock_account(db, user_id)
    await ensure_can_spend(db, user)
    items = await allocations(db, user_id, "ai_task", str(task_id))
    task = await db.scalar(select(WalletTaskSettlement).where(WalletTaskSettlement.task_id == task_id))
    if task is None or task.user_id != user_id or task.state != "reserved":
        raise WalletError("WALLET_TASK_RESERVATION_REQUIRED", "任务没有有效预扣记录，不能发起新的付费调用。", 409)
    if sum(item.units for item in items if item.state == "reserved") != task.reserved_units:
        raise WalletError("WALLET_TASK_FUNDING_INCONSISTENT", "任务预扣与来源记录不一致，请联系管理员。", 503)
    for item in items:
        lot = await db.get(WalletFundingLot, item.lot_id)
        if item.state == "reserved" and not lot.active:
            raise WalletError("WALLET_SOURCE_REVOKED", "任务预扣资金已退款，已停止新的付费调用。")


async def settle_task(db, user_id, task_id, charged_units, *, note=""):
    """退回有效未用预扣；实际已发生且无法收回的费用成为明确欠费。"""
    user = await lock_account(db, user_id)
    task = await db.scalar(select(WalletTaskSettlement).where(WalletTaskSettlement.task_id == task_id).with_for_update())
    if task and task.state == "settled":
        return {"charged": task.charged_units, "refunded": task.refunded_units,
                "debt_fen": await debt_units(db, user_id)}
    if type(charged_units) is not int or charged_units < 0:
        raise WalletError("WALLET_AMOUNT_INVALID", "任务结算额度不正确。", 400)
    if task is None:
        task = WalletTaskSettlement(user_id=user_id, task_id=task_id, reserved_units=0,
                                    charged_units=0, refunded_units=0, state="reserved")
        db.add(task)
        await db.flush()
    if task.user_id != user_id:
        raise WalletError("WALLET_TASK_PAYER_CHANGED", "任务付款账户与资金记录不一致。")
    items = await allocations(db, user_id, "ai_task", str(task_id))
    if sum(item.units for item in items if item.state == "reserved") != task.reserved_units:
        raise WalletError("WALLET_TASK_FUNDING_INCONSISTENT", "任务预扣与来源记录不一致，结算已停止。", 503)
    remaining, refunded = charged_units, 0
    for item in items:
        if item.state != "reserved":
            continue
        lot = await db.get(WalletFundingLot, item.lot_id)
        used = min(remaining, item.units)
        used_ranges, unused_ranges = ranges.split(item.ranges, used)
        unused = item.units - used
        if unused:
            ranges.put(lot, unused_ranges)
            if lot.active:
                refunded += unused
        if used:
            item.units, item.ranges, item.amount_fen = used, used_ranges, ranges.cost(lot, used_ranges)
            item.state = "consumed"
            if unused:
                db.add(WalletAllocation(user_id=user_id, lot_id=lot.id, business_type="ai_task",
                    business_ref=str(task_id), units=unused, amount_fen=ranges.cost(lot, unused_ranges),
                    ranges=unused_ranges, state="returned"))
            if not lot.active:
                await create_debt(db, user, used, "source_refund", str(item.id), origin_lot_id=lot.id)
        else:
            item.state = "returned"
        remaining -= used
    # 仅超预扣才需要新来源；与有效预扣返还不会同时发生。
    extras = await allocate(db, user, remaining, "ai_task", str(task_id), partial=True) if remaining else []
    funded = sum(item.units for item in extras)
    if remaining > funded:
        await create_debt(db, user, remaining - funded, "ai_overage", str(task_id))
    await post(db, user, refunded - funded, "settle", f"task:{task_id}:settle",
               frozen_delta=-task.reserved_units,
               details={"charged": charged_units, "refunded": refunded, "funded_overage": funded, "note": note})
    task.state, task.charged_units, task.refunded_units = "settled", charged_units, refunded
    for notice in (await db.execute(select(WalletTaskNotice).where(WalletTaskNotice.task_id == task_id,
                                                                 WalletTaskNotice.status == "pending"))).scalars():
        notice.status = "done"
    await db.flush()
    await sweep_debts(db, user_id)
    return {"charged": charged_units, "refunded": refunded, "debt_fen": await debt_units(db, user_id)}
