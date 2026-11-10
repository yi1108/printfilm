"""历史资金回放：只有来源、余额和冻结均可核对时才生成切换快照。"""
from dataclasses import dataclass, field

from sqlalchemy import or_, select

from app.models import Order, User, WalletLedger
from app.models_wallet import WalletAccount, WalletAllocation, WalletDebt, WalletEvent, WalletFundingLot, WalletRepayment
from . import wallet_ranges as ranges


async def assert_no_active_tasks(db):
    """调用者在切换事务锁定任务表后复核，不接受未结算的在途任务。"""
    from app.models_tasks import TaskRun
    active = await db.scalar(select(TaskRun.id).where(or_(TaskRun.status.in_(
        ("pending", "leased", "running", "awaiting_poll", "awaiting_review", "cancel_requested")),
        TaskRun.billing_status.in_(("frozen", "reserved")))).limit(1))
    if active is not None:
        raise RuntimeError("仍有进行中的任务，必须先排空并结算，不能切换统一钱包")


@dataclass
class Source:
    """回放阶段仅在内存中计算，不调用真实充值履约。"""
    source_type: str
    source_ref: str
    total_units: int
    total_amount_fen: int
    available_ranges: list = field(default_factory=list)


def replay_ledger(entries, orders, expected_balance, expected_frozen):
    """按历史先后回放 FIFO；无法辨明的入账或返还立即阻止切换。"""
    if expected_frozen:
        raise RuntimeError("仍有冻结额度，必须先排空并结算 AI 任务")
    sources, allocations, held, deficit = [], [], {}, 0
    order_refs = {str(order.id): order for order in orders}
    order_refs.update({order.out_trade_no: order for order in orders})

    def withdraw(amount, kind, ref, state="consumed"):
        """回放原支出，历史负数以明确欠费记录保留。"""
        nonlocal deficit
        result = []
        for index, source in enumerate(sources):
            count = min(amount, ranges.units(source.available_ranges))
            if not count:
                continue
            selected, cash = ranges.take(source, count)
            item = {"source_index": index, "units": count, "amount_fen": cash, "ranges": selected,
                    "business_type": kind, "business_ref": ref, "state": state}
            allocations.append(item)
            result.append(item)
            amount -= count
        deficit += amount
        return result

    def repay_deficit(ref):
        """历史超额遇到退冻结或后续赠额时，先补齐负数再保留可用额度。"""
        nonlocal deficit
        amount = min(deficit, sum(ranges.units(source.available_ranges) for source in sources))
        if amount:
            deficit -= amount
            withdraw(amount, "legacy_debt_repayment", str(ref))

    for entry in entries:
        delta, kind, ref = int(entry.delta_fen), entry.kind, str(entry.ref_id)
        if kind == "freeze" and delta < 0:
            if entry.ref_type != "task_run":
                raise RuntimeError(f"流水 {entry.id} 的冻结归属无法核对")
            held.setdefault(ref, []).extend(withdraw(-delta, "ai_task", ref, "reserved"))
        elif kind == "unfreeze" and delta > 0:
            remaining = delta
            for item in reversed(held.get(ref, [])):
                if item["state"] != "reserved":
                    continue
                count = min(remaining, item["units"])
                keep, returned = ranges.split(item["ranges"], item["units"] - count)
                source = sources[item["source_index"]]
                source.available_ranges = ranges.normalize(source.total_units, source.available_ranges + returned)
                item["units"], item["ranges"], item["amount_fen"] = ranges.units(keep), keep, ranges.cost(source, keep)
                if not keep:
                    item["state"] = "returned"
                remaining -= count
            if remaining:
                raise RuntimeError(f"流水 {entry.id} 的退冻结找不到原始来源")
            repay_deficit(entry.id)
        elif delta > 0:
            if kind == "topup":
                order = order_refs.get(ref)
                if order is None or order.status != "paid" or order.credit_fen != delta or order.team_id is not None:
                    raise RuntimeError(f"流水 {entry.id} 缺少可核对的个人充值订单")
                source = Source("web_order", order.out_trade_no, delta, order.amount_fen, [[0, delta]])
            elif kind == "grant":
                source = Source("signup_grant" if entry.ref_type == "signup" else "admin_grant",
                                f"legacy-ledger:{entry.id}", delta, 0, [[0, delta]])
            else:
                raise RuntimeError(f"流水 {entry.id} 的正向资金来源未知，禁止按现金猜测")
            sources.append(source)
            repay_deficit(entry.id)
        elif delta < 0:
            if kind not in ("settle", "adjust"):
                raise RuntimeError(f"流水 {entry.id} 的支出类型 {kind} 无法核对")
            # settle 负数只表示实际扣款或冻结之外的超额，不能再扣 held 中的原预扣。
            withdraw(-delta, "ai_task" if entry.ref_type == "task_run" else "admin_adjustment", ref or str(entry.id))
        if kind == "settle":
            for item in held.get(ref, []):
                if item["state"] == "reserved":
                    item["state"] = "consumed"
    if any(item["state"] == "reserved" and item["units"] for item in allocations):
        raise RuntimeError("历史冻结未找到对应结算，必须人工核对")
    actual = sum(ranges.units(source.available_ranges) for source in sources)
    if actual != max(0, expected_balance) or deficit != max(0, -expected_balance):
        raise RuntimeError(f"历史回放与余额不一致：回放可用 {actual}，账户可用 {expected_balance}，待核对欠费 {deficit}")
    return sources, [item for item in allocations if item["units"]], deficit


async def build_report(db, environment):
    """只读报告不建表、不创建账户、不修改旧钱包或余额。"""
    from sqlalchemy import inspect
    connection = await db.connection()
    tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names(
        schema=(sync.get_execution_options().get("schema_translate_map") or {}).get(None))))
    existing_accounts = {row.user_id: row for row in (await db.execute(select(WalletAccount))).scalars()} if "wallet_accounts" in tables else {}
    reports, plans = [], []
    for user in (await db.execute(select(User).order_by(User.id))).scalars():
        if user.id in existing_accounts:
            marker = existing_accounts[user.id]
            lots = list((await db.execute(select(WalletFundingLot).where(WalletFundingLot.user_id == user.id))).scalars())
            reserved = list((await db.execute(select(WalletAllocation).where(
                WalletAllocation.user_id == user.id, WalletAllocation.state == "reserved"))).scalars())
            valid = (marker.environment == environment and all(lot.environment == environment for lot in lots)
                     and sum(ranges.units(lot.available_ranges) for lot in lots if lot.active) == int(user.balance_fen or 0)
                     and sum(item.units for item in reserved) == int(user.frozen_fen or 0))
            reports.append({"user_id": user.id, "status": "already_migrated" if valid else "blocked",
                            **({} if valid else {"reason": "已迁移账户的环境、余额或冻结来源不一致"})})
            continue
        entries = list((await db.execute(select(WalletLedger).where(WalletLedger.user_id == user.id)
                      .order_by(WalletLedger.id))).scalars())
        orders = list((await db.execute(select(Order).where(Order.user_id == user.id, Order.team_id.is_(None)))).scalars())
        try:
            sources, allocations, debt = replay_ledger(entries, orders, int(user.balance_fen or 0), int(user.frozen_fen or 0))
            coin = await coin_snapshot(db, user.id, environment, tables)
            plans.append((user, sources, allocations, debt, coin))
            combined = max(0, int(user.balance_fen or 0)) + coin["balance"]
            reports.append({"user_id": user.id, "status": "ready", "source_count": len(sources),
                            "balance_fen": user.balance_fen, "legacy_debt_fen": debt,
                            "coin_remaining": coin["balance"], "coin_source_count": len(coin["lots"]),
                            "merged_balance_fen": max(0, combined - debt),
                            "remaining_debt_fen": max(0, debt - combined)})
        except RuntimeError as error:
            reports.append({"user_id": user.id, "status": "blocked", "reason": str(error)})
    return reports, plans


async def coin_snapshot(db, user_id, environment, tables):
    """保留独立观影币的原区间与消费映射，仅迁入未用余额。"""
    empty = {"balance": 0, "lots": [], "allocations": [], "transactions": {}}
    if "marketplace_coin_wallets" not in tables:
        return empty
    from app.marketplace.app_models import AppleTransaction, CoinAllocation, CoinLot, CoinUnlock, CoinWallet
    from app.marketplace.models import ContentOrder
    wallet = await db.scalar(select(CoinWallet).where(CoinWallet.user_id == user_id, CoinWallet.environment == environment))
    observed = list((await db.execute(select(AppleTransaction).where(AppleTransaction.user_id == user_id,
        AppleTransaction.environment == environment))).scalars())
    observed_unlocks = list((await db.execute(select(CoinUnlock.id).where(CoinUnlock.user_id == user_id,
        CoinUnlock.environment == environment))).scalars())
    if wallet is None:
        if observed or observed_unlocks:
            raise RuntimeError("历史Apple交易缺少原观影币账户，必须先核对")
        return empty
    lots = list((await db.execute(select(CoinLot).where(CoinLot.wallet_id == wallet.id).order_by(CoinLot.id))).scalars())
    transactions = {lot.transaction_id: await db.get(AppleTransaction, lot.transaction_id) for lot in lots}
    for lot in lots:
        validate_coin_source(lot, transactions[lot.transaction_id], user_id, environment)
    from app.marketplace.coin_costs import _available
    actual = sum(ranges.units(_available(lot)) for lot in lots if lot.active)
    if actual != wallet.balance_coins:
        raise RuntimeError("独立观影币余额与来源不一致，禁止合并")
    if {row.id for row in observed} != set(transactions):
        raise RuntimeError("历史Apple交易与观影币来源批次不是一一对应，禁止合并")
    items = []
    unlocks = {}
    for lot in lots:
        partition = list(lot.available_ranges) if lot.active else []
        for allocation in (await db.execute(select(CoinAllocation).where(CoinAllocation.lot_id == lot.id))).scalars():
            validate_coin_allocation(lot, allocation)
            unlock = await db.get(CoinUnlock, allocation.unlock_id)
            if unlock is None:
                raise RuntimeError("历史观影币消费缺少解锁订单")
            if unlock.environment != environment or unlock.user_id != user_id:
                raise RuntimeError("历史观影币消费归属或环境不一致")
            order = await db.get(ContentOrder, unlock.order_id)
            if (order is None or order.user_id != user_id or order.publication_id != unlock.publication_id
                    or order.amount_fen != unlock.amount_fen or order.status != unlock.status
                    or order.pay_type not in ("apple_coin", "platform_balance")
                    or unlock.status not in ("paid", "revoked")):
                raise RuntimeError("历史解锁与内容订单的归属、发布版本、金额或状态不一致")
            unlocks[unlock.id] = unlock
            if unlock.status == "paid":
                if not lot.active:
                    raise RuntimeError("已退款历史来源仍有关联有效解锁，必须先完成旧退款处理")
                try:
                    partition = ranges.normalize(lot.total_coins, partition + allocation.cost_ranges)
                except ValueError as error:
                    raise RuntimeError("历史观影币可用和已消费区间重叠，禁止合并") from error
            items.append((allocation, unlock))
        if lot.active and ranges.units(partition) != lot.total_coins:
            raise RuntimeError("历史观影币来源存在未解释的额度缺口，禁止合并")
    owned_lots = {lot.id for lot in lots}
    if set(observed_unlocks) != set(unlocks):
        raise RuntimeError("历史解锁缺少完整来源分摊，必须先核对")
    for unlock in unlocks.values():
        history = list((await db.execute(select(CoinAllocation).where(CoinAllocation.unlock_id == unlock.id))).scalars())
        if (any(row.lot_id not in owned_lots for row in history)
                or sum(row.coins for row in history) != unlock.coins
                or sum(row.amount_fen for row in history) != unlock.amount_fen):
            raise RuntimeError("历史解锁金额与全部来源分摊不一致，禁止合并")
    return {"balance": actual, "lots": lots, "allocations": items, "transactions": transactions}


def validate_coin_source(lot, transaction, user_id, environment):
    """来源面值和实付必须能回到原渠道凭证，不能只相信批次自己对得上。"""
    if (transaction is None or transaction.user_id != user_id or transaction.environment != environment
            or transaction.currency != "CNY" or transaction.coins != lot.total_coins
            or transaction.amount_fen != lot.total_amount_fen or lot.total_coins <= 0
            or lot.total_amount_fen < 0 or transaction.status not in ("paid", "refunded")
            or lot.active != (transaction.status == "paid")):
        raise RuntimeError("历史观影币来源与Apple交易的归属、环境、额度、实付或状态不一致")
    if not lot.active and (lot.available_ranges or lot.remaining_coins or lot.remaining_amount_fen):
        raise RuntimeError("已退款历史来源仍有可用额度，必须先完成旧退款处理")


def validate_coin_allocation(lot, allocation):
    """分摊额度及现金成本必须由原序号区间精确推导。"""
    try:
        values = ranges.normalize(lot.total_coins, allocation.cost_ranges)
    except (TypeError, ValueError) as error:
        raise RuntimeError("历史观影币消费区间无效，禁止合并") from error
    cash = sum(lot.total_amount_fen * end // lot.total_coins
               - lot.total_amount_fen * start // lot.total_coins for start, end in values)
    if allocation.coins <= 0 or allocation.coins != ranges.units(values) or allocation.amount_fen != cash:
        raise RuntimeError("历史消费的额度、实付分摊与来源区间不一致")


async def apply_plans(db, plans, environment, backup_reference):
    """只执行已整体核对通过的快照，不重新履约任何历史充值。"""
    for user, sources, allocations, debt, coin in plans:
        original_balance = int(user.balance_fen or 0)
        db.add(WalletAccount(user_id=user.id, environment=environment, migration_reference=backup_reference))
        migrated = []
        for source in sources:
            lot = WalletFundingLot(user_id=user.id, environment=environment,
                source_type=source.source_type, source_ref=source.source_ref, total_units=source.total_units,
                total_amount_fen=source.total_amount_fen, available_ranges=source.available_ranges,
                void_ranges=[], active=True, revision=0,
                settlement_status="reconciled" if source.total_amount_fen == 0 else "pending")
            db.add(lot)
            await db.flush()
            migrated.append(lot)
        for values in allocations:
            values = dict(values)
            index = values.pop("source_index")
            db.add(WalletAllocation(user_id=user.id, lot_id=migrated[index].id, **values))
        original_debt = None
        if debt:
            original_debt = WalletDebt(user_id=user.id, cause_type="legacy_overage", cause_ref=backup_reference,
                                       units=debt, active=True)
            db.add(original_debt)
        old_to_new = {}
        for old in coin["lots"]:
            txn = coin["transactions"][old.transaction_id]
            validate_coin_source(old, txn, user.id, environment)
            void = []
            if not old.active:
                consumed = [allocation.cost_ranges for allocation, unlock in coin["allocations"]
                            if allocation.lot_id == old.id and unlock.status == "paid"]
                # 已退款且旧权益已撤销时整批未再消费，可在退款撤销后按原规则恢复。
                if consumed:
                    raise RuntimeError("已退款来源仍有有效解锁，必须先完成旧退款处理")
                void = [[0, old.total_coins]]
            lot = WalletFundingLot(user_id=user.id, environment=environment, source_type="apple_transaction",
                source_ref=f"{environment}:{txn.transaction_id}", total_units=old.total_coins,
                total_amount_fen=old.total_amount_fen, available_ranges=old.available_ranges if old.active else [],
                void_ranges=void, active=old.active, revision=txn.revision,
                settlement_status="reconciled" if txn.settlement_status == "reconciled" else "pending")
            db.add(lot)
            await db.flush()
            old_to_new[old.id] = lot
        for allocation, unlock in coin["allocations"]:
            if unlock.status != "paid":
                continue
            lot = old_to_new[allocation.lot_id]
            db.add(WalletAllocation(user_id=user.id, lot_id=lot.id, business_type="video_unlock",
                business_ref=str(unlock.id), units=allocation.coins, amount_fen=allocation.amount_fen,
                ranges=allocation.cost_ranges, state="consumed"))
        user.balance_fen = max(0, int(user.balance_fen or 0)) + coin["balance"]
        repaid = min(debt, user.balance_fen)
        if repaid:
            # 切换期间统一开关仍关闭，不能调用带运行时门禁的 sweep_debts；
            # 使用同一分摊内核，在单次迁移事务中保留真实偿还来源。
            from .wallet_base import allocate
            await db.flush()
            payments = await allocate(db, user, repaid, "debt_repayment", str(original_debt.id))
            for payment in payments:
                db.add(WalletRepayment(user_id=user.id, debt_id=original_debt.id,
                    allocation_id=payment.id, units=payment.units, active=True))
            user.balance_fen -= repaid
        delta = user.balance_fen - original_balance
        db.add(WalletEvent(user_id=user.id, reference="migration:" + backup_reference, kind="migration",
            delta_fen=delta, frozen_delta_fen=0, balance_after=user.balance_fen, frozen_after=0,
            details={"legacy_balance_fen": original_balance, "coin_remaining": coin["balance"],
                     "legacy_debt_fen": debt, "debt_repaid_fen": repaid, "source_count": len(sources)}))
        db.add(WalletLedger(user_id=user.id, delta_fen=delta, balance_after=user.balance_fen,
            kind="migration", ref_type="unified_wallet", ref_id="opening", note=backup_reference))
    await db.flush()
