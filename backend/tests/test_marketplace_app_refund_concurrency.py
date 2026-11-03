"""真实多连接退款与非等额币成本守恒；只写随机隔离测试 schema。"""
import asyncio
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import func, select, text

from app.models import User
from app.marketplace import coin_refunds
from app.marketplace.app_models import AppleProduct, CoinGrant, CoinUnlock, RevenueAdjustment
from app.models_wallet import WalletEvent, WalletFundingLot
from app.services.billing import wallet_ranges
from app.marketplace.coin_service import apply_apple_transaction, refund_apple_transaction, unlock_publication
from app.marketplace.models import ContentOrder, Entitlement, RevenueLedger
from app.marketplace.service import now
from test_marketplace_coins import coin_ctx, content, topup


async def actual_cost_topup(ctx, coins, actual_fen):
    """模拟已通过签名核验的非等额付款输入，不修改已经入账的交易。"""
    product_id = f"test.cost.{uuid.uuid4().hex}"
    ctx.db.add(AppleProduct(product_id=product_id, sku_id=f"test_cost_{coins}_{actual_fen}",
        sku_snapshot={"id": f"test_cost_{coins}_{actual_fen}", "name": "测试实付套餐", "amount_fen": actual_fen, "credit_fen": coins},
        coins=coins, price_fen=actual_fen, enabled=True))
    await ctx.db.commit()
    transaction = await apply_apple_transaction(ctx.db, {
        "environment": "Production", "transaction_id": uuid.uuid4().hex, "user_id": ctx.buyer.id,
        "product_id": product_id, "app_account_token": ctx.token, "amount_fen": actual_fen,
        "currency": "CNY", "status": "paid", "signed_at": now(), "raw_payload": {},
    })
    await ctx.db.commit()
    return transaction


async def remaining_cost(ctx):
    """检查实际资金区间的剩余实付，而非读取已停写的旧钱包字段。"""
    lots = (await ctx.db.scalars(select(WalletFundingLot).where(WalletFundingLot.active.is_(True)))).all()
    return sum(wallet_ranges.cost(lot, lot.available_ranges) for lot in lots)


async def source_lot(ctx, transaction):
    """来源始终对应环境和已验签交易编号。"""
    return await ctx.db.scalar(select(WalletFundingLot).where(
        WalletFundingLot.source_ref == f"Production:{transaction.transaction_id}"))


@pytest.mark.asyncio
async def test_opposite_author_purchase_sequences_refund_without_deadlock_or_double_reversal(coin_ctx, monkeypatch):
    """两用户的消费顺序相反，退款仍按共同作者顺序持锁，不因冲正交叉死锁。"""
    ctx = coin_ctx
    other_buyer = User(email=f"other-buyer-{uuid.uuid4().hex}@test.invalid", hashed_password="unused")
    other_owner = User(email=f"other-owner-{uuid.uuid4().hex}@test.invalid", hashed_password="unused")
    ctx.db.add_all([other_buyer, other_owner])
    await ctx.db.commit()
    peer = SimpleNamespace(db=ctx.db, buyer=other_buyer, owner=other_owner, token=str(uuid.uuid4()))
    publication_a, publication_b = await content(ctx, 100), await content(peer, 100)
    topup_a, _ = await topup(ctx, 300)
    topup_b, _ = await topup(peer, 300)
    transaction_ids = (topup_a.transaction_id, topup_b.transaction_id)
    for buyer, sequence in ((ctx.buyer, (publication_a, publication_b)), (other_buyer, (publication_b, publication_a))):
        for publication in sequence:
            await unlock_publication(ctx.db, buyer.id, "Production", publication.id, 100, uuid.uuid4().hex)
            await ctx.db.commit()

    # 保留真实 PostgreSQL 锁，仅在首次持有作者锁后让出执行权，稳定覆盖相反顺序的危险交错。
    original_lock = coin_refunds.lock_creator
    first_lock_sessions = set()

    async def yield_after_first_creator_lock(db, owner_id, environment):
        account = await original_lock(db, owner_id, environment)
        if db not in first_lock_sessions:
            first_lock_sessions.add(db)
            await asyncio.sleep(.05)
        return account

    monkeypatch.setattr(coin_refunds, "lock_creator", yield_after_first_creator_lock)

    async def concurrent_refunds():
        barrier, backend_ids = asyncio.Barrier(2), []

        async def execute(transaction_id):
            async with ctx.factory() as db:
                await db.execute(text("SET LOCAL lock_timeout = '4s'"))
                await db.execute(text("SET LOCAL statement_timeout = '8s'"))
                backend_ids.append(await db.scalar(text("SELECT pg_backend_pid()")))
                await barrier.wait()
                await refund_apple_transaction(db, "Production", transaction_id)
                await db.commit()

        tasks = [asyncio.create_task(execute(transaction_id)) for transaction_id in transaction_ids]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=12)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert len(set(backend_ids)) == 2

    await concurrent_refunds()
    entries_after_first = await ctx.db.scalar(select(func.count()).select_from(WalletEvent))
    await ctx.db.rollback()
    await concurrent_refunds()  # 两笔相同退款再次从独立连接到达。
    counts = (await ctx.db.execute(select(RevenueAdjustment.unlock_id, func.count()).group_by(RevenueAdjustment.unlock_id))).all()
    assert len(counts) == 4 and all(count == 1 for _, count in counts)
    assert await ctx.db.scalar(select(func.count()).select_from(WalletEvent)) == entries_after_first
    assert await ctx.db.scalar(select(func.sum(User.balance_fen))) == 0
    assert await ctx.db.scalar(select(func.sum(WalletEvent.delta_fen))) == 0
    assert await ctx.db.scalar(select(func.count()).select_from(CoinUnlock).where(CoinUnlock.status == "revoked")) == 4
    assert await ctx.db.scalar(select(func.count()).select_from(ContentOrder).where(ContentOrder.status == "revoked")) == 4
    assert await ctx.db.scalar(select(func.count()).select_from(CoinGrant).where(CoinGrant.active.is_(True))) == 0
    assert await ctx.db.scalar(select(func.count()).select_from(Entitlement).where(Entitlement.active.is_(True))) == 0
    assert await ctx.db.scalar(select(func.sum(RevenueLedger.gross_fen))) == 400
    assert await ctx.db.scalar(select(func.sum(RevenueAdjustment.gross_fen))) == -400
    assert await ctx.db.scalar(select(func.sum(RevenueAdjustment.creator_fen))) == -320


@pytest.mark.asyncio
@pytest.mark.parametrize("first_refunded", [0, 1])
async def test_non_unit_payment_mixed_lot_refunds_conserve_coins_and_actual_money(coin_ctx, first_refunded):
    """非1:1实付成本经跨批次扣币、退回、再消费与退款后仍完全守恒。"""
    ctx = coin_ctx
    transactions = []
    for coins, actual_fen in ((6, 10), (7, 11)):
        transactions.append(await actual_cost_topup(ctx, coins, actual_fen))

    for coins in (4, 5, 4):
        publication = await content(ctx, coins)
        await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, coins, uuid.uuid4().hex)
        await ctx.db.commit()
    assert await ctx.db.scalar(select(func.sum(User.balance_fen))) == 0
    assert await ctx.db.scalar(select(func.sum(RevenueLedger.gross_fen))) == 21
    assert await remaining_cost(ctx) == 0

    await refund_apple_transaction(ctx.db, "Production", transactions[first_refunded].transaction_id)
    await ctx.db.commit()
    valid_transaction = transactions[1-first_refunded]
    valid_lot = await source_lot(ctx, valid_transaction)
    remaining_units = wallet_ranges.units(valid_lot.available_ranges)
    remaining_fen = wallet_ranges.cost(valid_lot, valid_lot.available_ranges)
    assert remaining_units == (3 if first_refunded == 0 else 2)
    assert remaining_fen == 4
    net_revenue = await ctx.db.scalar(select(func.sum(RevenueLedger.gross_fen)))
    net_revenue += await ctx.db.scalar(select(func.sum(RevenueAdjustment.gross_fen)))
    assert net_revenue + remaining_fen == valid_transaction.amount_fen

    publication = await content(ctx, remaining_units)
    again = await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id,
        remaining_units, uuid.uuid4().hex)
    await ctx.db.commit()
    assert again["amount_fen"] == 4
    await refund_apple_transaction(ctx.db, "Production", valid_transaction.transaction_id)
    await refund_apple_transaction(ctx.db, "Production", valid_transaction.transaction_id)
    await ctx.db.commit()
    assert await ctx.db.scalar(select(func.sum(User.balance_fen))) == 0
    assert await ctx.db.scalar(select(func.sum(WalletEvent.delta_fen))) == 0
    assert await remaining_cost(ctx) == 0
    gross = await ctx.db.scalar(select(func.sum(RevenueLedger.gross_fen)))
    adjustment = await ctx.db.scalar(select(func.sum(RevenueAdjustment.gross_fen)))
    assert gross + adjustment == 0
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueAdjustment)) == 4


@pytest.mark.asyncio
async def test_actual_amount_uses_strict_cumulative_rounding_for_every_prefix(coin_ctx):
    """每笔收入遵循floor(A*end/C)-floor(A*start/C)，不能向后挪用尾差。"""
    ctx = coin_ctx
    await actual_cost_topup(ctx, 6, 10)
    costs = []
    for number in range(6):
        publication = await content(ctx, 1)
        result = await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 1, uuid.uuid4().hex)
        await ctx.db.commit()
        costs.append(result["amount_fen"])
        assert sum(costs) == 10 * (number+1) // 6
    assert costs == [1, 2, 2, 1, 2, 2]
    assert await remaining_cost(ctx) == 0


@pytest.mark.asyncio
async def test_mixed_refund_restores_original_coin_cost_ranges_without_repricing(coin_ctx):
    """退回批次中部区间后再次消费，逐币成本仍对应原来源，不能按余额重新定价。"""
    ctx = coin_ctx
    valid = await actual_cost_topup(ctx, 6, 10)
    refunded = await actual_cost_topup(ctx, 2, 2)
    for coins in (1, 1, 5, 1):
        publication = await content(ctx, coins)
        await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, coins, uuid.uuid4().hex)
        await ctx.db.commit()
    await refund_apple_transaction(ctx.db, "Production", refunded.transaction_id)
    await ctx.db.commit()
    valid_lot = await source_lot(ctx, valid)
    assert (wallet_ranges.units(valid_lot.available_ranges), wallet_ranges.cost(valid_lot, valid_lot.available_ranges)) == (4, 7)
    costs = []
    for _ in range(4):
        publication = await content(ctx, 1)
        result = await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 1, uuid.uuid4().hex)
        await ctx.db.commit()
        costs.append(result["amount_fen"])
    assert costs == [2, 1, 2, 2]
    await refund_apple_transaction(ctx.db, "Production", valid.transaction_id)
    await ctx.db.commit()
    assert await ctx.db.scalar(select(func.sum(User.balance_fen))) == 0
    gross = await ctx.db.scalar(select(func.sum(RevenueLedger.gross_fen)))
    adjustment = await ctx.db.scalar(select(func.sum(RevenueAdjustment.gross_fen)))
    assert gross + adjustment == 0


@pytest.mark.asyncio
async def test_simultaneous_same_transaction_refunds_refresh_locked_state(coin_ctx, monkeypatch):
    """两连接都先读到paid，等待用户锁后必须重读版本，不能重复追加退款事件。"""
    from app.marketplace.app_models import AppleTransaction, AppleTransactionRevision
    ctx = coin_ctx
    transaction, _ = await topup(ctx)
    publication = await content(ctx, 100)
    await unlock_publication(ctx.db, ctx.buyer.id, "Production", publication.id, 100, "same-refund-concurrent")
    await ctx.db.commit()
    barrier = asyncio.Barrier(2)
    original_lock = coin_refunds.lock_wallet

    async def both_read_before_wallet_lock(db, user_id, environment):
        await barrier.wait()
        return await original_lock(db, user_id, environment)

    monkeypatch.setattr(coin_refunds, "lock_wallet", both_read_before_wallet_lock)

    async def refund():
        async with ctx.factory() as db:
            await refund_apple_transaction(db, "Production", transaction.transaction_id)
            await db.commit()

    await asyncio.wait_for(asyncio.gather(refund(), refund()), timeout=15)
    assert await ctx.db.scalar(select(func.count()).select_from(AppleTransactionRevision)) == 2
    assert await ctx.db.scalar(select(AppleTransaction.revision)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(RevenueAdjustment)) == 1
    assert await ctx.db.scalar(select(User.balance_fen).where(User.id == ctx.buyer.id)) == 0
