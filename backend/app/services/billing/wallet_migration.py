"""历史资金回放：只有来源、余额和冻结均可核对时才生成切换快照。"""
from dataclasses import asdict, dataclass, field
import hashlib
import json

from sqlalchemy import or_, select

from app.models import Order, User, WalletLedger
from app.models_wallet import WalletAccount, WalletAllocation, WalletDebt, WalletEvent, WalletFundingLot, WalletRepayment
from . import wallet_ranges as ranges
from .wallet_valuation import order_cash


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
    valuation_pending: bool = False



def historical_opening(entries, balance):
    """Only missing opening history is approvable; gaps inside a ledger are not."""
    if not entries:
        return int(balance)
    opening = int(entries[0].balance_after) - int(entries[0].delta_fen)
    running = opening
    for entry in entries:
        running += int(entry.delta_fen)
        if running != int(entry.balance_after):
            raise RuntimeError(f"流水 {entry.id} 前后余额不连续，必须人工核对")
    if running != int(balance):
        raise RuntimeError("末笔流水与当前余额不一致，必须人工核对")
    return opening


def report_fingerprint(environment, user, entries, orders, sources, allocations, debt, coin):
    def fields(obj, keys):
        return {key: getattr(obj, key, None) for key in keys.split()}
    data = {"version": 2, "environment": environment,
            "user": fields(user, "id balance_fen frozen_fen"),
            "entries": [fields(e, "id delta_fen balance_after kind ref_type ref_id") for e in entries],
            "orders": [fields(o, "id user_id team_id out_trade_no status pay_type payment_environment credit_fen amount_fen payment_currency payment_amount_minor payment_exchange_rate") for o in orders],
            "sources": [asdict(source) for source in sources], "allocations": allocations, "debt": debt,
            "coin_balance": coin["balance"],
            "coin_lots": [fields(lot, "id transaction_id total_coins total_amount_fen active available_ranges remaining_coins remaining_amount_fen") for lot in coin["lots"]],
            "coin_allocations": [[fields(a, "id lot_id coins amount_fen cost_ranges"), fields(u, "id status order_id coins amount_fen")] for a, u in coin["allocations"]],
            "coin_transactions": [fields(t, "id transaction_id user_id environment currency status coins amount_fen revision settlement_status") for t in coin["transactions"].values()]}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()


def replay_ledger(entries, orders, expected_balance, expected_frozen, *, opening_balance=0):
    """按历史先后回放 FIFO；无法辨明的入账或返还立即阻止切换。"""
    if expected_frozen:
        raise RuntimeError("仍有冻结额度，必须先排空并结算 AI 任务")
    sources, allocations, held, deficit = [], [], {}, max(0, -opening_balance)
    if opening_balance > 0:
        sources.append(Source("legacy_opening", "opening", opening_balance, 0, [[0, opening_balance]], True))
    seen_orders = set()
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
                if order is None:
                    raise RuntimeError(f"流水 {entry.id} 的充值没有对应订单")
                if getattr(order, "pay_type", "alipay") not in ("alipay", "wxpay", "stripe"):
                    raise RuntimeError("充值渠道不能映射为Web资金来源")
                if entry.ref_type != "order":
                    raise RuntimeError(f"流水 {entry.id} 的充值引用类型不是订单")
                if order.out_trade_no in seen_orders:
                    raise RuntimeError(f"订单 {order.out_trade_no} 重复入账，禁止迁移")
                seen_orders.add(order.out_trade_no)
                if order.team_id is not None:
                    raise RuntimeError(f"流水 {entry.id} 对应团队订单 {order.out_trade_no}，不能记入个人来源")
                if getattr(order, "payment_environment", None) not in (None, "Production"):
                    raise RuntimeError(f"流水 {entry.id} 的订单 {order.out_trade_no} 属于 {order.payment_environment}，不能并入正式余额")
                if order.status != "paid":
                    raise RuntimeError(f"流水 {entry.id} 的订单 {order.out_trade_no} 状态是 {order.status}，不是已支付")
                if order.credit_fen != delta:
                    raise RuntimeError(f"流水 {entry.id} 到账 {delta}，订单 {order.out_trade_no} 到账 {order.credit_fen}")
                cash = order_cash(order)
                source = Source("web_order", order.out_trade_no, delta, cash or 0, [[0, delta]], cash is None)
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


def _active_available(lots):
    """累计仍有效来源的可用额度；区间损坏时整户视为不可核对。"""
    total = 0
    for lot in lots:
        if not lot.active:
            continue
        try:
            available = ranges.normalize(lot.total_units, lot.available_ranges or [])
            ranges.normalize(lot.total_units, available + getattr(lot, "void_ranges", []))
            total += ranges.units(available)
        except (TypeError, ValueError):
            return 0, True
    return total, False


def kept_balance(original, proposed):
    """迁移后的可用积分不得低于原来的正余额。"""
    floor = max(0, int(original or 0))
    if int(proposed) < floor:
        raise RuntimeError(f"迁移后余额 {int(proposed)} 低于当前可用 {floor}")
    return int(proposed)


def ledger_findings(entries, balance):
    """从完整流水解释余额从哪来；用户明细只展示最新几条，不能代替这里。"""
    if not entries:
        return [f"没有钱包流水，账户余额 {balance}"] if balance else []
    first = entries[0]
    opening = int(first.balance_after) - int(first.delta_fen)
    net = sum(int(entry.delta_fen) for entry in entries)
    credits = [entry for entry in entries if int(entry.delta_fen) > 0 and entry.kind in ("grant", "topup")]
    parts = [f"流水 {len(entries)} 笔，最早一笔前余额 {opening}，流水净额 {net}"]
    if opening > 0 and not credits:
        parts.append(f"最早一笔扣费前余额是 {opening}，没有赠送或充值流水")
    if net != balance:
        parts.append(f"流水净额 {net} 与账户余额 {balance} 相差 {balance - net}")
    task_count = sum(1 for entry in entries if str(entry.ref_id).startswith("task:"))
    if task_count:
        parts.append(f"任务冻结或结算 {task_count} 笔")
    return parts


def payment_findings(entries, orders, lots=(), apple_transactions=()):
    """已支付订单必须能在流水或来源批次中找到，Sandbox 不并入正式余额。"""
    refs = {str(entry.ref_id) for entry in entries
            if entry.kind == "topup" and entry.ref_type == "order" and int(entry.delta_fen) > 0}
    refs.update(str(lot.source_ref) for lot in lots
                if lot.source_type == "web_order" and getattr(lot, "source_ref", None))
    missing, sandbox = [], []
    for order in orders:
        if order.status != "paid" or order.team_id is not None:
            continue
        text = f"{order.out_trade_no} 实付 {order.amount_fen} 到账 {order.credit_fen}"
        if getattr(order, "payment_environment", None) not in (None, "Production"):
            sandbox.append(text)
        elif getattr(order, "pay_type", None) == "apple_iap":
            matching = [txn for txn in apple_transactions
                        if getattr(txn, "recharge_order_id", None) == order.id and txn.status == "paid"
                        and txn.user_id == getattr(order, "user_id", None)
                        and txn.environment == "Production" and txn.coins == order.credit_fen]
            if len(matching) != 1:
                missing.append(text)
        elif order.out_trade_no not in refs and str(order.id) not in refs:
            missing.append(text)
    return missing, sandbox


def payment_evidence_problems(entries, orders):
    problems, by_ref, seen = [], {}, set()
    for order in orders:
        for ref in (str(order.id), order.out_trade_no):
            if ref in by_ref and by_ref[ref].id != order.id:
                problems.append("订单编号存在歧义，禁止按字符串猜测匹配")
            by_ref[ref] = order
    for entry in entries:
        if entry.kind != "topup" or entry.ref_type != "order":
            continue
        order = by_ref.get(str(entry.ref_id))
        if (not order or order.status != "paid" or order.team_id is not None
                or getattr(order, "payment_environment", None) not in (None, "Production")
                or getattr(order, "pay_type", "alipay") not in ("alipay", "wxpay", "stripe")
                or int(entry.delta_fen) <= 0 or order.credit_fen != int(entry.delta_fen)):
            problems.append(f"充值流水 {entry.id} 的订单归属、渠道、环境、状态或额度不一致")
        elif order.id in seen:
            problems.append(f"订单 {order.out_trade_no} 重复入账")
        else:
            seen.add(order.id)
    return problems


def source_payment_problems(lots, orders):
    """来源批次上的实付必须和正式个人订单一致，赠送不能被记成实付。"""
    by_ref = {}
    for order in orders:
        by_ref[order.out_trade_no] = order
        by_ref[str(order.id)] = order
    problems = []
    seen_orders = set()
    for lot in lots:
        if lot.source_type == "web_order":
            order = by_ref.get(str(lot.source_ref))
            if order is not None and order.out_trade_no in seen_orders:
                problems.append(f"订单 {order.out_trade_no} 存在重复来源")
            if order is not None:
                seen_orders.add(order.out_trade_no)
                try:
                    cash = order_cash(order)
                except RuntimeError as error:
                    problems.append(str(error))
                    continue
            if order is None:
                problems.append(f"来源订单 {lot.source_ref} 不存在")
            elif (order.status != "paid" or order.team_id is not None
                  or getattr(order, "pay_type", "alipay") not in ("alipay", "wxpay", "stripe")
                  or getattr(order, "payment_environment", None) not in (None, "Production")):
                problems.append(f"来源订单 {lot.source_ref} 不是已支付的正式个人订单")
            elif int(order.credit_fen) != int(lot.total_units) or (cash is not None and cash != int(lot.total_amount_fen)):
                problems.append(f"来源订单 {order.out_trade_no} 额度或历史实付成本不一致")
            elif cash is None and lot.settlement_status != "pending_fx":
                problems.append(f"来源订单 {order.out_trade_no} 缺少汇率，必须标记待核算")
        elif lot.source_type in ("signup_grant", "admin_grant") and int(lot.total_amount_fen) != 0:
            problems.append(f"{lot.source_type} 记了实付 {lot.total_amount_fen}")
        elif lot.source_type == "legacy_opening" and getattr(lot, "settlement_status", "") != "pending_fx":
            problems.append("历史结余被标为已核算，缺少实付依据，须人工复核")
    return problems


def existing_account_row(user, marker, lots, reserved, environment, entries=(), orders=(), apple_transactions=()):
    """已有统一钱包账户时带回当前积分，并把环境、来源、流水和订单差额写进核对原因。"""
    balance = int(user.balance_fen or 0)
    frozen = int(user.frozen_fen or 0)
    available, unreadable = _active_available(lots)
    reserved_units = sum(int(item.units) for item in reserved)
    missing, sandbox = payment_findings(entries, orders, lots, apple_transactions)
    lot_problems = source_payment_problems(lots, orders) + payment_evidence_problems(entries, orders)
    valid = (not unreadable and marker.environment == environment
             and all(lot.environment == environment for lot in lots)
             and available == balance and reserved_units == frozen
             and not missing and not lot_problems)
    row = {"user_id": user.id, "status": "already_migrated" if valid else "blocked",
           "balance_fen": balance, "merged_balance_fen": balance}
    if valid and not sandbox:
        return row
    gaps = []
    if marker.environment != environment:
        gaps.append(f"账户环境 {marker.environment}，当前环境 {environment}")
    foreign = sorted({lot.environment for lot in lots if lot.environment != environment})
    if foreign:
        gaps.append(f"来源环境 {'、'.join(foreign)}，当前环境 {environment}")
    if unreadable:
        gaps.append("来源区间无法读取")
    elif available != balance:
        gaps.append(f"来源可用 {available}，账户余额 {balance}")
    if reserved_units != frozen:
        gaps.append(f"预留冻结 {reserved_units}，账户冻结 {frozen}")
    if lots:
        shown = [f"{lot.source_type} {lot.total_units}（实付 {lot.total_amount_fen}，环境 {lot.environment}"
                 f"{'' if lot.active else '，已停用'}）" for lot in lots[:5]]
        text = "、".join(shown)
        if len(lots) > len(shown):
            text += f"，另有 {len(lots) - len(shown)} 笔"
        gaps.append(f"已有来源：{text}")
    else:
        gaps.append("没有资金来源批次")
    reference = marker.migration_reference or ""
    if reference == "new-account":
        gaps.append("账户是注册时创建的")
    elif reference.startswith("admin:"):
        gaps.append("账户由历史迁移写入")
    gaps.extend(ledger_findings(entries, balance))
    if missing:
        gaps.append("已支付订单未入账：" + "、".join(missing[:5]))
    gaps.extend(lot_problems[:5])
    if sandbox:
        gaps.append("Sandbox 已支付订单不并入正式余额：" + "、".join(sandbox[:3]))
    row["reason"] = "已有统一钱包账户。" + "；".join(gap for gap in gaps if gap)
    return row


def guard_merged(row, missing, sandbox):
    """正余额不能被迁少；未入账的正式订单不能当成已经核对。"""
    floor = max(0, int(row.get("balance_fen") or 0))
    merged = int(row.get("merged_balance_fen") or 0)
    reasons = []
    if merged < floor:
        reasons.append(f"迁移后积分 {merged} 低于当前可用 {floor}")
        row["merged_balance_fen"] = floor
    if missing:
        reasons.append("已支付订单未入账：" + "、".join(missing[:5]))
    if sandbox:
        reasons.append("Sandbox 已支付订单不并入正式余额：" + "、".join(sandbox[:3]))
    if merged < floor or missing:
        row["status"] = "blocked"
        row["reason"] = "；".join(reasons)
        return False
    if reasons:
        row["reason"] = "；".join(reasons)
    return True


def validate_account_structure(user_id, lots, allocations, debts, repayments):
    """Validate partitions and debt edges, not merely their aggregate sums."""
    by_lot = {lot.id: lot for lot in lots}
    by_allocation = {item.id: item for item in allocations}
    by_debt = {item.id: item for item in debts}
    try:
        for lot in lots:
            if lot.user_id != user_id or lot.total_units <= 0 or lot.total_amount_fen < 0:
                raise ValueError("来源归属或金额无效")
            partition = ranges.normalize(lot.total_units, list(lot.available_ranges) + list(lot.void_ranges))
            if not lot.active and lot.available_ranges:
                raise ValueError("失效来源仍有可用额度")
            if lot.active and lot.void_ranges:
                raise ValueError("有效来源仍有作废区间")
            for item in allocations:
                if item.lot_id != lot.id:
                    continue
                values = ranges.normalize(lot.total_units, item.ranges)
                if (item.units != ranges.units(values) or item.units <= 0
                        or item.amount_fen != ranges.cost(lot, values) or item.user_id != user_id
                        or item.state not in ("reserved", "consumed", "returned")):
                    raise ValueError("消费分摊的归属、额度或实付成本不一致")
                if not lot.active and item.state == "consumed" and item.business_type == "ai_task":
                    matching = [debt for debt in debts if debt.active and debt.cause_type == "source_refund"
                                and debt.cause_ref == str(item.id) and debt.origin_lot_id == lot.id
                                and debt.units == item.units]
                    if len(matching) != 1:
                        raise ValueError("退款后的实际AI消费缺少原始追偿关系")
                if not lot.active and item.state == "consumed" and item.business_type == "video_unlock":
                    raise ValueError("退款来源仍有关联未撤销的视频消费")
                if item.state != "returned":
                    partition = ranges.normalize(lot.total_units, partition + values)
            if ranges.units(partition) != lot.total_units:
                raise ValueError("来源存在未解释的额度缺口")
        if any(item.lot_id not in by_lot for item in allocations):
            raise ValueError("消费缺少本账户来源")
        paid = {}
        seen = set()
        for item in repayments:
            debt, allocation = by_debt.get(item.debt_id), by_allocation.get(item.allocation_id)
            if (not debt or not allocation or item.user_id != user_id or item.units <= 0
                    or allocation.business_type != "debt_repayment" or allocation.units != item.units
                    or allocation.business_ref != str(debt.id) or item.allocation_id in seen):
                raise ValueError("欠费偿还关系无效或重复")
            seen.add(item.allocation_id)
            if item.active:
                if allocation.state != "consumed" or not by_lot[allocation.lot_id].active or not debt.active:
                    raise ValueError("有效偿还引用了失效来源或欠费")
                paid[debt.id] = paid.get(debt.id, 0) + item.units
            elif allocation.state != "returned":
                raise ValueError("已撤销偿还未返还原分摊")
        if any(item.business_type == "debt_repayment" and item.id not in seen for item in allocations):
            raise ValueError("偿还消费缺少原始欠费关系")
        for debt in debts:
            if getattr(debt, "origin_lot_id", None) is not None:
                if debt.origin_lot_id not in by_lot:
                    raise ValueError("欠费原因引用了其他账户来源")
                if debt.active and getattr(debt, "cause_type", None) == "source_refund" and by_lot[debt.origin_lot_id].active:
                    raise ValueError("有效来源仍关联未撤销的退款欠费")
            if debt.user_id != user_id or debt.units <= 0 or paid.get(debt.id, 0) > debt.units:
                raise ValueError("欠费金额或归属无效")
        return sum(debt.units - paid.get(debt.id, 0) for debt in debts if debt.active)
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        raise RuntimeError("资金区间或欠费关系损坏：" + str(exc)) from exc


async def validate_retired_coin_mirror(db, user_id, environment, lots, allocations, tables):
    """An imported legacy wallet is a read-only snapshot, not a second balance.

    Original transaction/unlock states may legitimately change after migration.
    Only immutable source/allocation correspondence is checked against this mirror.
    """
    if "marketplace_coin_wallets" not in tables:
        return
    from app.marketplace.app_models import AppleTransaction, CoinAllocation, CoinLot, CoinWallet
    old_wallet = await db.scalar(select(CoinWallet).where(CoinWallet.user_id == user_id,
        CoinWallet.environment == environment).execution_options(populate_existing=True))
    if not old_wallet:
        return
    old_lots = list((await db.execute(select(CoinLot).where(CoinLot.wallet_id == old_wallet.id)
                                     .execution_options(populate_existing=True))).scalars())
    by_ref = {lot.source_ref: lot for lot in lots if lot.source_type == "apple_transaction"}
    if old_wallet.balance_coins and not old_lots:
        raise RuntimeError("历史观影币仍有未解释余额")
    for old in old_lots:
        txn = await db.get(AppleTransaction, old.transaction_id, populate_existing=True)
        current = by_ref.get(f"{environment}:{txn.transaction_id}") if txn else None
        if (not txn or txn.user_id != user_id or txn.environment != environment or not current
                or current.total_units != old.total_coins or current.total_amount_fen != old.total_amount_fen):
            raise RuntimeError("历史观影币来源尚未迁入或原始金额不一致")
        for old_allocation in (await db.execute(select(CoinAllocation).where(CoinAllocation.lot_id == old.id)
                                                .execution_options(populate_existing=True))).scalars():
            validate_coin_allocation(old, old_allocation)
            if not any(item.lot_id == current.id and item.business_type == "video_unlock"
                       and item.business_ref == str(old_allocation.unlock_id)
                       and item.units == old_allocation.coins and item.amount_fen == old_allocation.amount_fen
                       and item.ranges == old_allocation.cost_ranges for item in allocations):
                # Old revoked unlocks were intentionally not imported.
                from app.marketplace.app_models import CoinUnlock
                unlock = await db.get(CoinUnlock, old_allocation.unlock_id, populate_existing=True)
                if not unlock or unlock.status != "revoked":
                    raise RuntimeError("历史观影币消费缺少迁移分摊关系")


async def build_report(db, environment, approvals=None):
    """只读报告不建表、不创建账户、不修改旧钱包或余额。"""
    from sqlalchemy import inspect
    connection = await db.connection()
    tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names(
        schema=(sync.get_execution_options().get("schema_translate_map") or {}).get(None))))
    existing_accounts = {row.user_id: row for row in (await db.execute(select(WalletAccount).execution_options(populate_existing=True))).scalars()} if "wallet_accounts" in tables else {}
    reports, plans = [], []
    for user in (await db.execute(select(User).order_by(User.id).execution_options(populate_existing=True))).scalars():
        entries = list((await db.execute(select(WalletLedger).where(WalletLedger.user_id == user.id)
                      .order_by(WalletLedger.id).execution_options(populate_existing=True))).scalars())
        orders = list((await db.execute(select(Order).where(Order.user_id == user.id).order_by(Order.id).execution_options(populate_existing=True))).scalars())
        if user.id in existing_accounts:
            marker = existing_accounts[user.id]
            lots = list((await db.execute(select(WalletFundingLot).where(WalletFundingLot.user_id == user.id).execution_options(populate_existing=True))).scalars())
            all_allocations = list((await db.execute(select(WalletAllocation).where(WalletAllocation.user_id == user.id).execution_options(populate_existing=True))).scalars())
            reserved = [item for item in all_allocations if item.state == "reserved"]
            debts = list((await db.execute(select(WalletDebt).where(WalletDebt.user_id == user.id).execution_options(populate_existing=True))).scalars())
            repayments = list((await db.execute(select(WalletRepayment).where(WalletRepayment.user_id == user.id).execution_options(populate_existing=True))).scalars())
            apple_transactions = []
            if "marketplace_apple_transactions" in tables:
                from app.marketplace.app_models import AppleTransaction
                apple_transactions = list((await db.execute(select(AppleTransaction).where(
                    AppleTransaction.user_id == user.id, AppleTransaction.environment == environment)
                    .execution_options(populate_existing=True))).scalars())
            funded_refs = {lot.source_ref for lot in lots if lot.source_type == "apple_transaction"}
            funded_transactions = [txn for txn in apple_transactions if f"{environment}:{txn.transaction_id}" in funded_refs]
            row = existing_account_row(user, marker, lots, reserved, environment, entries, orders, funded_transactions)
            row.update(frozen_fen=int(user.frozen_fen or 0), environment=environment,
                       legacy_debt_fen=sum(debt.units for debt in debts if debt.active),
                       pending_source_count=sum(lot.settlement_status == "pending_fx" for lot in lots),
                       pending_sources=[{"source_type": lot.source_type, "source_ref": lot.source_ref,
                                         "units": lot.total_units, "valuation_status": "pending"}
                                        for lot in lots if lot.settlement_status == "pending_fx"])
            try:
                if len(funded_transactions) != len(apple_transactions):
                    raise RuntimeError("已有账户仍有Apple交易缺少统一来源，必须人工核对")
                if any(lot.source_type == "apple_transaction" for lot in lots):
                    from app.marketplace.app_models import AppleTransaction
                    if "marketplace_apple_transactions" not in tables:
                        raise RuntimeError("Apple来源缺少原渠道交易表")
                    for lot in lots:
                        if lot.source_type != "apple_transaction":
                            continue
                        ref_environment, separator, transaction_id = lot.source_ref.partition(":")
                        txn = await db.scalar(select(AppleTransaction).where(
                            AppleTransaction.transaction_id == transaction_id,
                            AppleTransaction.environment == ref_environment).execution_options(populate_existing=True))
                        if (not separator or ref_environment != environment or not txn or txn.user_id != user.id
                                or txn.coins != lot.total_units or txn.amount_fen != lot.total_amount_fen
                                or txn.status not in ("paid", "refunded") or lot.active != (txn.status == "paid")):
                            raise RuntimeError("Apple来源与原交易归属、环境、额度、实付或状态不一致")
                row["remaining_debt_fen"] = validate_account_structure(user.id, lots, all_allocations, debts, repayments)
            except RuntimeError as error:
                row.update(status="blocked", reason=(row.get("reason", "") + str(error)))
            try:
                await validate_retired_coin_mirror(db, user.id, environment, lots, all_allocations, tables)
            except (RuntimeError, ValueError, TypeError) as error:
                row.update(status="blocked", reason=row.get("reason", "") + str(error))
            reports.append(row)
            continue
        balance, frozen = int(user.balance_fen or 0), int(user.frozen_fen or 0)
        base = {"user_id": user.id, "balance_fen": balance, "frozen_fen": frozen,
                "environment": environment, "legacy_debt_fen": max(0, -balance)}
        try:
            evidence_problems = payment_evidence_problems(entries, orders)
            if evidence_problems:
                raise RuntimeError("；".join(evidence_problems))
            opening = historical_opening(entries, balance)
            sources, allocations, debt = replay_ledger(entries, orders, balance, frozen, opening_balance=opening)
            coin = await coin_snapshot(db, user.id, environment, tables)
            combined = max(0, balance) + coin["balance"]
            merged = max(0, combined - debt)
            missing, sandbox = payment_findings(entries, orders, apple_transactions=coin["transactions"].values())
            if opening and sandbox:
                raise RuntimeError("缺失期初历史且存在 Sandbox 已支付交易，无法证明正式余额来源，禁止确认")
            # Referenced sandbox money is never an approvable historical opening.
            referenced = {str(e.ref_id) for e in entries if e.kind == "topup"}
            if any(getattr(o, "payment_environment", None) not in (None, "Production")
                   and (str(o.id) in referenced or o.out_trade_no in referenced) for o in orders):
                raise RuntimeError("Sandbox 充值已进入旧流水，禁止转为正式历史结余")
            row = {**base, "status": "ready", "source_count": len(sources),
                   "legacy_debt_fen": debt, "coin_remaining": coin["balance"],
                   "coin_source_count": len(coin["lots"]), "merged_balance_fen": merged,
                   "remaining_debt_fen": max(0, debt - combined),
                   "pending_source_count": sum(s.valuation_pending for s in sources),
                   "pending_sources": [{"source_type": source.source_type, "source_ref": source.source_ref,
                                        "units": source.total_units, "valuation_status": "pending"}
                                       for source in sources if source.valuation_pending],
                   "opening_balance_fen": opening}
            if not guard_merged(row, missing, sandbox):
                reports.append(row)
                continue
            fingerprint = report_fingerprint(environment, user, entries, orders, sources, allocations, debt, coin)
            row["fingerprint"] = fingerprint
            if opening:
                approval = (approvals or {}).get(str(user.id), {})
                approved = approval.get("fingerprint") == fingerprint and approval.get("environment") == environment
                row.update(status="opening", approval_status="approved" if approved else "required",
                           reason=f"缺失期初历史 {opening} 积分须逐户确认；保留已知充值及消费，未知实付保持待核算，负数转明确欠费。"
                                  + "；".join(ledger_findings(entries, balance)))
                if not approved:
                    reports.append(row)
                    continue
            plans.append((user, sources, allocations, debt, coin))
            reports.append(row)
        except (RuntimeError, ValueError, TypeError) as error:
            reports.append({**base, "status": "blocked", "reason": str(error)})
    return reports, plans


async def coin_snapshot(db, user_id, environment, tables):
    """保留独立观影币的原区间与消费映射，仅迁入未用余额。"""
    empty = {"balance": 0, "lots": [], "allocations": [], "transactions": {}}
    if "marketplace_coin_wallets" not in tables:
        return empty
    from app.marketplace.app_models import AppleTransaction, CoinAllocation, CoinLot, CoinUnlock, CoinWallet
    from app.marketplace.models import ContentOrder
    wallet = await db.scalar(select(CoinWallet).where(CoinWallet.user_id == user_id, CoinWallet.environment == environment).execution_options(populate_existing=True))
    observed = list((await db.execute(select(AppleTransaction).where(AppleTransaction.user_id == user_id,
        AppleTransaction.environment == environment).order_by(AppleTransaction.id).execution_options(populate_existing=True))).scalars())
    observed_unlocks = list((await db.execute(select(CoinUnlock.id).where(CoinUnlock.user_id == user_id,
        CoinUnlock.environment == environment))).scalars())
    if wallet is None:
        if observed or observed_unlocks:
            raise RuntimeError("历史Apple交易缺少原观影币账户，必须先核对")
        return empty
    lots = list((await db.execute(select(CoinLot).where(CoinLot.wallet_id == wallet.id).order_by(CoinLot.id).execution_options(populate_existing=True))).scalars())
    transactions = {lot.transaction_id: await db.get(AppleTransaction, lot.transaction_id, populate_existing=True) for lot in lots}
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
        for allocation in (await db.execute(select(CoinAllocation).where(CoinAllocation.lot_id == lot.id).order_by(CoinAllocation.id).execution_options(populate_existing=True))).scalars():
            validate_coin_allocation(lot, allocation)
            unlock = await db.get(CoinUnlock, allocation.unlock_id, populate_existing=True)
            if unlock is None:
                raise RuntimeError("历史观影币消费缺少解锁订单")
            if unlock.environment != environment or unlock.user_id != user_id:
                raise RuntimeError("历史观影币消费归属或环境不一致")
            order = await db.get(ContentOrder, unlock.order_id, populate_existing=True)
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
                settlement_status=("pending_fx" if source.valuation_pending else
                                   "reconciled" if source.total_amount_fen == 0 else "pending"))
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
        user.balance_fen = kept_balance(original_balance, user.balance_fen)
        delta = user.balance_fen - original_balance
        db.add(WalletEvent(user_id=user.id, reference="migration:" + backup_reference, kind="migration",
            delta_fen=delta, frozen_delta_fen=0, balance_after=user.balance_fen, frozen_after=0,
            details={"legacy_balance_fen": original_balance, "coin_remaining": coin["balance"],
                     "legacy_debt_fen": debt, "debt_repaid_fen": repaid, "source_count": len(sources)}))
        db.add(WalletLedger(user_id=user.id, delta_fen=delta, balance_after=user.balance_fen,
            kind="migration", ref_type="unified_wallet", ref_id="opening", note=backup_reference))
    await db.flush()
