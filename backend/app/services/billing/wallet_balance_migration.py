"""Explicit, fingerprinted original-balance cutover. Never a replay-error fallback."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from sqlalchemy import select

from app.models import User, Order, WalletLedger
from app.models_wallet import (WalletAccount, WalletAllocation, WalletDebt, WalletEvent,
    WalletFundingLot, WalletMigrationResolution, WalletRepayment, WalletTaskNotice, WalletTaskSettlement)
from . import wallet_ranges as ranges


@dataclass
class BalancePlan:
    user: object
    snapshot: dict
    preview: dict
    sources: list
    allocations: list
    approval: dict


def record(row, keys=None):
    names = keys.split() if keys else row.__table__.columns.keys()
    return {key: (value.isoformat() if isinstance(value, datetime) else value)
            for key in names if (value := getattr(row, key, None)) is not None}


async def load_snapshot(db, user_id, tables):
    async def rows(model):
        if model.__tablename__ not in tables:
            return []
        return list((await db.execute(select(model).where(model.user_id == user_id)
            .order_by(model.id).execution_options(populate_existing=True))).scalars())
    user = await db.scalar(select(User).where(User.id == user_id).execution_options(populate_existing=True))
    data = {"user": record(user, "id balance_fen frozen_fen")}
    for key, model in (("accounts", WalletAccount), ("lots", WalletFundingLot),
                       ("allocations", WalletAllocation), ("debts", WalletDebt),
                       ("repayments", WalletRepayment), ("notices", WalletTaskNotice),
                       ("events", WalletEvent), ("task_settlements", WalletTaskSettlement)):
        data[key] = [record(row) for row in await rows(model)]
    entries, orders = await rows(WalletLedger), await rows(Order)
    data["entries"] = [record(row) for row in entries]
    data["orders"] = [record(row, "id user_id team_id out_trade_no trade_no status pay_type payment_environment amount_fen credit_fen payment_currency payment_amount_minor payment_exchange_rate") for row in orders]
    from app.marketplace.app_models import AppleTransaction, CoinWallet
    data["apple_transactions"] = [record(row, "id user_id transaction_id environment status coins amount_fen recharge_order_id revision currency payment_amount_minor valuation_status") for row in await rows(AppleTransaction)]
    data["coin_wallets"] = [record(row) for row in await rows(CoinWallet)]
    return user, entries, orders, data


def prepare(user, entries, orders, snapshot):
    """Pure decision logic: preserve proven sources; never guess real cash allocation."""
    from .wallet_migration import (Source, historical_opening, replay_ledger,
        source_payment_problems, validate_account_structure)
    from types import SimpleNamespace as NS
    balance = int(user.balance_fen or 0)
    lots = [NS(**item) for item in snapshot["lots"]]
    allocations = [NS(**item) for item in snapshot["allocations"]]
    if int(user.frozen_fen or 0) or any(a.state == "reserved" for a in allocations):
        raise ValueError("仍有实际冻结或预留额度，请先排空任务并结算")
    if any(item.get("active") for item in snapshot["debts"]):
        raise ValueError("已有欠费及偿还关系，请先完成逐笔核对，不能按余额覆盖")
    if any(item.get("state") == "reserved" and item.get("reserved_units", 0) > 0
           for item in snapshot.get("task_settlements", [])):
        raise ValueError("任务资金冻结尚未结算，请先完成任务核对")
    if any(item.get("status") == "pending" for item in snapshot["notices"]):
        raise ValueError("仍有待处理退款任务，不能建立新余额基线")
    if any(item.get("environment") == "Production" and item.get("balance_coins", 0)
           for item in snapshot["coin_wallets"]):
        raise ValueError("还有独立正式观影币余额，请先按原来源合并，不能遗漏真实付款")
    def linked_transactions(order):
        return [t for t in snapshot["apple_transactions"]
                if t.get("user_id", user.id) == user.id and
                (t.get("recharge_order_id") == order.id or
                 (getattr(order, "trade_no", None) and
                  str(t["transaction_id"]) == str(order.trade_no)))]

    sandbox_order_ids = set()
    for order in orders:
        if getattr(order, "pay_type", None) != "apple_iap":
            continue
        linked = linked_transactions(order)
        if len(linked) > 1:
            raise ValueError("Apple订单关联多个交易凭证，请先核对，不能猜测支付环境")
        if linked and linked[0]["environment"] == "Sandbox":
            sandbox_order_ids.add(order.id)
    real_orders = [o for o in orders if o.status == "paid" and o.team_id is None
                   and getattr(o, "payment_environment", None) in (None, "Production")
                   and not (getattr(o, "pay_type", None) == "apple_iap" and o.id in sandbox_order_ids)]
    production = [lot for lot in lots if lot.environment == "Production"]
    production_ids = {lot.id for lot in production}
    production_allocations = [a for a in allocations if a.lot_id in production_ids]
    preserved = []
    if production:
        try:
            if source_payment_problems(production, orders):
                raise ValueError("来源与真实付款不一致")
            validate_account_structure(user.id, production, production_allocations, [], [])
            preserved = production
        except (RuntimeError, ValueError):
            if any(lot.source_type in ("web_order", "apple_transaction") for lot in production):
                raise ValueError("真实付款来源损坏，必须修复证据，不能改成赠额或猜测实付")
    preserved_ids = {lot.id for lot in preserved}
    kept = sum(ranges.units(lot.available_ranges) for lot in preserved if lot.active)
    if kept > max(0, balance):
        raise ValueError("真实来源可用额度高于原积分，须核对已消费区间，不能猜测扣减")
    retired = [lot for lot in lots if lot.id not in preserved_ids]
    # Valid personal payment evidence must survive as its original funding lot.
    sources, new_allocations = [], []
    pending_order_ids = []
    if not lots and real_orders:
        try:
            opening = historical_opening(entries, balance)
        except RuntimeError as error:
            # Only a broken balance chain is eligible. Payment evidence is
            # independently checked below, never bypassed by this decision.
            if "前后余额不连续" not in str(error) and "末笔流水与当前余额不一致" not in str(error):
                raise
            from .wallet_migration import payment_evidence_problems
            problems = payment_evidence_problems(entries, orders)
            if any(entry.kind == "topup" and entry.ref_type != "order" for entry in entries):
                problems.append("充值流水引用类型不是订单，不能确认成本待核算")
            if problems:
                raise ValueError("；".join(problems)) from error
            for order in real_orders:
                matching = [entry for entry in entries if entry.kind == "topup"
                            and entry.ref_type == "order"
                            and str(entry.ref_id) in (str(order.id), order.out_trade_no)]
                if (getattr(order, "user_id", None) != user.id
                        or getattr(order, "pay_type", None) not in ("alipay", "wxpay", "stripe")
                        or len(matching) != 1):
                    raise ValueError("真实付款缺少唯一且有效的原入账凭证，请先核对") from error
            pending_order_ids = [order.id for order in real_orders]
            opening = None
        try:
            if opening is not None:
                sources, new_allocations, debt = replay_ledger(entries, orders, balance, 0, opening_balance=opening)
                if debt != max(0, -balance):
                    raise ValueError("欠费不一致")
        except (RuntimeError, ValueError, TypeError) as error:
            raise ValueError("存在真实付款但无法确定剩余来源，请先核对，不能将真实充值改成零成本") from error
        kept = sum(ranges.units(source.available_ranges) for source in sources)
    funded_web = {lot.source_ref for lot in preserved if lot.source_type == "web_order"}
    funded_web.update(source.source_ref for source in sources if source.source_type == "web_order")
    funded_apple = {lot.source_ref for lot in preserved if lot.source_type == "apple_transaction"}
    for lot in preserved:
        if lot.source_type != "apple_transaction":
            continue
        matching = [t for t in snapshot["apple_transactions"] if f"Production:{t['transaction_id']}" == lot.source_ref
                    and t["environment"] == "Production" and t["coins"] == lot.total_units
                    and t["amount_fen"] == lot.total_amount_fen and t["status"] in ("paid", "refunded")
                    and lot.active == (t["status"] == "paid")]
        if len(matching) != 1:
            raise ValueError("正式Apple来源与原始交易不一致，不能按原积分掩盖实付差异")
    if any(t["environment"] == "Production" and f"Production:{t['transaction_id']}" not in funded_apple
           for t in snapshot["apple_transactions"]):
        raise ValueError("真实Apple交易缺少原资金来源，请先核对，不能按余额忽略付款事实")
    for order in real_orders:
        if order.id in pending_order_ids:
            continue
        if getattr(order, "pay_type", None) == "apple_iap":
            matches = [t for t in linked_transactions(order)
                       if t["environment"] == "Production" and t["status"] == "paid"
                       and t["coins"] == order.credit_fen and f"Production:{t['transaction_id']}" in funded_apple]
            if len(matches) != 1:
                raise ValueError("真实Apple充值尚未核实入账，不能作为平台赠额替代")
        elif order.out_trade_no not in funded_web and str(order.id) not in funded_web:
            raise ValueError("真实充值缺少可追溯来源，不能按原积分忽略已付款订单")
    known_preserved = kept - sum(ranges.units(source.available_ranges) for source in sources if source.valuation_pending)
    target = max(0, balance)
    residual = target - kept
    sandbox_account = any(item["environment"] == "Sandbox" for item in snapshot["accounts"])
    sandbox_units = 0
    if not sandbox_account:
        for lot in retired:
            if lot.environment != "Sandbox" or not lot.active:
                continue
            try:
                sandbox_units += ranges.units(ranges.normalize(lot.total_units, lot.available_ranges))
            except (TypeError, ValueError):
                # Unprovable residual remains pending, never certified free cash.
                continue
    gift = 0 if pending_order_ids else residual if sandbox_account else min(residual, sandbox_units)
    pending = residual - gift
    if gift:
        sources.append(Source("admin_grant", "balance-sandbox-replacement", gift, 0, [[0, gift]]))
    if pending:
        sources.append(Source("legacy_opening", "balance-unexplained", pending, 0, [[0, pending]], True))
    fingerprint = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode()).hexdigest()
    preview = {"eligible": True, "fingerprint": fingerprint, "environment": "Production",
        "original_balance_fen": balance, "merged_balance_fen": target, "remaining_debt_fen": max(0, -balance),
        "platform_grant_fen": gift, "pending_units": sum(ranges.units(s.available_ranges) for s in sources if s.valuation_pending),
        "preserved_units": known_preserved, "archived_lot_ids": [lot.id for lot in retired],
        "preserved_order_ids": [order.id for order in real_orders if order.id not in pending_order_ids],
        "pending_order_ids": pending_order_ids,
        "pending_payment_reason": "历史余额链不连续，原付款及入账凭证保留，消费分摊与实付成本待核算" if pending_order_ids else None}
    return preview, sources, new_allocations


async def candidate(db, user_id, tables):
    user, entries, orders, snapshot = await load_snapshot(db, user_id, tables)
    try:
        preview, sources, allocations = prepare(user, entries, orders, snapshot)
    except (ValueError, RuntimeError, TypeError) as error:
        return {"eligible": False, "reason": str(error)}, None
    return preview, BalancePlan(user, snapshot, preview, sources, allocations, {})


async def apply(db, plan, backup_reference):
    """Called only under the same cutover advisory/table locks, after database backup."""
    user, preview, old = plan.user, plan.preview, plan.snapshot
    if await db.scalar(select(WalletMigrationResolution.id).where(WalletMigrationResolution.user_id == user.id)):
        raise ValueError("该账户已有按原积分迁移记录，请刷新，不能重复补赠")
    for lot_id in preview["archived_lot_ids"]:
        lot = await db.get(WalletFundingLot, lot_id)
        if lot.environment == "Production":
            # Close mutable grant state; immutable ledgers and the exact prior
            # lot snapshot remain intact. Never retire real payment lots.
            lot.active, lot.settlement_status = False, "migration_archived"
    marker = await db.scalar(select(WalletAccount).where(WalletAccount.user_id == user.id))
    if marker is None:
        db.add(WalletAccount(user_id=user.id, environment="Production", migration_reference=backup_reference))
    else:
        marker.environment, marker.migration_reference = "Production", backup_reference
    new_lots = []
    for index, source in enumerate(plan.sources):
        ref = source.source_ref if source.source_type == "web_order" else f"balance:{preview['fingerprint']}:{index}"
        lot = WalletFundingLot(user_id=user.id, environment="Production", source_type=source.source_type,
            source_ref=ref, total_units=source.total_units, total_amount_fen=source.total_amount_fen,
            available_ranges=source.available_ranges, void_ranges=[], active=True, revision=0,
            settlement_status="pending_fx" if source.valuation_pending else "reconciled" if source.total_amount_fen == 0 else "pending")
        db.add(lot)
        await db.flush()
        new_lots.append(lot)
    for item in plan.allocations:
        values = dict(item)
        index = values.pop("source_index")
        db.add(WalletAllocation(user_id=user.id, lot_id=new_lots[index].id, **values))
    if preview["remaining_debt_fen"]:
        db.add(WalletDebt(user_id=user.id, cause_type="legacy_overage", cause_ref=backup_reference,
            units=preview["remaining_debt_fen"], active=True))
    user.balance_fen = preview["merged_balance_fen"]
    result = dict(preview)
    db.add(WalletMigrationResolution(user_id=user.id, fingerprint=preview["fingerprint"],
        backup_reference=backup_reference, operator_id=plan.approval["operator_id"],
        reason=plan.approval["reason"], snapshot=old, result=result))
    gift = preview["platform_grant_fen"]
    baseline_balance = user.balance_fen - gift
    delta = baseline_balance - preview["original_balance_fen"]
    details = {"mode": "original_balance", "operator_id": plan.approval["operator_id"],
        "reason": plan.approval["reason"], "backup_reference": backup_reference,
        "platform_grant_fen": preview["platform_grant_fen"], "pending_units": preview["pending_units"],
        "original_balance_fen": preview["original_balance_fen"], "debt_fen": preview["remaining_debt_fen"],
        "note": "按原积分迁移；Sandbox替代额度由平台赠送，原交易及流水保留"}
    db.add(WalletEvent(user_id=user.id, reference="balance-migration:" + backup_reference, kind="migration",
        delta_fen=delta, frozen_delta_fen=0, balance_after=baseline_balance, frozen_after=0, details=details))
    db.add(WalletLedger(user_id=user.id, delta_fen=delta, balance_after=baseline_balance,
        kind="migration", ref_type="unified_wallet", ref_id="balance-baseline", note=details["note"] + "；" + backup_reference))
    if gift:
        db.add(WalletEvent(user_id=user.id, reference="balance-migration:" + backup_reference + ":grant",
            kind="grant", delta_fen=gift, frozen_delta_fen=0, balance_after=user.balance_fen, frozen_after=0,
            details={**details, "note": "平台补发正式赠额，替代原Sandbox剩余额度，不代表Apple正式付款"}))
        db.add(WalletLedger(user_id=user.id, delta_fen=gift, balance_after=user.balance_fen,
            kind="grant", ref_type="unified_wallet", ref_id="balance-sandbox-grant",
            note="平台补发正式赠额，替代Sandbox剩余额度；" + backup_reference))
    await db.flush()
