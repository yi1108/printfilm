"""历史资金回放和独立观影币切换，全部隔离到随机测试 schema。"""
from datetime import UTC, datetime
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import func, select, text

from app.models import Order, User, WalletLedger
from app.models_wallet import WalletAccount, WalletAllocation, WalletDebt, WalletFundingLot, WalletRepayment
from app.services.billing.wallet_migration import (apply_plans, assert_no_active_tasks, build_report,
                                                  coin_snapshot, replay_ledger, validate_coin_allocation, validate_coin_source)
from test_unified_wallet_core import wallet_ctx  # noqa: F401


def line(index, delta, kind, ref="", ref_type="task_run"):
    """纯回放输入保持原流水字段，不调用充值或任务执行器。"""
    return SimpleNamespace(id=index, delta_fen=delta, kind=kind, ref_id=ref, ref_type=ref_type)


def paid_order():
    """Web 标价与到账赠额不同，回放须使用订单真实金额。"""
    return SimpleNamespace(id=1, out_trade_no="WEB-1", status="paid", credit_fen=120, amount_fen=100, team_id=None)


def test_replay_frozen_refund_and_settle_retains_original_cash_cost():
    entries = [line(1, 120, "topup", "WEB-1", "order"), line(2, -100, "freeze", "10"),
               line(3, 30, "unfreeze", "10"), line(4, 0, "settle", "10")]
    sources, allocations, debt = replay_ledger(entries, [paid_order()], 50, 0)
    assert debt == 0 and sources[0].available_ranges == [[70, 120]]
    assert sum(item["units"] for item in allocations if item["state"] == "consumed") == 70
    assert sum(item["amount_fen"] for item in allocations if item["state"] == "consumed") == 58


def test_replay_overage_only_charges_extra_once():
    entries = [line(1, 120, "topup", "1", "order"), line(2, -100, "freeze", "10"),
               line(3, -30, "settle", "10"), line(4, 0, "settle", "10")]
    sources, allocations, debt = replay_ledger(entries, [paid_order()], -10, 0)
    assert sources[0].available_ranges == [] and debt == 10
    assert sum(item["units"] for item in allocations) == 120


def test_replay_negative_balance_repaid_by_later_grant():
    entries = [line(1, -100, "settle", "1"), line(2, 60, "grant", "operator", "admin")]
    sources, allocations, debt = replay_ledger(entries, [], -40, 0)
    assert debt == 40 and sources[0].available_ranges == []
    assert allocations[0]["business_type"] == "legacy_debt_repayment"
    assert allocations[0]["amount_fen"] == 0


def test_replay_negative_balance_repaid_by_unfreeze():
    entries = [line(1, 120, "topup", "WEB-1", "order"), line(2, -120, "freeze", "1"),
               line(3, -50, "settle", "2"), line(4, 120, "unfreeze", "1"), line(5, 0, "settle", "1")]
    sources, _, debt = replay_ledger(entries, [paid_order()], 70, 0)
    assert debt == 0 and sources[0].available_ranges == [[50, 120]]


@pytest.mark.parametrize("entries,balance,frozen", [([], 10, 0), ([], 0, 10),
    ([line(1, 10, "unknown", "x")], 10, 0), ([line(1, 10, "unfreeze", "missing")], 10, 0)])
def test_unexplained_balance_or_unknown_refund_stops_migration(entries, balance, frozen):
    with pytest.raises(RuntimeError):
        replay_ledger(entries, [], balance, frozen)


async def prepare_legacy_tables(ctx):
    """只建立随机 schema 中回放查询需要的旧表。"""
    from app.models_teams import Team
    connection = await ctx.db.connection()
    await connection.run_sync(lambda sync: Team.__table__.create(sync, checkfirst=True))
    await connection.run_sync(lambda sync: Order.__table__.create(sync, checkfirst=True))


@pytest.mark.asyncio
async def test_report_is_readonly_and_repeated_migration_is_noop(wallet_ctx):
    ctx = wallet_ctx
    await prepare_legacy_tables(ctx)
    legacy = User(email=f"{uuid.uuid4().hex}@test.invalid", hashed_password="unused", balance_fen=100, frozen_fen=0)
    ctx.db.add(legacy)
    await ctx.db.flush()
    ctx.db.add(WalletLedger(user_id=legacy.id, delta_fen=100, balance_after=100, kind="grant", ref_type="signup", ref_id="signup"))
    await ctx.db.flush()
    reports, plans = await build_report(ctx.db, "Production")
    assert any(row["user_id"] == legacy.id and row["status"] == "ready" for row in reports)
    assert not await ctx.db.scalar(select(WalletAccount.id).where(WalletAccount.user_id == legacy.id))
    await apply_plans(ctx.db, plans, "Production", "test-backup-sha256")
    reports, second = await build_report(ctx.db, "Production")
    assert second == [] and all(row["status"] == "already_migrated" for row in reports)
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == 1


@pytest.mark.asyncio
async def test_active_tasks_block_cutover(wallet_ctx):
    ctx = wallet_ctx
    connection = await ctx.db.connection()
    schema = connection.sync_connection.get_execution_options()["schema_translate_map"][None]
    await ctx.db.execute(text(f'CREATE TABLE "{schema}".task_runs (id INTEGER PRIMARY KEY, status VARCHAR(32), billing_status VARCHAR(16))'))
    # 编译的 ORM 查询使用 schema_translate_map；原始 SQL 明确写随机测试 schema。
    await ctx.db.execute(text(f'INSERT INTO "{schema}".task_runs VALUES (1, \'running\', \'none\')'))
    with pytest.raises(RuntimeError):
        await assert_no_active_tasks(ctx.db)
    await ctx.db.execute(text(f'UPDATE "{schema}".task_runs SET status=\'succeeded\''))
    await assert_no_active_tasks(ctx.db)
    await ctx.db.execute(text(f'UPDATE "{schema}".task_runs SET billing_status=\'frozen\''))
    with pytest.raises(RuntimeError):
        await assert_no_active_tasks(ctx.db)


async def retired_coin_history(ctx, *, legacy_balance=0, total=7, cash=10, spent=3):
    """建立有原渠道交易和内容订单的旧币来源，支持明确欠费回放。"""
    await prepare_legacy_tables(ctx)
    from app.marketplace.app_models import AppleTransaction, CoinAllocation, CoinLot, CoinUnlock, CoinWallet
    from app.marketplace.app_schema import register_models
    from app.marketplace.models import Asset, ContentOrder, MarketBase, Publication, Work
    register_models()
    connection = await ctx.db.connection()
    await connection.run_sync(MarketBase.metadata.create_all)
    legacy = User(email=f"{uuid.uuid4().hex}@test.invalid", hashed_password="unused", balance_fen=legacy_balance, frozen_fen=0)
    ctx.db.add(legacy)
    await ctx.db.flush()
    if legacy_balance < 0:
        ctx.db.add(WalletLedger(user_id=legacy.id, delta_fen=legacy_balance, balance_after=legacy_balance,
                                kind="settle", ref_type="task_run", ref_id="legacy-ai"))
    asset = Asset(owner_id=ctx.user.id, kind="video", filename="x.mp4", content_type="video/mp4", size_bytes=1,
                  object_key="marketplace/test/migration.mp4", status="ready")
    ctx.db.add(asset)
    await ctx.db.flush()
    work = Work(owner_id=ctx.user.id, title="migration", asset_id=asset.id, price_fen=0)
    ctx.db.add(work)
    await ctx.db.flush()
    publication = Publication(content_type="work", content_id=work.id, version=1, owner_id=ctx.user.id,
                              asset_id=asset.id, sale_type="platform_unlock", share_bps=2000)
    ctx.db.add(publication)
    await ctx.db.flush()
    consumed_cash = cash * spent // total
    order = ContentOrder(out_trade_no="OLD-CONTENT", user_id=legacy.id, publication_id=publication.id,
                         amount_fen=consumed_cash, pay_type="apple_coin", status="paid", idempotency_key="old")
    ctx.db.add(order)
    old_wallet = CoinWallet(user_id=legacy.id, environment="Production", balance_coins=total-spent)
    transaction = AppleTransaction(user_id=legacy.id, environment="Production", transaction_id="old-apple",
        original_transaction_id="old-apple", product_id="old.product", app_account_token=str(uuid.uuid4()),
        coins=total, amount_fen=cash, status="paid", revision=0, signed_at=datetime.now(UTC))
    ctx.db.add_all([old_wallet, transaction])
    await ctx.db.flush()
    lot = CoinLot(wallet_id=old_wallet.id, transaction_id=transaction.id, total_coins=total, total_amount_fen=cash,
                  remaining_coins=total-spent, remaining_amount_fen=cash-consumed_cash,
                  available_ranges=[[spent, total]] if spent < total else [], active=True)
    unlock = CoinUnlock(user_id=legacy.id, environment="Production", order_id=order.id,
        publication_id=publication.id, coins=spent, amount_fen=consumed_cash, status="paid", idempotency_key="old-unlock")
    ctx.db.add_all([lot, unlock])
    await ctx.db.flush()
    allocation = CoinAllocation(unlock_id=unlock.id, lot_id=lot.id, coins=spent, amount_fen=consumed_cash,
                                cost_ranges=[[0, spent]])
    ctx.db.add(allocation)
    await ctx.db.flush()
    return SimpleNamespace(user=legacy, wallet=old_wallet, lot=lot, transaction=transaction,
                           allocation=allocation, unlock=unlock, order=order)


@pytest.mark.asyncio
async def test_retired_coin_wallet_migrates_only_unused_and_preserves_ranges(wallet_ctx):
    ctx = wallet_ctx
    old = await retired_coin_history(ctx)
    reports, plans = await build_report(ctx.db, "Production")
    assert all(row["status"] != "blocked" for row in reports)
    await apply_plans(ctx.db, plans, "Production", "backup-proof")
    assert old.user.balance_fen == 4 and old.wallet.balance_coins == 4
    source = await ctx.db.scalar(select(WalletFundingLot).where(WalletFundingLot.user_id == old.user.id))
    assert source.available_ranges == [[3, 7]] and source.total_amount_fen == 10
    allocation = await ctx.db.scalar(select(WalletAllocation).where(WalletAllocation.user_id == old.user.id))
    assert allocation.ranges == [[0, 3]] and allocation.amount_fen == 4 and allocation.business_ref == str(old.unlock.id)
    _, repeated = await build_report(ctx.db, "Production")
    assert repeated == [] and old.user.balance_fen == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("target,attribute,value", [
    ("transaction", "amount_fen", 9), ("transaction", "coins", 8),
    ("transaction", "user_id", -1), ("transaction", "status", "refunded"),
    ("allocation", "amount_fen", 5), ("allocation", "coins", 4),
    ("order", "amount_fen", 5), ("order", "user_id", -1), ("order", "status", "revoked"),
    ("unlock", "coins", 4),
])
async def test_inconsistent_old_payment_evidence_blocks_readonly_report(wallet_ctx, target, attribute, value):
    """每种不一致都必须在报告阶段阻断，不能等到写入时才报错。"""
    ctx = wallet_ctx
    old = await retired_coin_history(ctx)
    setattr(getattr(old, target), attribute, value)
    await ctx.db.flush()
    reports, plans = await build_report(ctx.db, "Production")
    assert any(row["user_id"] == old.user.id and row["status"] == "blocked" for row in reports)
    assert not any(plan[0].id == old.user.id for plan in plans)
    assert not await ctx.db.scalar(select(WalletAccount.id).where(WalletAccount.user_id == old.user.id))
    assert old.user.balance_fen == 0 and old.wallet.balance_coins == 4


@pytest.mark.asyncio
async def test_refunded_old_source_with_paid_unlock_blocks_before_apply(wallet_ctx):
    """报告不能把旧退款尚未撤权的批次标成可以迁移。"""
    ctx = wallet_ctx
    old = await retired_coin_history(ctx)
    old.transaction.status = "refunded"
    old.lot.active = False
    old.lot.available_ranges = []
    old.lot.remaining_coins = old.lot.remaining_amount_fen = old.wallet.balance_coins = 0
    await ctx.db.flush()
    reports, plans = await build_report(ctx.db, "Production")
    assert any(row["user_id"] == old.user.id and row["status"] == "blocked" for row in reports)
    assert not any(plan[0].id == old.user.id for plan in plans)


@pytest.mark.asyncio
@pytest.mark.parametrize("debt,expected_balance,expected_debt", [(40, 60, 0), (140, 0, 40)])
async def test_cutover_coin_balance_immediately_repays_legacy_debt_and_refund_reopens_once(
        wallet_ctx, debt, expected_balance, expected_debt):
    """合并即可用余额先补欠费，偿还来源之后退款可准确重新打开原欠费。"""
    ctx = wallet_ctx
    old = await retired_coin_history(ctx, legacy_balance=-debt, total=110, cash=100, spent=10)
    reports, plans = await build_report(ctx.db, "Production")
    report = next(row for row in reports if row["user_id"] == old.user.id)
    assert report["merged_balance_fen"] == expected_balance
    assert report["remaining_debt_fen"] == expected_debt
    await apply_plans(ctx.db, plans, "Production", "backup-proof")
    from app.services.billing import wallet
    from app.services.billing.wallet_base import debt_units
    assert old.user.balance_fen == expected_balance
    assert await debt_units(ctx.db, old.user.id) == expected_debt
    repayments = list((await ctx.db.execute(select(WalletRepayment).where(WalletRepayment.user_id == old.user.id))).scalars())
    assert sum(row.units for row in repayments) == min(100, debt)
    original = await ctx.db.scalar(select(WalletDebt).where(WalletDebt.user_id == old.user.id))
    assert original.units == debt
    # 核对时旧开关可关闭；正常运行退款使用统一服务，不能重复造一笔欠费。
    await wallet.revoke_source(ctx.db, old.user.id, "apple_transaction", "Production:old-apple")
    assert await debt_units(ctx.db, old.user.id) == debt
    assert await ctx.db.scalar(select(func.count()).select_from(WalletDebt).where(WalletDebt.user_id == old.user.id)) == 1
    assert old.user.balance_fen == 0


@pytest.mark.asyncio
async def test_untraceable_ledger_migrates_current_balance_without_cash_source(wallet_ctx):
    """对不上的历史流水按当前余额收口：正数无实付来源，负数记欠费，冻结仍阻断。"""
    ctx = wallet_ctx
    await prepare_legacy_tables(ctx)
    positive = User(email=f"{uuid.uuid4().hex}@test.invalid", hashed_password="unused", balance_fen=500, frozen_fen=0)
    negative = User(email=f"{uuid.uuid4().hex}@test.invalid", hashed_password="unused", balance_fen=-200, frozen_fen=0)
    frozen = User(email=f"{uuid.uuid4().hex}@test.invalid", hashed_password="unused", balance_fen=100, frozen_fen=40)
    ctx.db.add_all([positive, negative, frozen])
    await ctx.db.flush()
    ctx.db.add(WalletLedger(user_id=positive.id, delta_fen=500, balance_after=500, kind="unfreeze", ref_type="task_run", ref_id="missing"))
    reports, plans = await build_report(ctx.db, "Production")
    assert next(row for row in reports if row["user_id"] == positive.id)["status"] == "opening"
    assert next(row for row in reports if row["user_id"] == negative.id)["merged_balance_fen"] == 0
    assert next(row for row in reports if row["user_id"] == frozen.id)["status"] == "blocked"
    await apply_plans(ctx.db, plans, "Production", "backup-proof")
    source = await ctx.db.scalar(select(WalletFundingLot).where(WalletFundingLot.user_id == positive.id))
    assert source.source_type == "legacy_opening" and source.total_units == 500 and source.total_amount_fen == 0
    assert positive.balance_fen == 500 and negative.balance_fen == 0
    debt = await ctx.db.scalar(select(WalletDebt).where(WalletDebt.user_id == negative.id))
    assert debt.units == 200
    assert not await ctx.db.scalar(select(WalletAccount.id).where(WalletAccount.user_id == frozen.id))
