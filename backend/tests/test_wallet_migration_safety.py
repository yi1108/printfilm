"""Migration safety regressions; report and failure tests never open a business database."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.models import User, Order, WalletLedger
from app.services.billing import wallet_cutover as cutover, wallet_migration as migration
from app.services.billing.wallet_valuation import order_cash


def entry(index, delta, after, kind="topup", ref="ORDER-7", ref_type="order"):
    return NS(id=index, delta_fen=delta, balance_after=after, kind=kind, ref_id=ref, ref_type=ref_type)


def order(**changes):
    values = dict(id=7, user_id=1, out_trade_no="ORDER-7", status="paid", team_id=None,
                  amount_fen=100, credit_fen=120, pay_type="alipay", payment_environment="Production")
    return NS(**(values | changes))


class ReportDB:
    def __init__(self, balance, entries=(), orders=()):
        self.user = NS(id=1, balance_fen=balance, frozen_fen=0)
        self.rows = {User: [self.user], WalletLedger: list(entries), Order: list(orders)}

    async def connection(self):
        return NS(run_sync=AsyncMock(return_value=set()))

    async def execute(self, statement):
        return NS(scalars=lambda: self.rows[statement.column_descriptions[0]["entity"]])


@pytest.mark.asyncio
async def test_missing_opening_preserves_known_cash_and_requires_fresh_approval():
    db = ReportDB(150, [entry(1, 120, 170), entry(2, -20, 150, "settle", "99", "task_run")], [order()])
    rows, plans = await migration.build_report(db, "Production")
    row = rows[0]
    assert row["opening_balance_fen"] == 50 and row["approval_status"] == "required" and not plans
    approved = {"1": {"fingerprint": row["fingerprint"], "environment": "Production"}}
    rows, plans = await migration.build_report(db, "Production", approved)
    assert rows[0]["approval_status"] == "approved"
    assert [(s.source_type, s.total_amount_fen, s.valuation_pending) for s in plans[0][1]] == [
        ("legacy_opening", 0, True), ("web_order", 100, False)]
    db.rows[Order][0].amount_fen = 99
    rows, plans = await migration.build_report(db, "Production", approved)
    assert rows[0]["approval_status"] == "required" and not plans
    rows, plans = await migration.build_report(db, "Sandbox", approved)
    assert rows[0]["approval_status"] == "required" and not plans


@pytest.mark.asyncio
@pytest.mark.parametrize("entries,orders,balance", [
    ([entry(1, 120, 120)], [order(payment_environment="Sandbox")], 120),
    ([entry(1, 120, 120), entry(2, 120, 240)], [order()], 240),
    ([entry(1, 120, 120), entry(2, -20, 99, "settle", "99", "task_run")], [order()], 99),
    ([entry(1, 120, 120, "unfreeze", "99", "task_run")], [], 120),
    ([entry(1, 120, 120)], [order(credit_fen=110)], 120),
    ([], [order()], 120),
    ([], [order(payment_environment="Sandbox")], 120),
])
async def test_provenance_conflicts_never_become_approvable_openings(entries, orders, balance):
    rows, plans = await migration.build_report(ReportDB(balance, entries, orders), "Production")
    assert rows[0]["status"] == "blocked" and "fingerprint" not in rows[0] and not plans


@pytest.mark.asyncio
async def test_negative_opening_is_debt_not_forgiveness_and_needs_confirmation():
    db = ReportDB(-200)
    rows, plans = await migration.build_report(db, "Production")
    assert rows[0]["merged_balance_fen"] == 0 and rows[0]["remaining_debt_fen"] == 200 and not plans
    approved = {"1": {"fingerprint": rows[0]["fingerprint"], "environment": "Production"}}
    _, plans = await migration.build_report(db, "Production", approved)
    assert plans[0][3] == 200


def test_task_reference_does_not_prove_paid_order_credit():
    missing, _ = migration.payment_findings([entry(1, -10, 0, "settle", "7", "task_run")], [order()])
    assert len(missing) == 1
    _, sandbox = migration.payment_findings([entry(1, 120, 120)], [order(payment_environment="Sandbox")])
    assert len(sandbox) == 1


def funding(**changes):
    values = dict(id=1, user_id=1, source_type="web_order", source_ref="ORDER-7", environment="Production",
        active=True, total_units=120, total_amount_fen=100, available_ranges=[[0, 120]], void_ranges=[], settlement_status="pending")
    return NS(**(values | changes))


@pytest.mark.parametrize("values", [[[0, 60], [50, 110]], [[0, 121]], [[0, 50]], [[False, 120]]])
def test_source_partition_damage_cannot_pass_sum_reconciliation(values):
    with pytest.raises(RuntimeError, match="资金区间"):
        migration.validate_account_structure(1, [funding(available_ranges=values)], [], [], [])


def test_allocation_partition_and_cost_are_both_checked():
    lot = funding(available_ranges=[[60, 120]])
    allocation = NS(id=1, user_id=1, lot_id=1, units=60, amount_fen=50, ranges=[[0, 60]], state="consumed", business_type="ai_task")
    assert migration.validate_account_structure(1, [lot], [allocation], [], []) == 0
    allocation.amount_fen = 49
    with pytest.raises(RuntimeError):
        migration.validate_account_structure(1, [lot], [allocation], [], [])


def test_debt_repayment_must_reference_original_debt_and_source():
    lot = funding(available_ranges=[[60, 120]])
    allocation = NS(id=1, user_id=1, lot_id=1, units=60, amount_fen=50, ranges=[[0, 60]], state="consumed", business_type="debt_repayment", business_ref="2")
    debt = NS(id=2, user_id=1, units=80, active=True)
    payment = NS(id=1, user_id=1, debt_id=2, allocation_id=1, units=60, active=True)
    assert migration.validate_account_structure(1, [lot], [allocation], [debt], [payment]) == 20
    payment.units = 59
    with pytest.raises(RuntimeError):
        migration.validate_account_structure(1, [lot], [allocation], [debt], [payment])


def test_usd_valuation_uses_original_rate_not_nominal_package_price():
    paid = order(amount_fen=10000, credit_fen=10000, payment_currency="USD", payment_amount_minor=1499, payment_exchange_rate="7.2")
    assert order_cash(paid) == 10793
    lot = funding(total_units=10000, total_amount_fen=10793)
    assert migration.source_payment_problems([lot], [paid]) == []
    paid.payment_exchange_rate = None
    lot.total_amount_fen, lot.settlement_status = 0, "pending_fx"
    assert order_cash(paid) is None and migration.source_payment_problems([lot], [paid]) == []
    lot.settlement_status = "reconciled"
    assert migration.source_payment_problems([lot], [paid])


@pytest.mark.asyncio
async def test_approval_requires_current_paused_job_and_exact_fingerprint(monkeypatch):
    db = NS(commit=AsyncMock())
    monkeypatch.setattr(cutover, "exclusive", AsyncMock())
    state = {"paused": True, "phase": "paused", "job_id": "a" * 32}
    monkeypatch.setattr(cutover, "state", AsyncMock(return_value=state))
    monkeypatch.setattr(cutover, "report", AsyncMock(return_value={"accounts": [
        {"user_id": 1, "status": "opening", "environment": "Production", "fingerprint": "b" * 64, "balance_fen": 50}]}))
    save = AsyncMock()
    monkeypatch.setattr(cutover, "save_state", save)
    with pytest.raises(ValueError):
        await cutover.approve(db, 1, "c" * 64, "Production", "a" * 32, 9, "checked")
    save.assert_not_awaited()
    result = await cutover.approve(db, 1, "b" * 64, "Production", "a" * 32, 9, "checked")
    assert result["operator_id"] == 9 and state["history"][-1]["action"] == "approve:1"
    with pytest.raises(ValueError):
        await cutover.approve(db, 1, "b" * 64, "Production", "d" * 32, 9, "checked")


@pytest.mark.asyncio
async def test_backup_journal_survives_rollback_and_retry_keeps_old_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(cutover, "BACKUPS", tmp_path)
    monkeypatch.setattr(cutover.shutil, "which", lambda tool: tool)
    monkeypatch.setattr(cutover, "get_settings", lambda: NS(database_url="postgresql+asyncpg://test:unused@localhost/test"))
    count = 0
    async def command(*args, env=None):
        nonlocal count
        if args[0] == "pg_dump":
            count += 1
            from pathlib import Path
            Path(args[-1]).write_bytes(f"snapshot-{count}".encode())
    monkeypatch.setattr(cutover, "command", command)
    job = "a" * 32
    original = await cutover.backup(job)
    # No database transaction was committed: backup remains discoverable anyway.
    cutover.backup_manifest(job, migration_status="failed")
    assert cutover.backup_records()[0]["sha256"] == original
    second = await cutover.backup(job)
    assert second != original
    records = cutover.backup_records()
    archived = next(item for item in records if item.get("parent_job_id") == job)
    assert cutover.verify_backup(archived["job_id"], original) == original
    assert cutover.verify_backup(job, second) == second
    (tmp_path / (job + ".dump")).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        cutover.verify_backup(job, second)


@pytest.mark.asyncio
async def test_missing_backup_tools_do_not_claim_success(monkeypatch, tmp_path):
    monkeypatch.setattr(cutover, "BACKUPS", tmp_path)
    monkeypatch.setattr(cutover.shutil, "which", lambda tool: None)
    with pytest.raises(ValueError):
        await cutover.backup("a" * 32)
    assert cutover.backup_records()[0]["status"] == "failed"
    assert not cutover.backup_records()[0].get("sha256")


def test_apple_recharge_order_requires_its_own_validated_transaction():
    paid = order(pay_type="apple_iap")
    transaction = NS(recharge_order_id=paid.id, status="paid", user_id=paid.user_id, environment="Production", coins=paid.credit_fen)
    assert migration.payment_findings([], [paid])[0]
    assert migration.payment_findings([], [paid], apple_transactions=[transaction]) == ([], [])
    transaction.user_id = 999
    assert migration.payment_findings([], [paid], apple_transactions=[transaction])[0]


@pytest.mark.asyncio
async def test_lock_recheck_rejects_expired_individual_approval(monkeypatch):
    from test_wallet_cutover import MigrationDB
    db = MigrationDB()
    state = {"paused": True, "phase": "paused", "job_id": "a" * 32, "approvals": {"1": {"fingerprint": "old"}}}
    monkeypatch.setattr(cutover, "exclusive", AsyncMock())
    monkeypatch.setattr(cutover, "state", AsyncMock(return_value=state))
    monkeypatch.setattr(cutover, "report", AsyncMock(return_value={"missing_schema": [], "blocked": 0, "active_tasks": False, "approval_required": 0}))
    monkeypatch.setattr(cutover, "assert_no_active_tasks", AsyncMock())
    monkeypatch.setattr(cutover, "backup", AsyncMock(return_value="digest"))
    monkeypatch.setattr(cutover, "configured_flat", AsyncMock(return_value={"wallet_environment": "Production"}))
    monkeypatch.setattr(cutover, "build_report", AsyncMock(return_value=([{"status": "opening", "approval_status": "required"}], [])))
    apply = AsyncMock()
    monkeypatch.setattr(cutover, "apply_plans", apply)
    with pytest.raises(ValueError, match="锁内重新核对"):
        await cutover.apply(db, state["job_id"], 9, "核对确认")
    apply.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_migration_backup_is_listed_and_downloadable(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from app.api.admin import wallet_migration as api
    monkeypatch.setattr(cutover, "BACKUPS", tmp_path)
    job = "a" * 32
    (tmp_path / (job + ".dump")).write_bytes(b"test archive before failed migration")
    digest = cutover.verify_backup(job)
    cutover.backup_manifest(job, status="ready", sha256=digest)
    db = NS(rollback=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr(cutover, "apply", AsyncMock(side_effect=RuntimeError("来源核对失败")))
    monkeypatch.setattr(cutover, "exclusive", AsyncMock())
    monkeypatch.setattr(cutover, "state", AsyncMock(return_value={"paused": True, "job_id": job}))
    monkeypatch.setattr(cutover, "save_state", AsyncMock())
    with pytest.raises(HTTPException) as failed:
        await api.act("apply", api.Action(reason="人工核对", job_id=job), NS(id=9), db)
    assert failed.value.status_code == 409
    record = cutover.backup_records()[0]
    assert record["sha256"] == digest and record["migration_status"] == "failed"
    response = await api.download(job, NS(id=9), db)
    assert job + ".dump" in response.headers["content-disposition"]
    assert b"".join([chunk async for chunk in response.body_iterator]) == b"test archive before failed migration"
    (tmp_path / (job + ".dump")).write_bytes(b"damaged")
    with pytest.raises(HTTPException) as damaged:
        await api.download(job, NS(id=9), db)
    assert damaged.value.status_code == 409


def test_existing_ledger_duplicate_and_order_alias_collision_are_blocked():
    lines = [entry(1, 120, 120), entry(2, 120, 240)]
    assert migration.payment_evidence_problems(lines, [order()])
    alias = order(id=9, out_trade_no="7")
    assert migration.payment_evidence_problems([], [order(), alias])


@pytest.mark.asyncio
async def test_imported_coin_mirror_does_not_reapply_old_balance_after_refund():
    from app.marketplace.app_models import AppleTransaction, CoinAllocation
    old = NS(id=3, transaction_id=4, total_coins=120, total_amount_fen=100,
             active=True, available_ranges=[[60, 120]])
    txn = NS(id=4, user_id=1, environment="Production", transaction_id="apple-4", status="refunded")
    old_allocation = NS(id=6, lot_id=3, unlock_id=9, coins=60, amount_fen=50, cost_ranges=[[0, 60]])
    current = funding(source_type="apple_transaction", source_ref="Production:apple-4", active=False,
                      available_ranges=[], void_ranges=[[60, 120]])
    allocation = NS(lot_id=1, business_type="video_unlock", business_ref="9", units=60,
                    amount_fen=50, ranges=[[0, 60]], state="returned")
    class MirrorDB:
        async def scalar(self, _statement):
            return NS(id=2, balance_coins=60)
        async def execute(self, statement):
            values = [old_allocation] if statement.column_descriptions[0]["entity"] is CoinAllocation else [old]
            return NS(scalars=lambda: values)
        async def get(self, model, _key, **_kwargs):
            assert model is AppleTransaction
            return txn
    await migration.validate_retired_coin_mirror(MirrorDB(), 1, "Production", [current], [allocation], {"marketplace_coin_wallets"})
    current.total_amount_fen = 99
    with pytest.raises(RuntimeError):
        await migration.validate_retired_coin_mirror(MirrorDB(), 1, "Production", [current], [allocation], {"marketplace_coin_wallets"})


@pytest.mark.asyncio
async def test_old_cli_cannot_bypass_confirmation_and_cutover():
    from scripts.prepare_unified_wallet_schema import run
    with pytest.raises(RuntimeError, match="旧命令行资金写入已停用"):
        await run(NS(apply=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("rate,expected", [("7.2", 10793), (None, 0)])
async def test_normal_topup_and_migration_use_same_payment_valuation(monkeypatch, rate, expected):
    from app.services.billing import settlement, wallet
    paid = order(payment_currency="usd", payment_amount_minor=1499, payment_exchange_rate=rate)
    lot = NS(settlement_status="pending" if rate else "reconciled")
    credit = AsyncMock(return_value=lot)
    monkeypatch.setattr(wallet, "enabled", lambda: True)
    monkeypatch.setattr(wallet, "credit", credit)
    db = NS(scalar=AsyncMock(return_value=paid))
    await settlement.credit_topup(db, NS(id=1), 120, ref_type="order", ref_id="ORDER-7")
    assert credit.await_args.kwargs["amount_fen"] == expected
    assert lot.settlement_status == ("pending" if rate else "pending_fx")
