"""苹果充值对账和创作者人工打款，所有金额由服务端核对。"""
from sqlalchemy import and_, cast, select, text, String

from app.models_wallet import WalletAllocation, WalletFundingLot
from .app_models import AppleSettlement, AppleSettlementItem, AppleTransaction, AppleTransactionRevision, AppPayout, AppPayoutItem, CoinUnlock
from .coin_service import PRICE_DIFFERENCE_ANOMALY, app_fail, lock_creator
from .models import RevenueLedger


def eligible_condition():
    """每笔解锁的所有充值来源均已对账、未退款且无异常才能打款。"""
    invalid = select(WalletAllocation.id).join(WalletFundingLot, WalletFundingLot.id == WalletAllocation.lot_id).where(
        WalletAllocation.business_type == "video_unlock",
        WalletAllocation.business_ref == cast(CoinUnlock.id, String),
        (WalletFundingLot.active.is_(False)) | (WalletFundingLot.settlement_status != "reconciled"))
    funded = select(WalletAllocation.id).where(WalletAllocation.business_type == "video_unlock",
        WalletAllocation.business_ref == cast(CoinUnlock.id, String), WalletAllocation.state == "consumed")
    paid = select(AppPayoutItem.id).where(AppPayoutItem.ledger_id == RevenueLedger.id)
    return (CoinUnlock.status == "paid", RevenueLedger.settlement_status != "revoked", funded.exists(), ~invalid.exists(), ~paid.exists())


async def reconcile(db, body, operator_id: int) -> AppleSettlement:
    """对账只登记核实后的苹果报表，不把客户端付款提示当实际到账。"""
    # 幂等编号跨环境唯一，固定同一个独立锁避免跨环境并发撞唯一约束。
    await lock_creator(db, 0, "Production")
    prior = (await db.execute(select(AppleSettlement).where(AppleSettlement.idempotency_key == body.idempotency_key))).scalar_one_or_none()
    requested = sorted(body.transaction_ids)
    if prior:
        actual = sorted(set((await db.execute(select(AppleSettlementItem.transaction_id).where(AppleSettlementItem.settlement_id == prior.id))).scalars()))
        if prior.environment != body.environment or actual != requested or any(getattr(prior, name) != getattr(body, name) for name in ("month", "channel_fee_fen", "tax_fen", "received_fen", "note")):
            app_fail("MARKETPLACE_IDEMPOTENCY_CONFLICT", "该对账操作编号已用于其他内容。", 409)
        return prior
    rows = list((await db.execute(select(AppleTransaction).where(AppleTransaction.id.in_(requested)).order_by(AppleTransaction.id).with_for_update())).scalars())
    # 已验签实付是现金成本；参考价差保留提示，并由本次真实报表精确对账。
    # 其他异常仍须先排查，不允许凭一条备注批量忽略。
    if len(rows) != len(requested) or any(row.environment != body.environment or row.settlement_status != "pending" or row.valuation_status != "valued"
            or row.anomaly not in ("", PRICE_DIFFERENCE_ANOMALY) for row in rows):
        app_fail("MARKETPLACE_SETTLEMENT_INVALID", "交易不存在、环境不符、存在异常或已经对账，请重新核对。", 409)
    revisions = list((await db.execute(select(AppleTransactionRevision).where(
        AppleTransactionRevision.transaction_id.in_(requested)).order_by(
        AppleTransactionRevision.transaction_id, AppleTransactionRevision.revision))).scalars())
    for row in rows:
        history = [revision for revision in revisions if revision.transaction_id == row.id]
        if ([revision.revision for revision in history] != list(range(row.revision + 1))
                or history[-1].status != row.status):
            app_fail("MARKETPLACE_SETTLEMENT_REVISION_MISSING", "交易财务事件记录不完整，请人工核对，不能沿用旧对账。", 409)
    # 锁住交易当前版本后一次收齐尚未对账的事件；未对账充值+退款净额为0。
    pending = list((await db.execute(select(AppleTransactionRevision).outerjoin(AppleSettlementItem, and_(
        AppleSettlementItem.transaction_id == AppleTransactionRevision.transaction_id,
        AppleSettlementItem.revision == AppleTransactionRevision.revision)).where(
        AppleTransactionRevision.transaction_id.in_(requested), AppleSettlementItem.id.is_(None)
    ).order_by(AppleTransactionRevision.transaction_id, AppleTransactionRevision.revision))).scalars())
    if set(revision.transaction_id for revision in pending) != set(requested):
        app_fail("MARKETPLACE_SETTLEMENT_INVALID", "所选交易没有新的待对账事件，请刷新后核对。", 409)
    gross = sum(revision.delta_gross_fen for revision in pending)
    if body.received_fen != gross - body.channel_fee_fen - body.tax_fen:
        app_fail("MARKETPLACE_SETTLEMENT_AMOUNT_MISMATCH", "实际到账必须等于本次交易净收款减渠道费和税费；请拆分核对，勿用调差掩盖差异。", 409)
    item = AppleSettlement(environment=body.environment, month=body.month, gross_fen=gross,
                           channel_fee_fen=body.channel_fee_fen, tax_fen=body.tax_fen, received_fen=body.received_fen,
                           operator_id=operator_id, note=body.note, idempotency_key=body.idempotency_key)
    db.add(item)
    await db.flush()
    for row in rows:
        row.settlement_status = "reconciled"
        # Apple source and the shared funding lot must become eligible together.
        from app.models_wallet import WalletFundingLot
        await db.execute(
            WalletFundingLot.__table__.update()
            .where(WalletFundingLot.source_type == "apple_transaction",
                   WalletFundingLot.source_ref == f"{body.environment}:{row.transaction_id}")
            .values(settlement_status="reconciled")
        )
    for revision in pending:
        db.add(AppleSettlementItem(settlement_id=item.id, transaction_id=revision.transaction_id,
                                  revision=revision.revision, status=revision.status, gross_fen=revision.delta_gross_fen))
    await db.flush()
    return item


async def create_payout(db, body, operator_id: int) -> AppPayout:
    """只登记人工已打款或全额抵扣，不调用任何转账服务。"""
    # 幂等键是全局唯一，必须先跨作者/环境串行化同键，再取创作者结算锁。
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": "marketplace-app-payout:" + body.idempotency_key})
    creator = await lock_creator(db, body.owner_id, body.environment)
    prior = (await db.execute(select(AppPayout).where(AppPayout.idempotency_key == body.idempotency_key))).scalar_one_or_none()
    requested = sorted(body.ledger_ids)
    if prior:
        actual = sorted((await db.execute(select(AppPayoutItem.ledger_id).where(AppPayoutItem.payout_id == prior.id))).scalars())
        if prior.owner_id != body.owner_id or prior.environment != body.environment or prior.amount_fen != body.amount_fen or prior.note != body.note or actual != requested:
            app_fail("MARKETPLACE_IDEMPOTENCY_CONFLICT", "该打款操作编号已用于其他内容。", 409)
        return prior
    rows = list((await db.execute(select(RevenueLedger).join(CoinUnlock, CoinUnlock.order_id == RevenueLedger.order_id).where(
        RevenueLedger.id.in_(requested), RevenueLedger.owner_id == body.owner_id, CoinUnlock.environment == body.environment,
        *eligible_condition()).order_by(RevenueLedger.id).with_for_update(of=RevenueLedger))).scalars())
    if len(rows) != len(requested):
        app_fail("MARKETPLACE_PAYOUT_NOT_ELIGIBLE", "收益尚未全部对账、已撤销、已打款或不属于该创作者，不能重复结算。", 409)
    gross = sum(row.creator_fen for row in rows)
    offset = min(gross, creator.debt_fen)
    if body.amount_fen != gross - offset:
        app_fail("MARKETPLACE_PAYOUT_AMOUNT_MISMATCH", f"本次可登记打款为{(gross-offset)/100:.2f}元，已扣除待抵扣金额{offset/100:.2f}元。", 409)
    item = AppPayout(owner_id=body.owner_id, environment=body.environment, amount_fen=body.amount_fen,
                     debt_offset_fen=offset, status="paid" if body.amount_fen else "offset_only",
                     operator_id=operator_id, note=body.note, idempotency_key=body.idempotency_key)
    db.add(item)
    await db.flush()
    creator.debt_fen -= offset
    for row in rows:
        row.settlement_status = "paid"
        db.add(AppPayoutItem(payout_id=item.id, ledger_id=row.id))
    await db.flush()
    return item
