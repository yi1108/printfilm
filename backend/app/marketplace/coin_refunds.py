"""Apple 退款适配：统一资金追偿、视频撤权与创作者收益冲正。"""
from sqlalchemy import select

from app.models import Order
from app.services.billing import wallet
from .app_models import AppleTransaction, AppleTransactionRevision, AppPayoutItem, CoinGrant, CoinUnlock, RevenueAdjustment
from .coin_service import app_fail, funds_call, lock_creator, lock_wallet
from .models import ContentOrder, Entitlement, Publication, RevenueLedger
from .service import event, notify, now


async def _reverse_unlock(db, item: CoinUnlock, refunded_transaction: AppleTransaction) -> None:
    """整单只撤销一次，只撤回该次授予，返还其他有效资金后先补欠费。"""
    if item.status != "paid":
        return
    item.status = "revoked"
    order = await db.get(ContentOrder, item.order_id)
    if order:
        order.status = "revoked"
    grant = await db.scalar(select(CoinGrant).where(CoinGrant.unlock_id == item.id).with_for_update())
    if grant:
        grant.active = False
    entitlement = None
    if item.environment == "Production":
        entitlement = await db.scalar(select(Entitlement).where(Entitlement.user_id == item.user_id,
            Entitlement.publication_id == item.publication_id).with_for_update())
        if entitlement and entitlement.order_id == item.order_id:
            entitlement.active = False
    ledger = await db.scalar(select(RevenueLedger).where(RevenueLedger.order_id == item.order_id))
    if ledger:
        creator = await lock_creator(db, ledger.owner_id, item.environment)
        ledger = await db.scalar(select(RevenueLedger).where(RevenueLedger.id == ledger.id).with_for_update())
        paid = await db.scalar(select(AppPayoutItem.id).where(AppPayoutItem.ledger_id == ledger.id))
        if paid:
            creator.debt_fen += ledger.creator_fen
        else:
            ledger.settlement_status = "revoked"
        db.add(RevenueAdjustment(unlock_id=item.id, owner_id=ledger.owner_id, environment=item.environment,
            gross_fen=-ledger.gross_fen, platform_fen=-ledger.platform_fen, creator_fen=-ledger.creator_fen,
            reason=f"苹果充值退款 {refunded_transaction.transaction_id}"))
    if item.environment == "Production" and entitlement and entitlement.active and entitlement.order_id != item.order_id:
        # 在途Web付款此前因同版本已有余额权益而暂不重复记收益；余额收益撤回后，
        # 保留其独立实收来源，并把存活Web订单的收益补齐一次。
        surviving_order = await db.get(ContentOrder, entitlement.order_id) if entitlement.order_id else None
        if (surviving_order and surviving_order.user_id == item.user_id
                and surviving_order.publication_id == item.publication_id
                and surviving_order.status == "paid" and surviving_order.pay_type in ("alipay", "wxpay")):
            from .commerce import ensure_paid_order_revenue
            publication = await db.get(Publication, item.publication_id)
            if publication:
                recovered = await ensure_paid_order_revenue(db, surviving_order, publication)
                if recovered:
                    event(db, item.user_id, "content_order", surviving_order.id, "paid_revenue_recovered",
                          "余额购买已撤销，按存活的易支付实收订单补齐收益；不重复授予权益", publication.version)
    await funds_call(wallet.restore_consumption(db, item.user_id, "video_unlock", str(item.id), environment=item.environment))
    notify(db, item.user_id, f"充值已由苹果退款，关联解锁订单 {order.out_trade_no if order else item.id} 已撤销；其他有效来源已退回平台余额并优先抵扣欠费。")


async def refund_apple_transaction(db, environment: str, transaction_id: str, reversed: bool = False):
    """权威状态已在事务外向 Apple 查询；用户锁内原子处理退款及偿还链。"""
    transaction = await db.scalar(select(AppleTransaction).where(AppleTransaction.environment == environment,
        AppleTransaction.transaction_id == str(transaction_id)))
    if not transaction:
        app_fail("MARKETPLACE_IAP_TRANSACTION_UNKNOWN", "尚未收到该笔充值的完整交易信息，请先补验单。", 409)
    await lock_wallet(db, transaction.user_id, environment)
    transaction = await db.scalar(select(AppleTransaction).where(AppleTransaction.id == transaction.id)
        .with_for_update().execution_options(populate_existing=True))
    source_ref = f"{environment}:{transaction_id}"
    if reversed:
        if transaction.status != "refunded":
            return transaction
        await funds_call(wallet.reverse_source(db, transaction.user_id, "apple_transaction", source_ref, environment=environment))
        transaction.status = "paid"
        transaction.revision += 1
        transaction.settlement_status = "pending"
        transaction.revoked_at = None
        db.add(AppleTransactionRevision(transaction_id=transaction.id, revision=transaction.revision,
            status="paid", delta_gross_fen=transaction.amount_fen))
        order = await db.get(Order, transaction.recharge_order_id) if transaction.recharge_order_id else None
        if order:
            order.status = "paid"
        notify(db, transaction.user_id, "苹果已撤销充值退款，平台已按原消费及偿还记录恢复相应余额。已撤销的观看权益不会自动恢复，可重新解锁。")
        await db.flush()
        return transaction
    if transaction.status == "refunded":
        return transaction
    result = await funds_call(wallet.revoke_source(db, transaction.user_id, "apple_transaction", source_ref, environment=environment))
    transaction.status = "refunded"
    transaction.revision += 1
    transaction.settlement_status = "pending"
    transaction.revoked_at = now()
    db.add(AppleTransactionRevision(transaction_id=transaction.id, revision=transaction.revision,
        status="refunded", delta_gross_fen=-transaction.amount_fen))
    order = await db.get(Order, transaction.recharge_order_id) if transaction.recharge_order_id else None
    if order:
        order.status = "refunded"
    unlock_ids = {int(item["business_ref"]) for item in result["affected_business_refs"]
                  if item["business_type"] == "video_unlock"}
    if unlock_ids:
        items = list((await db.execute(select(CoinUnlock).where(CoinUnlock.id.in_(unlock_ids),
            CoinUnlock.user_id == transaction.user_id, CoinUnlock.environment == environment,
            CoinUnlock.status == "paid").order_by(CoinUnlock.id).with_for_update())).scalars())
        owner_ids = (await db.execute(select(RevenueLedger.owner_id).where(
            RevenueLedger.order_id.in_([item.order_id for item in items])).distinct())).scalars().all()
        for owner_id in sorted(owner_ids):
            await lock_creator(db, owner_id, environment)
        for item in items:
            await _reverse_unlock(db, item, transaction)
    await funds_call(wallet.sweep_debts(db, transaction.user_id, environment=environment))
    notify(db, transaction.user_id, "苹果已退还一笔充值，相关余额和观看权益已按规则处理。实际发生的AI消费优先从其他可用余额抵扣，不足部分需充值补齐。")
    await db.flush()
    return transaction
