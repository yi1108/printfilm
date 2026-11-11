"""Original-balance cutover: explicit gifts, immutable history, no duplicate credit."""
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.models import WalletLedger
from app.models_wallet import WalletAccount, WalletEvent, WalletFundingLot, WalletDebt, WalletMigrationResolution
from app.services.billing import wallet_balance_migration as balance, wallet_cutover as cutover


def snapshot(value=500, environment=None):
    return {"user": {"id": 1, "balance_fen": value, "frozen_fen": 0},
        "accounts": [{"id": 1, "user_id": 1, "environment": environment, "migration_reference": "new-account"}] if environment else [],
        "lots": [], "allocations": [], "debts": [], "repayments": [], "notices": [],
        "entries": [], "orders": [], "apple_transactions": [], "coin_wallets": [], "events": [], "task_settlements": []}


def prepare(data):
    return balance.prepare(NS(**data["user"]), [], [], data)


@pytest.mark.parametrize("value", [10500, 9500, 500, 86, 20, 38, 0])
def test_sandbox_balance_is_replaced_by_platform_gift_not_paid_cash(value):
    data = snapshot(value, "Sandbox")
    before = deepcopy(data)
    preview, sources, allocations = prepare(data)
    assert data == before
    assert preview["merged_balance_fen"] == value and preview["platform_grant_fen"] == value
    assert preview["pending_units"] == 0 and not allocations
    assert all(source.source_type == "admin_grant" and source.total_amount_fen == 0 for source in sources)
    assert sum(source.total_units for source in sources) == value


@pytest.mark.parametrize("value", [2448, 500, -1124])
def test_unexplained_balance_remains_pending_and_negative_is_explicit_debt(value):
    data = snapshot(value)
    preview, sources, _ = prepare(data)
    assert preview["merged_balance_fen"] == max(0, value)
    assert preview["remaining_debt_fen"] == max(0, -value)
    assert preview["platform_grant_fen"] == 0 and preview["pending_units"] == max(0, value)
    assert all(source.valuation_pending for source in sources)


def test_legacy_apple_order_environment_uses_receipt_link_not_wallet_guess():
    data = snapshot(500, "Sandbox")
    order = NS(id=9, user_id=1, team_id=None, status="paid", pay_type="apple_iap",
               payment_environment="Production", trade_no="receipt-9")
    data["apple_transactions"] = [dict(id=1, user_id=1, transaction_id="receipt-9",
        environment="Sandbox", status="paid", coins=500, amount_fen=500)]
    before = deepcopy(data)
    preview, _, _ = balance.prepare(NS(**data["user"]), [], [order], data)
    assert preview["platform_grant_fen"] == 500 and data == before
    data["apple_transactions"].append(dict(data["apple_transactions"][0], id=2, environment="Production"))
    with pytest.raises(ValueError, match="多个交易凭证"):
        balance.prepare(NS(**data["user"]), [], [order], data)


def test_actual_freeze_debt_and_refund_work_cannot_be_bypassed():
    for field, value in (("frozen_fen", 1),):
        data = snapshot()
        data["user"][field] = value
        with pytest.raises(ValueError):
            prepare(data)
    data = snapshot()
    data["debts"] = [{"active": True, "units": 1}]
    with pytest.raises(ValueError):
        prepare(data)
    data = snapshot()
    data["notices"] = [{"status": "pending"}]
    with pytest.raises(ValueError):
        prepare(data)


def test_fingerprint_changes_with_balance_or_old_financial_record():
    data = snapshot(500, "Sandbox")
    first = prepare(data)[0]["fingerprint"]
    data["entries"] = [{"id": 1, "delta_fen": -1}]
    assert prepare(data)[0]["fingerprint"] != first
    data = snapshot(499, "Sandbox")
    assert prepare(data)[0]["fingerprint"] != first


def production_lot():
    return dict(id=2, user_id=1, environment="Production", source_type="web_order", source_ref="WEB-1",
        total_units=120, total_amount_fen=100, available_ranges=[[0, 120]], void_ranges=[], active=True,
        revision=0, settlement_status="pending")


def test_real_paid_funding_is_preserved_with_original_cost():
    data = snapshot(150)
    data["lots"] = [production_lot()]
    paid = NS(id=1, out_trade_no="WEB-1", status="paid", team_id=None, user_id=1,
        amount_fen=100, credit_fen=120, payment_environment="Production", pay_type="alipay")
    preview, sources, _ = balance.prepare(NS(**data["user"]), [], [paid], data)
    assert preview["preserved_units"] == 120 and preview["pending_units"] == 30
    assert preview["archived_lot_ids"] == [] and data["lots"][0]["total_amount_fen"] == 100
    assert sources[0].valuation_pending and sources[0].total_units == 30
    data["lots"][0]["available_ranges"] = [[0, 121]]
    with pytest.raises(ValueError, match="真实付款来源损坏"):
        balance.prepare(NS(**data["user"]), [], [paid], data)


def test_missing_real_payment_is_not_relabelled_as_free_gift():
    data = snapshot(500, "Sandbox")
    paid = NS(id=1, out_trade_no="WEB-1", status="paid", team_id=None, user_id=1,
        amount_fen=100, credit_fen=120, payment_environment="Production", pay_type="alipay")
    with pytest.raises(ValueError):
        balance.prepare(NS(**data["user"]), [], [paid], data)


@pytest.mark.parametrize("value", [2448, -1124])
def test_broken_balance_chain_preserves_paid_evidence_as_pending(value):
    data = snapshot(value)
    paid = NS(id=7, out_trade_no="WEB-7", status="paid", team_id=None, user_id=1,
        amount_fen=100, credit_fen=120, payment_environment="Production", pay_type="alipay")
    entries = [NS(id=1, kind="topup", ref_type="order", ref_id="WEB-7", delta_fen=120, balance_after=120),
               NS(id=2, kind="consume", ref_type="task", ref_id="old", delta_fen=-1, balance_after=value)]
    before = deepcopy(entries)
    preview, sources, allocations = balance.prepare(NS(**data["user"]), entries, [paid], data)
    assert preview["merged_balance_fen"] == max(0, value)
    assert preview["remaining_debt_fen"] == max(0, -value)
    assert preview["pending_order_ids"] == [7] and preview["preserved_order_ids"] == []
    assert preview["platform_grant_fen"] == 0 and preview["pending_units"] == max(0, value)
    assert all(source.valuation_pending and source.source_type == "legacy_opening" for source in sources)
    assert not allocations and vars(entries[0]) == vars(before[0])
    entries[0].delta_fen = 121
    with pytest.raises(ValueError, match="不一致"):
        balance.prepare(NS(**data["user"]), entries, [paid], data)
    entries[0].delta_fen = 120
    entries.insert(1, NS(**vars(entries[0])))
    with pytest.raises(ValueError, match="重复入账"):
        balance.prepare(NS(**data["user"]), entries, [paid], data)


@pytest.mark.asyncio
@pytest.mark.parametrize("value,environment", [(9500, "Sandbox"), (2448, None), (-1124, None)])
async def test_apply_appends_baseline_and_gift_without_double_balance(value, environment):
    data = snapshot(value, environment)
    user = NS(**data["user"])
    preview, sources, allocations = prepare(data)
    marker = NS(environment=environment, migration_reference="old") if environment else None
    added = []
    class DB:
        def add(self, item):
            added.append(item)
        async def scalar(self, stmt):
            return marker if stmt.column_descriptions[0]["entity"] is WalletAccount else None
        async def flush(self):
            for index, item in enumerate(added, 1):
                if getattr(item, "id", None) is None:
                    item.id = index
    plan = balance.BalancePlan(user, data, preview, sources, allocations, {"operator_id": 9, "reason": "核对后按原积分保留"})
    await balance.apply(DB(), plan, "test-backup-sha256")
    assert user.balance_fen == max(0, value)
    entries = [item for item in added if isinstance(item, WalletLedger)]
    assert sum(item.delta_fen for item in entries) == max(0, value) - value
    if environment:
        assert marker.environment == "Production"
        assert next(item for item in entries if item.kind == "grant").delta_fen == value
        assert entries[-1].balance_after == value
    if value < 0:
        assert next(item for item in added if isinstance(item, WalletDebt)).units == -value
    resolution = next(item for item in added if isinstance(item, WalletMigrationResolution))
    assert resolution.snapshot["user"]["balance_fen"] == value
    assert resolution.operator_id == 9
    assert resolution.snapshot["accounts"] == data["accounts"]


@pytest.mark.asyncio
async def test_repeated_apply_cannot_grant_again():
    data = snapshot(500, "Sandbox")
    preview, sources, allocations = prepare(data)
    db = NS(scalar=AsyncMock(return_value=1))
    with pytest.raises(ValueError, match="不能重复补赠"):
        await balance.apply(db, balance.BalancePlan(NS(**data["user"]), data, preview, sources, allocations, {}), "backup")


@pytest.mark.asyncio
async def test_batch_confirmation_is_atomic_and_requires_gift_acknowledgement(monkeypatch):
    job = "a" * 32
    state = {"paused": True, "phase": "paused", "job_id": job}
    preview = {"eligible": True, "fingerprint": "b" * 64, "platform_grant_fen": 500}
    monkeypatch.setattr(cutover, "exclusive", AsyncMock())
    monkeypatch.setattr(cutover, "state", AsyncMock(return_value=state))
    monkeypatch.setattr(cutover, "report", AsyncMock(return_value={"missing_schema": [], "active_tasks": False,
        "accounts": [{"user_id": 1, "status": "blocked", "balance_migration": preview}]}))
    save = AsyncMock()
    monkeypatch.setattr(cutover, "save_state", save)
    db = NS(commit=AsyncMock())
    chosen = [{"user_id": 1, "fingerprint": "b" * 64}]
    with pytest.raises(ValueError, match="正式赠额"):
        await cutover.approve_balances(db, chosen, job, 9, "核对确认", False)
    with pytest.raises(ValueError, match="预览已变化"):
        await cutover.approve_balances(db, chosen + [{"user_id": 2, "fingerprint": "c" * 64}], job, 9, "核对确认", True)
    save.assert_not_awaited()
    assert "approvals" not in state
    await cutover.approve_balances(db, chosen, job, 9, "核对确认", True)
    assert state["approvals"]["1"]["mode"] == "original_balance"
    assert state["history"][-1]["action"] == "approve_original_balances"
    db.commit.assert_awaited_once()



@pytest.fixture
def sqlite_wallet(monkeypatch):
    # Real SQL/ORM round trip without PostgreSQL; advisory locks and concurrent
    # cutover remain covered separately by the PostgreSQL integration suite.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.config import get_settings
    from app.models import User, Order
    from app.models_teams import Team
    from app.models_wallet import WalletBase
    from app.services.billing.wallet_schema import register_models
    register_models()
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    WalletLedger.__table__.create(engine)
    Team.__table__.create(engine)
    Order.__table__.create(engine)
    WalletBase.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    class DB:
        def add(self, row): session.add(row)
        async def scalar(self, stmt): return session.scalar(stmt)
        async def execute(self, stmt): return session.execute(stmt)
        async def get(self, model, key, **kwargs): return session.get(model, key, **kwargs)
        async def flush(self): session.flush()
        async def connection(self):
            class Connection:
                async def run_sync(self, callback): return callback(session.connection())
            return Connection()
    monkeypatch.setattr(get_settings(), "wallet_environment", "Production")
    try:
        yield NS(db=DB(), session=session)
    finally:
        session.close()
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("value,old_environment", [(20, "Sandbox"), (2448, None), (-1124, None)])
async def test_real_orm_baseline_roundtrip_preserves_history_and_reconciles(sqlite_wallet, value, old_environment):
    from sqlalchemy import select
    from app.models import User
    from app.models_wallet import WalletAllocation
    from app.services.billing.wallet_migration import build_report, apply_plans
    from app.services.billing.wallet_base import allocate
    ctx = sqlite_wallet
    user = User(email="baseline@test.invalid", hashed_password="unused", balance_fen=value, frozen_fen=0)
    ctx.session.add(user)
    ctx.session.flush()
    old_lot = None
    if old_environment:
        ctx.session.add(WalletAccount(user_id=user.id, environment=old_environment, migration_reference="new-account"))
        old_lot = WalletFundingLot(user_id=user.id, environment="Sandbox", source_type="signup_grant", source_ref="old",
            total_units=500, total_amount_fen=0, available_ranges=[[480, 500]], void_ranges=[], active=True,
            revision=0, settlement_status="reconciled")
        ctx.session.add(old_lot)
        ctx.session.flush()
        ctx.session.add(WalletAllocation(user_id=user.id, lot_id=old_lot.id, business_type="ai_task", business_ref="old-task",
            units=480, amount_fen=0, ranges=[[0, 480]], state="consumed"))
    old_entry = WalletLedger(user_id=user.id, delta_fen=-1, balance_after=value + 1,
        kind="freeze", ref_type="legacy_unknown", ref_id="old-unknown")
    ctx.session.add(old_entry)
    ctx.session.commit()
    old_entry_id = old_entry.id
    reports, plans = await build_report(ctx.db, "Production")
    assert reports[0]["status"] == "blocked" and not plans
    preview = reports[0]["balance_migration"]
    assert preview["eligible"]
    approvals = {str(user.id): {"mode": "original_balance", "fingerprint": preview["fingerprint"],
        "environment": "Production", "operator_id": 9, "reason": "核对后按原积分保留", "accept_platform_grant": True}}
    reports, plans = await build_report(ctx.db, "Production", approvals)
    assert reports[0]["status"] == "balance_approved" and len(plans) == 1
    await apply_plans(ctx.db, plans, "Production", "backup-test")
    ctx.session.commit()
    reports, repeated = await build_report(ctx.db, "Production", approvals)
    assert reports[0]["status"] == "already_migrated" and not repeated
    old_entry = ctx.session.get(WalletLedger, old_entry_id)
    assert old_entry.delta_fen == -1 and old_entry.balance_after == value + 1
    assert user.balance_fen == max(0, value)
    if old_environment:
        assert old_lot.environment == "Sandbox" and old_lot.active and old_lot.available_ranges == [[480, 500]]
        items = await allocate(ctx.db, user, 5, "admin_adjustment", "after-baseline")
        user.balance_fen -= 5
        ctx.session.flush()
        assert all(item.lot_id != old_lot.id for item in items)
        assert user.balance_fen == 15
    if value < 0:
        assert ctx.session.scalar(select(WalletDebt.units).where(WalletDebt.user_id == user.id)) == -value


@pytest.mark.asyncio
async def test_real_orm_failed_baseline_rolls_back_every_write(sqlite_wallet):
    from sqlalchemy import select
    from app.models import User
    from app.services.billing.wallet_migration import build_report, apply_plans
    ctx = sqlite_wallet
    user = User(email="rollback@test.invalid", hashed_password="unused", balance_fen=86, frozen_fen=0)
    ctx.session.add(user)
    ctx.session.flush()
    user_id = user.id
    ctx.session.add(WalletAccount(user_id=user_id, environment="Sandbox", migration_reference="old"))
    ctx.session.commit()
    reports, _ = await build_report(ctx.db, "Production")
    fingerprint = reports[0]["balance_migration"]["fingerprint"]
    _, plans = await build_report(ctx.db, "Production", {str(user_id): {"mode": "original_balance", "fingerprint": fingerprint,
        "environment": "Production", "operator_id": 9, "reason": "测试回滚", "accept_platform_grant": True}})
    await apply_plans(ctx.db, plans, "Production", "rollback-backup")
    ctx.session.rollback()
    assert ctx.session.scalar(select(WalletAccount.environment).where(WalletAccount.user_id == user_id)) == "Sandbox"
    assert ctx.session.scalar(select(User.balance_fen).where(User.id == user_id)) == 86
    assert ctx.session.scalar(select(WalletMigrationResolution.id)) is None
    assert ctx.session.scalar(select(WalletFundingLot.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [2448, -1124])
async def test_paid_pending_baseline_roundtrip(sqlite_wallet, value):
    from sqlalchemy import select
    from app.models import User, Order
    from app.services.billing.wallet_migration import build_report, apply_plans
    ctx = sqlite_wallet
    user = User(email="paid-pending@test.invalid", hashed_password="unused", balance_fen=value, frozen_fen=0)
    ctx.session.add(user)
    ctx.session.flush()
    order = Order(user_id=user.id, out_trade_no="OLD-PAID", sku_id="old", pay_type="alipay",
        amount_fen=100, credit_fen=120, status="paid", payment_environment="Production")
    ctx.session.add(order)
    ctx.session.add_all([
        WalletLedger(user_id=user.id, kind="topup", ref_type="order", ref_id="OLD-PAID", delta_fen=120, balance_after=120),
        WalletLedger(user_id=user.id, kind="consume", ref_type="task", ref_id="old", delta_fen=-1, balance_after=value)])
    ctx.session.commit()
    reports, _ = await build_report(ctx.db, "Production")
    preview = reports[0]["balance_migration"]
    assert preview["eligible"] and preview["pending_order_ids"] == [order.id]
    approval = {str(user.id): dict(mode="original_balance", fingerprint=preview["fingerprint"],
        environment="Production", operator_id=9, reason="保留原积分，成本待核算", accept_platform_grant=False)}
    _, plans = await build_report(ctx.db, "Production", approval)
    await apply_plans(ctx.db, plans, "Production", "pending-backup")
    ctx.session.commit()
    reports, plans = await build_report(ctx.db, "Production", approval)
    assert reports[0]["status"] == "already_migrated" and not plans
    assert user.balance_fen == max(0, value) and order.status == "paid" and order.amount_fen == 100
    assert ctx.session.scalar(select(WalletLedger.delta_fen).where(WalletLedger.ref_id == "OLD-PAID")) == 120
    if value > 0:
        lot = ctx.session.scalar(select(WalletFundingLot))
        assert lot.source_type == "legacy_opening" and lot.settlement_status == "pending_fx"
        assert lot.available_ranges == [[0, value]]
