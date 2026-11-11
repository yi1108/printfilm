"""统一资金核心真实 PostgreSQL 测试，随机测试 schema 隔离业务库。"""
import asyncio
from types import SimpleNamespace
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import User, WalletLedger
from app.models_wallet import WalletAllocation, WalletBase, WalletDebt, WalletFundingLot, WalletTaskNotice, WalletTaskSettlement
from app.services.billing import wallet
from app.services.billing.wallet_base import debt_units
from conftest import _ensure_test_database, _resolve_test_database_url


@pytest_asyncio.fixture
async def wallet_ctx(monkeypatch):
    """独立连接允许检查真实账户行锁；测试绝不修改生产 schema。"""
    from app.marketplace.app_settings import get_app_settings
    monkeypatch.setattr(get_settings(), "unified_wallet_enabled", True)
    monkeypatch.setattr(get_app_settings(), "apple_environment", "Production")
    async def no_pending(*_args, **_kwargs):
        """纯资金测试不引入 AI 任务表；预留保护由集成测试覆盖。"""
        return 0
    monkeypatch.setattr("app.services.billing.settlement.pending_task_commitment_fen", no_pending)
    url, name = _resolve_test_database_url(get_settings().database_url)
    await _ensure_test_database(url, name)
    schema = "wallet_core_" + uuid.uuid4().hex
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with scoped.begin() as connection:
            await connection.run_sync(lambda sync: User.__table__.create(sync))
            await connection.run_sync(lambda sync: WalletLedger.__table__.create(sync))
            await connection.run_sync(WalletBase.metadata.create_all)
        factory = async_sessionmaker(scoped, expire_on_commit=False)
        async with factory() as db:
            user = User(email=f"{uuid.uuid4().hex}@test.invalid", hashed_password="unused", balance_fen=0, frozen_fen=0)
            db.add(user)
            await db.flush()
            await wallet.initialize_account(db, user)
            await db.commit()
            yield SimpleNamespace(db=db, user=user, factory=factory)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def add(ctx, ref, units=100, cash=None, kind="apple_transaction"):
    """测试替身只代表验签之后的服务器事实，不调用外部支付。"""
    return await wallet.credit(ctx.db, ctx.user.id, units, source_type=kind, source_ref=ref,
                               amount_fen=units if cash is None else cash)


@pytest.mark.asyncio
async def test_existing_account_prevents_environment_switch(wallet_ctx):
    from app.services.billing.wallet_environment import validate_environment_change
    with pytest.raises(ValueError, match="已有统一钱包账户"):
        await validate_environment_change(wallet_ctx.db)


def test_wallet_environment_is_independent_of_apple(monkeypatch):
    from app.marketplace.app_settings import get_app_settings
    from app.services.billing.wallet_base import environment
    monkeypatch.setattr(get_settings(), "wallet_environment", "Production")
    monkeypatch.setattr(get_app_settings(), "apple_environment", "Sandbox")
    assert environment() == "Production"
    with pytest.raises(wallet.WalletError) as caught:
        environment("Sandbox")
    assert caught.value.code == "WALLET_ENVIRONMENT_MISMATCH"
    monkeypatch.setattr(get_settings(), "wallet_environment", "Sandbox")
    assert environment("Sandbox") == "Sandbox"


async def refund(ctx, ref):
    """视频撤权在市场测试覆盖；纯 AI 来源退款后直接收回欠费。"""
    result = await wallet.revoke_source(ctx.db, ctx.user.id, "apple_transaction", ref)
    await wallet.sweep_debts(ctx.db, ctx.user.id)
    return result


async def spend_ai(ctx, units, task_id=1):
    """真实冻结和结算，不直接改余额。"""
    await wallet.reserve_task(ctx.db, ctx.user.id, task_id, units)
    await wallet.settle_task(ctx.db, ctx.user.id, task_id, units)


@pytest.mark.asyncio
async def test_cross_source_real_cash_rounding_and_gifts(wallet_ctx):
    ctx = wallet_ctx
    await add(ctx, "package", 7, 10)
    await add(ctx, "grant", 3, 0, "signup_grant")
    costs = []
    for index in range(10):
        items = await wallet.consume(ctx.db, ctx.user.id, 1, business_type="test", business_ref=str(index))
        costs.append(sum(item.amount_fen for item in items))
    assert sum(costs) == 10 and costs[-3:] == [0, 0, 0]
    assert (await wallet.snapshot(ctx.db, ctx.user.id))["balance_fen"] == 0


@pytest.mark.asyncio
async def test_ai_overage_is_debt_not_negative_balance(wallet_ctx):
    ctx = wallet_ctx
    await add(ctx, "a", 40)
    await wallet.reserve_task(ctx.db, ctx.user.id, 1, 30)
    result = await wallet.settle_task(ctx.db, ctx.user.id, 1, 60)
    assert result == {"charged": 60, "refunded": 0, "debt_fen": 20}
    state = await wallet.snapshot(ctx.db, ctx.user.id)
    assert (state["balance_fen"], state["frozen_fen"], state["debt_fen"]) == (0, 0, 20)
    assert (await wallet.settle_task(ctx.db, ctx.user.id, 1, 60))["debt_fen"] == 20


@pytest.mark.asyncio
async def test_corrupt_task_reserve_cannot_consume_another_tasks_frozen_funds(wallet_ctx):
    """账户总冻结充足也不能让一条损坏任务结算掉另一任务的预扣。"""
    ctx = wallet_ctx
    await add(ctx, "funding", 100)
    await wallet.reserve_task(ctx.db, ctx.user.id, 1, 30)
    await wallet.reserve_task(ctx.db, ctx.user.id, 2, 50)
    first = await ctx.db.scalar(select(WalletTaskSettlement).where(WalletTaskSettlement.task_id == 1))
    first.reserved_units = 40
    await ctx.db.flush()
    with pytest.raises(wallet.WalletError) as error:
        await wallet.settle_task(ctx.db, ctx.user.id, 1, 30)
    assert error.value.code == "WALLET_TASK_FUNDING_INCONSISTENT"
    assert ctx.user.frozen_fen == 80 and ctx.user.balance_fen == 20


@pytest.mark.asyncio
async def test_dispatch_requires_a_real_unsettled_reservation_even_when_estimate_zero(wallet_ctx):
    """零估价也须有真实门闩，已结算任务不能借旧TaskRun状态继续调用。"""
    ctx = wallet_ctx
    with pytest.raises(wallet.WalletError) as missing:
        await wallet.validate_task_funding(ctx.db, ctx.user.id, 123)
    assert missing.value.code == "WALLET_TASK_RESERVATION_REQUIRED"
    await wallet.reserve_task(ctx.db, ctx.user.id, 123, 0)
    await wallet.validate_task_funding(ctx.db, ctx.user.id, 123)
    await wallet.settle_task(ctx.db, ctx.user.id, 123, 0)
    with pytest.raises(wallet.WalletError) as settled:
        await wallet.validate_task_funding(ctx.db, ctx.user.id, 123)
    assert settled.value.code == "WALLET_TASK_RESERVATION_REQUIRED"


@pytest.mark.asyncio
async def test_refund_reversal_preserves_prior_admin_deduction(wallet_ctx):
    """撤销退款只恢复未用额度，不能悄悄撤销管理员已确认的调减。"""
    ctx = wallet_ctx
    await add(ctx, "paid", 100)
    await wallet.consume(ctx.db, ctx.user.id, 50, business_type="admin_adjustment", business_ref="adjust-1")
    await refund(ctx, "paid")
    assert (await wallet.snapshot(ctx.db, ctx.user.id))["debt_fen"] == 0
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "paid")
    state = await wallet.snapshot(ctx.db, ctx.user.id)
    assert state["balance_fen"] == 50 and state["debt_fen"] == 0


@pytest.mark.asyncio
async def test_refund_reserved_source_actual_usage_and_reversal(wallet_ctx):
    ctx = wallet_ctx
    await add(ctx, "a")
    await wallet.reserve_task(ctx.db, ctx.user.id, 1, 80)
    await refund(ctx, "a")
    assert await ctx.db.scalar(select(func.count()).select_from(WalletTaskNotice)) == 1
    with pytest.raises(wallet.WalletError):
        await wallet.validate_task_funding(ctx.db, ctx.user.id, 1)
    assert (await wallet.settle_task(ctx.db, ctx.user.id, 1, 30))["debt_fen"] == 30
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "a")
    state = await wallet.snapshot(ctx.db, ctx.user.id)
    assert (state["balance_fen"], state["frozen_fen"], state["debt_fen"]) == (70, 0, 0)


@pytest.mark.asyncio
async def test_refund_repayment_refund_reopens_original_debt_once(wallet_ctx):
    ctx = wallet_ctx
    await add(ctx, "a")
    await spend_ai(ctx, 100)
    await refund(ctx, "a")
    assert await debt_units(ctx.db, ctx.user.id) == 100
    await add(ctx, "b")
    assert await debt_units(ctx.db, ctx.user.id) == 0
    await refund(ctx, "b")
    await refund(ctx, "b")
    assert await debt_units(ctx.db, ctx.user.id) == 100
    assert await ctx.db.scalar(select(func.count()).select_from(WalletDebt)) == 1
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "a")
    assert (await wallet.snapshot(ctx.db, ctx.user.id))["balance_fen"] == 0
    assert await debt_units(ctx.db, ctx.user.id) == 0
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "b")
    assert (await wallet.snapshot(ctx.db, ctx.user.id))["balance_fen"] == 100


@pytest.mark.asyncio
async def test_original_refund_reversal_returns_replacement_not_double_credit(wallet_ctx):
    ctx = wallet_ctx
    await add(ctx, "a")
    await spend_ai(ctx, 100)
    await refund(ctx, "a")
    await add(ctx, "b")
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "a")
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "a")
    state = await wallet.snapshot(ctx.db, ctx.user.id)
    assert (state["balance_fen"], state["debt_fen"]) == (100, 0)
    original = await wallet.get_source(ctx.db, ctx.user.id, "apple_transaction", "a")
    assert original.available_ranges == []


@pytest.mark.asyncio
async def test_third_source_repayment_prevents_reversal_overpay(wallet_ctx):
    ctx = wallet_ctx
    await add(ctx, "a")
    await spend_ai(ctx, 100)
    await refund(ctx, "a")
    await add(ctx, "b")
    await refund(ctx, "b")
    await add(ctx, "c")
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "b")
    assert (await wallet.snapshot(ctx.db, ctx.user.id))["balance_fen"] == 100
    assert await debt_units(ctx.db, ctx.user.id) == 0
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "a")
    assert (await wallet.snapshot(ctx.db, ctx.user.id))["balance_fen"] == 200


@pytest.mark.asyncio
async def test_mixed_video_refund_returns_other_source_without_debt(wallet_ctx):
    ctx = wallet_ctx
    await add(ctx, "a", 40)
    await add(ctx, "b", 60)
    await wallet.consume(ctx.db, ctx.user.id, 80, business_type="video_unlock", business_ref="1")
    result = await wallet.revoke_source(ctx.db, ctx.user.id, "apple_transaction", "a")
    assert result["affected_business_refs"] == [{"business_type": "video_unlock", "business_ref": "1"}]
    await wallet.restore_consumption(ctx.db, ctx.user.id, "video_unlock", "1")
    state = await wallet.snapshot(ctx.db, ctx.user.id)
    assert (state["balance_fen"], state["debt_fen"]) == (60, 0)
    await wallet.reverse_source(ctx.db, ctx.user.id, "apple_transaction", "a")
    assert (await wallet.snapshot(ctx.db, ctx.user.id))["balance_fen"] == 100


@pytest.mark.asyncio
async def test_environment_and_missing_migration_fail_closed(wallet_ctx):
    ctx = wallet_ctx
    with pytest.raises(wallet.WalletError) as error:
        await wallet.credit(ctx.db, ctx.user.id, 100, source_type="apple_transaction", source_ref="sandbox", environment="Sandbox")
    assert error.value.code == "WALLET_ENVIRONMENT_MISMATCH"
    user = User(email=f"{uuid.uuid4().hex}@test.invalid", hashed_password="unused", balance_fen=50)
    ctx.db.add(user)
    await ctx.db.flush()
    with pytest.raises(wallet.WalletError) as error:
        await wallet.initialize_account(ctx.db, user)
    assert error.value.code == "WALLET_MIGRATION_REQUIRED"


@pytest.mark.asyncio
async def test_concurrent_duplicate_credit_uses_user_lock(wallet_ctx):
    ctx = wallet_ctx
    await ctx.db.commit()
    async def apply():
        """不同连接模拟通知与验单同时到达。"""
        async with ctx.factory() as db:
            item = await wallet.credit(db, ctx.user.id, 100, source_type="web_order", source_ref="same", amount_fen=80)
            await db.commit()
            return item.id
    first, second = await asyncio.gather(apply(), apply())
    assert first == second
    state = await wallet.snapshot(ctx.db, ctx.user.id)
    assert state["balance_fen"] == 100
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == 1
