"""统一资金运营查询与Web来源对账，不提供手工伪造支付成功的入口。"""
from sqlalchemy import func, select, text

from app.models import Order, User
from app.models_wallet import WalletAccount, WalletAllocation, WalletDebt, WalletEvent, WalletFundingLot, WalletRepayment
from app.models_wallet_finance import WalletFundingReview
from app.services.billing import wallet
from .coin_service import app_fail


def fields(row, names):
    """财务查询仅输出业务白名单，不回显凭证载荷或账号密码。"""
    return {name: getattr(row, name) for name in names.split()}


async def records(db, kind, environment, page, page_size, status="", user_id=None):
    """按服务端分页读取同一部署的统一账户，不读取历史独立币余额。"""
    wallet.configured_environment(environment)
    if not wallet.enabled():
        app_fail("UNIFIED_WALLET_UNAVAILABLE", "统一余额尚未开放，请先完成迁移核对。", 503)
    choices = {
        "funding-sources": (WalletFundingLot, "id user_id environment source_type source_ref total_units total_amount_fen active settlement_status created_at"),
        "wallet-entries": (WalletEvent, "id user_id kind delta_fen frozen_delta_fen balance_after frozen_after reference created_at"),
        "debts": (WalletDebt, "id user_id cause_type cause_ref origin_lot_id units active created_at"),
        "repayments": (WalletRepayment, "id user_id debt_id allocation_id units active created_at"),
        "recharge-orders": (Order, "id user_id out_trade_no sku_id amount_fen credit_fen pay_type status trade_no paid_at created_at"),
        "funding-reviews": (WalletFundingReview, "id source_type source_ref gross_fen channel_fee_fen tax_fen received_fen operator_id note reviewed_at"),
    }
    if kind == "wallets":
        query = select(User).join(WalletAccount, WalletAccount.user_id == User.id).where(WalletAccount.environment == environment)
        if user_id:
            query = query.where(User.id == user_id)
        total = await db.scalar(select(func.count()).select_from(query.subquery()))
        rows = list((await db.scalars(query.order_by(User.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
        items = []
        for row in rows:
            debt = await wallet.debt_units(db, row.id)
            items.append({"user_id": row.id, "environment": environment, "balance_fen": row.balance_fen,
                          "frozen_fen": row.frozen_fen, "debt_fen": debt})
    else:
        model, names = choices[kind]
        conditions = []
        if hasattr(model, "environment"):
            conditions.append(model.environment == environment)
        if user_id and hasattr(model, "user_id"):
            conditions.append(model.user_id == user_id)
        if status and hasattr(model, "status"):
            conditions.append(model.status == status)
        if model is Order:
            conditions.append(Order.team_id.is_(None))
        total = await db.scalar(select(func.count()).select_from(model).where(*conditions))
        rows = list((await db.scalars(select(model).where(*conditions).order_by(model.id.desc())
                                    .offset((page-1)*page_size).limit(page_size))).all())
        items = [fields(row, names) for row in rows]
        if model is WalletFundingLot:
            for row, item in zip(rows, items):
                item["available_units"] = sum(end-start for start, end in row.available_ranges)
        if model is WalletDebt:
            for row, item in zip(rows, items):
                paid = await db.scalar(select(func.coalesce(func.sum(WalletRepayment.units), 0)).where(
                    WalletRepayment.debt_id == row.id, WalletRepayment.active.is_(True)))
                item["repaid_units"], item["outstanding_units"] = paid, max(0, row.units-paid) if row.active else 0
    return {"items": items, "meta": {"page": page, "page_size": page_size, "total": total}}


async def review_web_funding(db, body, operator_id):
    """逐来源核对Web实收，金额差异不能用任意调账掩盖。"""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": "wallet-funding-review:" + body.idempotency_key})
    lot = await db.get(WalletFundingLot, body.lot_id)
    if not lot or lot.source_type != "web_order":
        app_fail("WALLET_REVIEW_SOURCE_INVALID", "请选择已核验的Web充值来源；苹果交易请使用苹果月度对账。", 409)
    await wallet.lock_account(db, lot.user_id, lot.environment)
    lot = await db.scalar(select(WalletFundingLot).where(WalletFundingLot.id == body.lot_id)
                          .with_for_update().execution_options(populate_existing=True))
    prior = await db.scalar(select(WalletFundingReview).where(WalletFundingReview.idempotency_key == body.idempotency_key))
    if prior:
        if prior.source_ref != lot.source_ref or any(getattr(prior, key) != getattr(body, key) for key in
                ("channel_fee_fen", "tax_fen", "received_fen", "note")):
            app_fail("MARKETPLACE_IDEMPOTENCY_CONFLICT", "本次对账编号已用于其他资金记录。", 409)
        return prior
    order = await db.scalar(select(Order).where(Order.out_trade_no == lot.source_ref))
    if (not order or order.pay_type not in ("alipay", "wxpay") or order.status != "paid"
            or order.user_id != lot.user_id or order.credit_fen != lot.total_units or not lot.active
            or lot.settlement_status == "reconciled" or order.amount_fen != lot.total_amount_fen):
        app_fail("WALLET_REVIEW_SOURCE_INVALID", "来源未付款、已失效、已对账或金额不一致，请人工核对。", 409)
    if body.received_fen != lot.total_amount_fen-body.channel_fee_fen-body.tax_fen:
        app_fail("WALLET_REVIEW_AMOUNT_MISMATCH", "净到账必须等于真实付款减渠道费和税费。", 409)
    item = WalletFundingReview(source_type=lot.source_type, source_ref=lot.source_ref,
        gross_fen=lot.total_amount_fen, channel_fee_fen=body.channel_fee_fen, tax_fen=body.tax_fen,
        received_fen=body.received_fen, note=body.note, operator_id=operator_id, idempotency_key=body.idempotency_key)
    db.add(item)
    lot.settlement_status = "reconciled"
    await db.flush()
    return item
