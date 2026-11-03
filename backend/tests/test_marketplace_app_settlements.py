"""交易财务事件对账，覆盖退款、撤销、旧幂等请求与真实数据库并发。"""
import asyncio
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select

from app.marketplace.app_admin import PayoutInput, SettlementInput
from app.marketplace.app_finance import create_payout, reconcile
from app.models import User
from app.marketplace.app_models import AppleSettlement, AppleSettlementItem, AppleTransaction, AppleTransactionRevision, AppPayout
from app.marketplace.coin_service import apply_apple_transaction, refund_apple_transaction, unlock_publication
from app.marketplace.models import RevenueLedger
from test_marketplace_coins import balance, coin_ctx, content, topup


def statement(transaction, gross, key, *, environment="Production", month="2026-10"):
    """选择交易后金额必须与本次所有待对账事件的有符号净额一致。"""
    return SettlementInput(environment=environment, month=month, transaction_ids=[transaction.id],
        channel_fee_fen=0, tax_fen=0, received_fen=gross, note="核对苹果官方财务报告", idempotency_key=key)


async def settle(ctx, transaction, gross, key, **kwargs):
    item = await reconcile(ctx.db, statement(transaction, gross, key, **kwargs), ctx.owner.id)
    await ctx.db.commit()
    return item


@pytest.mark.asyncio
async def test_refund_and_reversal_have_separate_immutable_statements(coin_ctx):
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    original = await settle(ctx, transaction, 600, "initial-statement")
    original_id = original.id
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await ctx.db.commit()
    assert transaction.revision == 1 and transaction.settlement_status == "pending"

    # 重试旧对账只能读取冻结记录，不能把退款后的当前交易标为已核对。
    duplicate = await settle(ctx, transaction, 600, "initial-statement")
    assert duplicate.id == original_id
    assert transaction.settlement_status == "pending"
    refunded = await settle(ctx, transaction, -600, "refund-statement", month="2026-11")
    assert refunded.gross_fen == refunded.received_fen == -600

    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id, reversed=True)
    await ctx.db.commit()
    assert transaction.revision == 2 and transaction.settlement_status == "pending"
    reversed_statement = await settle(ctx, transaction, 600, "reversed-statement", month="2026-12")
    assert reversed_statement.gross_fen == 600
    items = list((await ctx.db.scalars(select(AppleSettlementItem).order_by(AppleSettlementItem.revision))).all())
    assert [(item.revision, item.status, item.gross_fen) for item in items] == [
        (0, "paid", 600), (1, "refunded", -600), (2, "paid", 600)]
    await ctx.db.refresh(original)
    assert original.gross_fen == original.received_fen == 600


@pytest.mark.asyncio
async def test_refund_arrives_before_first_verify_has_zero_initial_net(coin_ctx):
    ctx = coin_ctx
    transaction, payload = await topup(ctx, status="refunded")
    await apply_apple_transaction(ctx.db, {**payload, "status": "paid"})
    await ctx.db.commit()
    assert await balance(ctx) == 0
    initial = await settle(ctx, transaction, 0, "refund-first-statement")
    assert initial.gross_fen == 0
    revision = await ctx.db.scalar(select(AppleTransactionRevision))
    assert (revision.revision, revision.status, revision.delta_gross_fen) == (0, "refunded", 0)

    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id, reversed=True)
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id, reversed=True)
    await ctx.db.commit()
    assert await balance(ctx) == 600
    restored = await settle(ctx, transaction, 600, "refund-first-restored")
    assert restored.gross_fen == 600
    assert await ctx.db.scalar(select(func.count()).select_from(AppleTransactionRevision)) == 2


@pytest.mark.asyncio
async def test_all_unreconciled_cycles_are_included_and_idempotent(coin_ctx):
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id, reversed=True)
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await ctx.db.commit()
    result = await settle(ctx, transaction, 0, "all-revision-statement")
    duplicate = await settle(ctx, transaction, 0, "all-revision-statement")
    assert result.id == duplicate.id
    assert await ctx.db.scalar(select(func.count()).select_from(AppleSettlement)) == 1
    items = list((await ctx.db.scalars(select(AppleSettlementItem).order_by(AppleSettlementItem.revision))).all())
    assert [item.gross_fen for item in items] == [600, -600, 600, -600]
    assert [item.revision for item in items] == [0, 1, 2, 3]
    assert transaction.settlement_status == "reconciled"


@pytest.mark.asyncio
async def test_restored_coins_need_new_reconciliation_before_payout(coin_ctx):
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    publication = await content(ctx, 100)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "initial-settled-unlock")
    await ctx.db.commit()
    await settle(ctx, transaction, 600, "initial-revenue-statement")
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id)
    await refund_apple_transaction(ctx.db, "Production", transaction.transaction_id, reversed=True)
    await ctx.db.commit()
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "restored-coin-unlock")
    await ctx.db.commit()
    ledger = await ctx.db.scalar(select(RevenueLedger).order_by(RevenueLedger.id.desc()).limit(1))
    payout = PayoutInput(environment="Production", owner_id=ctx.owner.id, ledger_ids=[ledger.id],
        amount_fen=80, note="新收益打款回执", idempotency_key="restored-revenue-payout")
    with pytest.raises(HTTPException) as error:
        await create_payout(ctx.db, payout, ctx.owner.id)
    assert error.value.detail["code"] == "MARKETPLACE_PAYOUT_NOT_ELIGIBLE"
    await ctx.db.rollback()
    await ctx.db.refresh(transaction)
    await ctx.db.refresh(ctx.owner)
    await settle(ctx, transaction, 0, "refund-reversal-net-statement")
    await create_payout(ctx.db, payout, ctx.owner.id)
    await ctx.db.commit()
    await ctx.db.refresh(ledger)
    assert ledger.settlement_status == "paid"


@pytest.mark.asyncio
async def test_refund_locked_before_stale_statement_cannot_release_revenue(coin_ctx):
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    refund_ready, release_refund = asyncio.Event(), asyncio.Event()

    async def refund():
        async with ctx.factory() as db:
            await refund_apple_transaction(db, "Production", transaction.transaction_id)
            refund_ready.set()
            await release_refund.wait()
            await db.commit()

    async def stale_statement():
        await refund_ready.wait()
        release_refund.set()
        async with ctx.factory() as db:
            with pytest.raises(HTTPException) as error:
                await reconcile(db, statement(transaction, 600, "stale-in-flight-statement"), ctx.owner.id)
            assert error.value.detail["code"] == "MARKETPLACE_SETTLEMENT_AMOUNT_MISMATCH"
            await db.rollback()

    await asyncio.wait_for(asyncio.gather(refund(), stale_statement()), timeout=15)
    await ctx.db.refresh(transaction)
    assert transaction.status == "refunded" and transaction.settlement_status == "pending"
    assert await ctx.db.scalar(select(func.count()).select_from(AppleSettlement)) == 0


@pytest.mark.asyncio
async def test_statement_locked_before_refund_cannot_mark_new_revision_reconciled(coin_ctx):
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    statement_ready, release_statement = asyncio.Event(), asyncio.Event()

    async def initial_statement():
        async with ctx.factory() as db:
            await reconcile(db, statement(transaction, 600, "before-refund-statement"), ctx.owner.id)
            statement_ready.set()
            await release_statement.wait()
            await db.commit()

    async def later_refund():
        await statement_ready.wait()
        release_statement.set()
        async with ctx.factory() as db:
            await refund_apple_transaction(db, "Production", transaction.transaction_id)
            await db.commit()

    await asyncio.wait_for(asyncio.gather(initial_statement(), later_refund()), timeout=15)
    await ctx.db.refresh(transaction)
    assert transaction.revision == 1 and transaction.settlement_status == "pending"
    assert await ctx.db.scalar(select(func.count()).select_from(AppleSettlementItem)) == 1


@pytest.mark.asyncio
async def test_settlement_rejects_cross_environment_and_incomplete_event_history(coin_ctx):
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    with pytest.raises(HTTPException) as mismatch:
        await reconcile(ctx.db, statement(transaction, 600, "wrong-env-statement", environment="Sandbox"), ctx.owner.id)
    assert mismatch.value.detail["code"] == "MARKETPLACE_SETTLEMENT_INVALID"
    await ctx.db.rollback()
    await ctx.db.refresh(transaction)
    await ctx.db.refresh(ctx.owner)
    transaction.revision = 1
    await ctx.db.commit()
    with pytest.raises(HTTPException) as missing:
        await reconcile(ctx.db, statement(transaction, 600, "missing-revision-statement"), ctx.owner.id)
    assert missing.value.detail["code"] == "MARKETPLACE_SETTLEMENT_REVISION_MISSING"
    await ctx.db.rollback()
    assert await ctx.db.scalar(select(func.count()).select_from(AppleSettlement)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("different", ["owner", "environment"])
async def test_concurrent_global_payout_idempotency_is_conflict_not_database_error(coin_ctx, different):
    """不同作者/环境同一幂等键也要串行化，不能在唯一约束处变成500。"""
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    first = await content(ctx, 100)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", first.id, 100, "first-owner-unlock")
    await ctx.db.commit()
    await settle(ctx, transaction, 600, "first-source-statement")
    if different == "environment":
        # 统一余额要求 Sandbox 独立部署，生产库不能先创建一套可用沙箱余额。
        with pytest.raises(HTTPException) as mismatch:
            await topup(ctx, environment="Sandbox")
        assert mismatch.value.detail["code"] == "WALLET_ENVIRONMENT_MISMATCH"
        ledger = await ctx.db.scalar(select(RevenueLedger))
        body = PayoutInput(environment="Production", owner_id=ctx.owner.id, ledger_ids=[ledger.id],
            amount_fen=80, note="人工打款回执", idempotency_key="global-shared-payout-key")
        await create_payout(ctx.db, body, ctx.owner.id)
        await ctx.db.commit()
        # 即使外部重用了另一个环境标签，也只能报告冲突，不能复用已打款幂等键。
        with pytest.raises(HTTPException) as conflict:
            await create_payout(ctx.db, body.model_copy(update={"environment": "Sandbox"}), ctx.owner.id)
        assert conflict.value.detail["code"] == "MARKETPLACE_IDEMPOTENCY_CONFLICT"
        assert await ctx.db.scalar(select(func.count()).select_from(AppPayout)) == 1
        return
    else:
        other_environment = "Production"
        other_owner = User(email=f"second-creator-{uuid.uuid4().hex}@test.invalid", hashed_password="unused")
        ctx.db.add(other_owner)
        await ctx.db.commit()
        second = await content(SimpleNamespace(db=ctx.db, owner=other_owner), 100)
        await unlock_publication(ctx.db, ctx.buyer.id, "Production", second.id, 100, "second-owner-unlock")
        await ctx.db.commit()
    ledgers = list((await ctx.db.scalars(select(RevenueLedger).order_by(RevenueLedger.id))).all())
    bodies = [PayoutInput(environment=environment, owner_id=owner.id, ledger_ids=[ledger.id], amount_fen=80,
                          note="人工打款回执", idempotency_key="global-shared-payout-key")
              for environment, owner, ledger in [("Production", ctx.owner, ledgers[0]),
                                                 (other_environment, other_owner, ledgers[1])]]

    async def execute(body):
        async with ctx.factory() as db:
            try:
                await create_payout(db, body, ctx.owner.id)
                await db.commit()
                return "paid"
            except HTTPException as error:
                await db.rollback()
                return error.detail["code"]

    outcomes = await asyncio.wait_for(asyncio.gather(*(execute(body) for body in bodies)), timeout=15)
    assert sorted(outcomes) == sorted(["paid", "MARKETPLACE_IDEMPOTENCY_CONFLICT"])
    assert await ctx.db.scalar(select(func.count()).select_from(AppPayout)) == 1
