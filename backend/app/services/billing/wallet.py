"""统一平台余额门面；所有变更由调用者提交同一个数据库事务。"""
from sqlalchemy import select

from app.models_wallet import WalletAllocation, WalletFundingLot
from .wallet_base import (WalletError, allocations, allocate, debt_units, enabled, ensure_can_spend,
                          environment as configured_environment, get_source, initialize_account, lock_account, post)
from .wallet_debts import sweep_debts
from . import wallet_ranges as ranges

_SOURCE_TYPES = {"web_order", "apple_transaction", "signup_grant", "admin_grant", "legacy_opening"}


async def credit(db, user_id, units, *, source_type, source_ref, amount_fen=0, environment=None, note=""):
    """到账额度和真实实付分别保存，重试返回原来源而不再次入账。"""
    if source_type not in _SOURCE_TYPES or not str(source_ref).strip():
        raise WalletError("WALLET_SOURCE_INVALID", "资金来源类型或编号不正确。", 400)
    user = await lock_account(db, user_id, environment)
    existing = await get_source(db, user_id, source_type, source_ref, environment)
    if existing:
        if existing.total_units != units or existing.total_amount_fen != amount_fen:
            raise WalletError("WALLET_SOURCE_CONFLICT", "该笔资金来源的金额记录不一致。")
        return existing
    if type(units) is not int or units <= 0 or type(amount_fen) is not int or amount_fen < 0:
        raise WalletError("WALLET_AMOUNT_INVALID", "到账额度或实付金额不正确。", 400)
    item = WalletFundingLot(user_id=user_id, environment=configured_environment(environment),
        source_type=source_type, source_ref=str(source_ref), total_units=units,
        total_amount_fen=amount_fen, available_ranges=[[0, units]], void_ranges=[], active=True, revision=0,
        settlement_status="reconciled" if amount_fen == 0 else "pending")
    db.add(item)
    await db.flush()
    kind = "grant" if source_type in ("signup_grant", "admin_grant") else "topup"
    await post(db, user, units, kind, f"source:{item.id}:credit", details={"note": note, "amount_fen": amount_fen})
    await sweep_debts(db, user_id, environment)
    return item


async def consume(db, user_id, units, *, business_type, business_ref, environment=None):
    """普通扣款与视频解锁共用来源；AI 使用专用冻结结算接口。"""
    user = await lock_account(db, user_id, environment)
    prior = await allocations(db, user_id, business_type, business_ref)
    if prior:
        if sum(item.units for item in prior) != units:
            raise WalletError("WALLET_IDEMPOTENCY_CONFLICT", "该操作编号对应的扣款额度不同。")
        return prior
    if type(units) is not int or units <= 0:
        raise WalletError("WALLET_AMOUNT_INVALID", "扣款额度必须是正整数。", 400)
    await ensure_can_spend(db, user)
    if business_type == "video_unlock":
        from .settlement import pending_task_commitment_fen
        pending = await pending_task_commitment_fen(db, user_id)
        if int(user.balance_fen or 0) - pending < units:
            raise WalletError("WALLET_BALANCE_INSUFFICIENT", "余额不足，部分余额已预留给 AI 任务。")
    items = await allocate(db, user, units, business_type, business_ref)
    await post(db, user, -units, "adjust" if business_type == "admin_adjustment" else "consume",
               f"consume:{business_type}:{business_ref}",
               details={"amount_fen": sum(item.amount_fen for item in items)})
    return items


async def restore_consumption(db, user_id, business_type, business_ref, environment=None):
    """整笔消费撤销，返还其他有效来源；退款来源等待退款撤销再恢复。"""
    user = await lock_account(db, user_id, environment)
    returned = 0
    for item in await allocations(db, user_id, business_type, business_ref):
        if item.state != "consumed":
            continue
        lot = await db.get(WalletFundingLot, item.lot_id)
        ranges.put(lot, item.ranges)
        item.state = "returned"
        amount = item.units if lot.active else 0
        returned += amount
        await post(db, user, amount, "refund_return", f"restore:{item.id}")
    await sweep_debts(db, user_id, environment)
    return returned


async def snapshot(db, user_id, environment=None):
    """兼容 Web/App 的同一账户快照，可消费额扣除未冻结任务预留。"""
    user = await lock_account(db, user_id, environment)
    from .settlement import pending_task_commitment_fen
    debt = await debt_units(db, user_id)
    pending = await pending_task_commitment_fen(db, user_id)
    invalid = await db.scalar(select(WalletAllocation.id).join(WalletFundingLot,
        WalletFundingLot.id == WalletAllocation.lot_id).where(WalletAllocation.user_id == user_id,
        WalletAllocation.state == "reserved", WalletFundingLot.active.is_(False)).limit(1))
    return {"balance_fen": int(user.balance_fen or 0), "frozen_fen": int(user.frozen_fen or 0),
            "debt_fen": debt, "pending_commitment_fen": pending,
            "spendable_fen": 0 if debt or invalid else max(0, int(user.balance_fen or 0) - pending),
            "refund_pending": bool(invalid), "environment": configured_environment(environment)}


# 延迟导入的模块只依赖 wallet_base，避免与原 AI settlement 产生循环。
from .wallet_tasks import reserve_task, settle_task, validate_task_funding  # noqa: E402,F401
from .wallet_refunds import revoke_source, reverse_source  # noqa: E402,F401
