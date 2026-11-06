"""Accounting valuation of Apple foreign receipts, independent of retail prices."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select

from .app_models import AppleExchangeRate
from .coin_service import app_fail


def rate_text(value: str) -> str:
    try:
        rate = Decimal(value)
        if not rate.is_finite() or not 0 < rate <= 1000000 or rate.as_tuple().exponent < -6:
            raise ValueError
        return format(rate, "f")
    except (InvalidOperation, ValueError):
        app_fail("MARKETPLACE_FX_INVALID", "汇率须大于0且最多六位小数。", 422)


def cny_amount(minor: int, rate: str) -> int:
    return int((Decimal(minor) * Decimal(rate_text(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def value_transaction(db, txn: dict) -> dict:
    currency = txn.get("currency")
    minor = txn.get("payment_amount_minor", txn.get("amount_fen"))
    if currency not in ("CNY", "USD") or type(minor) is not int or minor < 0:
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "交易金额、币种或状态不正确。")
    snapshot = {"cny_per_unit": "1", "source": "CNY", "version": 0} if currency == "CNY" else {}
    if currency == "USD":
        rate = await db.scalar(select(AppleExchangeRate).where(AppleExchangeRate.currency == "USD").order_by(AppleExchangeRate.id.desc()).limit(1))
        if rate:
            snapshot = {"cny_per_unit": rate.cny_per_unit, "source": rate.source, "version": rate.id}
    return {**txn, "payment_amount_minor": minor, "fx_snapshot": snapshot,
            "amount_fen": cny_amount(minor, snapshot["cny_per_unit"]) if snapshot else 0,
            "valuation_status": "valued" if snapshot else "pending"}


async def finalize_valuation(db, transaction_id: int, rate_id: int, operator_id: int):
    """Finalize provisional costs under account/creator locks; never change credits.

    Settled receipts cannot enter this path. Append a revision and audit event;
    original zero-value receipt/refund events remain unchanged.
    """
    from app.models import Order
    from app.models_wallet import WalletAllocation
    from app.services.billing import wallet, wallet_ranges
    from .app_models import AppleTransaction, AppleTransactionRevision, CoinUnlock
    from .coin_service import funds_call, lock_creator
    from .models import ContentOrder, RevenueLedger
    from .service import event

    item = await db.get(AppleTransaction, transaction_id)
    if not item:
        app_fail("MARKETPLACE_RECORD_NOT_FOUND", "业务记录不存在。", 404)
    await funds_call(wallet.lock_account(db, item.user_id, item.environment))
    item = await db.scalar(select(AppleTransaction).where(AppleTransaction.id == item.id).with_for_update().execution_options(populate_existing=True))
    if item.valuation_status == "valued":
        if item.fx_snapshot.get("version") != rate_id:
            app_fail("MARKETPLACE_FX_IMMUTABLE", "该交易已完成核算，不能覆盖原汇率。", 409)
        return item
    rate = await db.get(AppleExchangeRate, rate_id)
    if not rate or rate.currency != item.currency:
        app_fail("MARKETPLACE_FX_INVALID", "汇率版本不存在或币种不符。", 422)
    lot = await funds_call(wallet.get_source(db, item.user_id, "apple_transaction", f"{item.environment}:{item.transaction_id}", item.environment))
    if not lot or lot.settlement_status != "pending_fx":
        app_fail("MARKETPLACE_FX_INVALID", "资金来源不处于待核算状态。", 409)
    amount = cny_amount(item.payment_amount_minor, rate.cny_per_unit)
    allocations = list((await db.execute(select(WalletAllocation).where(WalletAllocation.lot_id == lot.id).order_by(WalletAllocation.id))).scalars())
    unlock_ids = {int(a.business_ref) for a in allocations if a.business_type == "video_unlock" and a.state == "consumed"}
    unlocks = list((await db.execute(select(CoinUnlock).where(CoinUnlock.id.in_(unlock_ids), CoinUnlock.status == "paid"))).scalars()) if unlock_ids else []
    ledgers = list((await db.execute(select(RevenueLedger).where(RevenueLedger.order_id.in_([u.order_id for u in unlocks])))).scalars()) if unlocks else []
    for owner in sorted({row.owner_id for row in ledgers}):
        await lock_creator(db, owner, item.environment)
    lot.total_amount_fen, lot.settlement_status = amount, "pending"
    for allocation in allocations:
        allocation.amount_fen = wallet_ranges.cost(lot, allocation.ranges)
    await db.flush()
    corrections = []
    for unlock in unlocks:
        ledger = next(row for row in ledgers if row.order_id == unlock.order_id)
        if ledger.settlement_status not in ("pending",):
            app_fail("MARKETPLACE_FX_INVALID", "关联收益已结算，禁止覆盖。", 409)
        parts = list((await db.execute(select(WalletAllocation).where(WalletAllocation.user_id == item.user_id,
            WalletAllocation.business_type == "video_unlock", WalletAllocation.business_ref == str(unlock.id),
            WalletAllocation.state == "consumed"))).scalars())
        gross = sum(row.amount_fen for row in parts)
        corrections.append({"ledger_id": ledger.id, "old_gross_fen": ledger.gross_fen, "gross_fen": gross})
        ledger.gross_fen, ledger.platform_fen = gross, gross * ledger.share_bps // 10000
        ledger.creator_fen = gross - ledger.platform_fen
        unlock.amount_fen = gross
        order = await db.get(ContentOrder, unlock.order_id)
        order.amount_fen = gross
    item.amount_fen, item.valuation_status = amount, "valued"
    item.fx_snapshot = {"version": rate.id, "cny_per_unit": rate.cny_per_unit, "source": rate.source}
    item.revision += 1
    db.add(AppleTransactionRevision(transaction_id=item.id, revision=item.revision, status=item.status,
        delta_gross_fen=amount if item.status == "paid" else 0))
    order = await db.get(Order, item.recharge_order_id)
    order.amount_fen, order.payment_exchange_rate = amount, rate.cny_per_unit
    import json
    event(db, operator_id, "apple_transaction", item.id, "fx_valued", json.dumps({"rate_id": rate_id, "amount_fen": amount, "corrections": corrections}))
    await db.flush()
    return item
