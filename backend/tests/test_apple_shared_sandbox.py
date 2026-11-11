"""同数据库沙箱必须不改变真实余额、来源、收益与权益。"""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.config import get_settings
from app.models import WalletLedger
from app.models_wallet import WalletFundingLot, WalletEvent
from app.services.billing import wallet
from app.marketplace import apple_service, apple_api, app_access, sandbox_wallet, coin_api
from app.marketplace.app_models import CoinGrant, CoinUnlock, AppleTransaction
from app.marketplace.models import RevenueLedger, Entitlement
from app.marketplace.sandbox_models import SandboxEntry, SandboxLot, SandboxAccount
from app.marketplace.coin_service import unlock_publication, has_access
from app.marketplace.coin_refunds import refund_apple_transaction
from test_marketplace_apple_iap import apple_cfg, apple_ctx, verified_transaction
from test_marketplace_app_content import make_work


@pytest.fixture
def sandbox(apple_ctx, monkeypatch):
    monkeypatch.setattr(get_settings(), 'apple_sandbox_user_ids', str(apple_ctx.buyer.id))
    monkeypatch.setattr(get_settings(), 'apple_sandbox_enabled', True)
    return apple_ctx


async def purchase(ctx, transaction_id='sandbox-one', **changes):
    return await apple_service.apply_verified_transaction(ctx.db, verified_transaction(ctx,
        environment='Sandbox', transaction_id=transaction_id, **changes), expected_user_id=ctx.buyer.id)


@pytest.mark.asyncio
async def test_credit_is_separate_idempotent_and_ai_stays_production(sandbox):
    ctx = sandbox
    await wallet.credit(ctx.db, ctx.buyer.id, 100, source_type='admin_grant', source_ref='real-gift')
    before = await ctx.db.scalar(select(func.count()).select_from(WalletEvent))
    txn = await purchase(ctx)
    await purchase(ctx)
    assert txn.settlement_status == 'test_only'
    assert (await sandbox_wallet.snapshot(ctx.db, ctx.buyer.id))['balance_fen'] == 600
    assert ctx.buyer.balance_fen == 100
    assert await ctx.db.scalar(select(func.count()).select_from(WalletEvent)) == before
    assert await ctx.db.scalar(select(func.count()).select_from(SandboxLot)) == 1
    assert await ctx.db.scalar(select(func.count()).select_from(WalletFundingLot)) == 1
    await wallet.reserve_task(ctx.db, ctx.buyer.id, 100, 80)
    await wallet.settle_task(ctx.db, ctx.buyer.id, 100, 80)
    assert ctx.buyer.balance_fen == 20
    assert (await sandbox_wallet.snapshot(ctx.db, ctx.buyer.id))['balance_fen'] == 600
    assert app_access.environment(ctx.buyer.id) == 'Sandbox'
    assert app_access.environment(ctx.other.id) == 'Production'
    assert wallet.configured_environment() == 'Production'


@pytest.mark.asyncio
async def test_non_whitelisted_and_cross_account_transactions_rejected(apple_ctx):
    ctx = apple_ctx
    with pytest.raises(HTTPException) as error:
        await purchase(ctx)
    assert error.value.detail['code'] == 'WALLET_ENVIRONMENT_MISMATCH'
    assert not await ctx.db.scalar(select(SandboxAccount.id))
    with pytest.raises(HTTPException):
        await apple_service.apply_verified_transaction(ctx.db, verified_transaction(ctx, environment='Sandbox'),
                                                       expected_user_id=ctx.other.id)
    assert not await ctx.db.scalar(select(AppleTransaction.id))


@pytest.mark.asyncio
async def test_legacy_sandbox_transaction_cannot_pretend_isolated_credit_was_delivered(sandbox):
    ctx = sandbox
    from app.marketplace.service import now
    ctx.db.add(AppleTransaction(environment='Sandbox', transaction_id='legacy', user_id=ctx.buyer.id,
        product_id='coins.600', app_account_token=ctx.token.token, coins=600, amount_fen=600,
        signed_at=now(), status='paid'))
    await ctx.db.flush()
    with pytest.raises(HTTPException) as error:
        await purchase(ctx, 'legacy')
    assert error.value.detail['code'] == 'SANDBOX_LEGACY_REVIEW_REQUIRED'
    assert ctx.buyer.balance_fen == 0
    assert not await ctx.db.scalar(select(SandboxLot.id))


@pytest.mark.asyncio
async def test_mixed_lot_refund_repurchase_and_reversal_never_touch_real_rights(sandbox):
    ctx = sandbox
    first = await purchase(ctx, 'first')
    await purchase(ctx, 'second')
    item = await make_work(SimpleNamespace(db=ctx.db, owner=ctx.other), sale_type='platform_unlock')
    item.publication.unlock_price_fen = 800
    # The actual sale, source allocation and grants all execute against PostgreSQL.
    unlocked = await unlock_publication(ctx.db, ctx.buyer.id, 'Sandbox', item.publication.id, 800, 'unlock-first')
    retry = await unlock_publication(ctx.db, ctx.buyer.id, 'Sandbox', item.publication.id, 800, 'unlock-first')
    assert retry['duplicate'] and unlocked['balance_fen'] == 400
    assert await has_access(ctx.db, ctx.buyer.id, item.publication.id, 'Sandbox')
    assert not await has_access(ctx.db, ctx.buyer.id, item.publication.id, 'Production')
    assert not await ctx.db.scalar(select(RevenueLedger.id))
    assert not await ctx.db.scalar(select(Entitlement.id))
    await refund_apple_transaction(ctx.db, 'Sandbox', first.transaction_id)
    assert (await sandbox_wallet.snapshot(ctx.db, ctx.buyer.id))['balance_fen'] == 600
    assert not await has_access(ctx.db, ctx.buyer.id, item.publication.id, 'Sandbox')
    item.publication.unlock_price_fen = 100
    newer = await unlock_publication(ctx.db, ctx.buyer.id, 'Sandbox', item.publication.id, 100, 'unlock-newer')
    await refund_apple_transaction(ctx.db, 'Sandbox', first.transaction_id)
    assert await has_access(ctx.db, ctx.buyer.id, item.publication.id, 'Sandbox')
    await refund_apple_transaction(ctx.db, 'Sandbox', first.transaction_id, reversed=True)
    assert (await sandbox_wallet.snapshot(ctx.db, ctx.buyer.id))['balance_fen'] == 1100
    await refund_apple_transaction(ctx.db, 'Sandbox', first.transaction_id, reversed=True)
    assert (await sandbox_wallet.snapshot(ctx.db, ctx.buyer.id))['balance_fen'] == 1100
    assert (await ctx.db.get(CoinUnlock, newer['id'])).status == 'paid'
    assert ctx.buyer.balance_fen == 0
    assert not await ctx.db.scalar(select(WalletLedger.id))


@pytest.mark.asyncio
async def test_stopping_new_purchase_preserves_intent_fulfillment_and_refund(sandbox, monkeypatch):
    ctx = sandbox
    await apple_service.purchase_intent(ctx.db, ctx.buyer.id, 'Sandbox', 'coins.600', 'sandbox-intent')
    monkeypatch.setattr(get_settings(), 'apple_sandbox_enabled', False)
    assert not apple_api.purchasing_enabled(ctx.buyer.id)
    with pytest.raises(HTTPException):
        await apple_service.purchase_intent(ctx.db, ctx.buyer.id, 'Sandbox', 'coins.600', 'another-intent')
    monkeypatch.setattr(get_settings(), 'apple_sandbox_user_ids', '')
    txn = await purchase(ctx)
    await refund_apple_transaction(ctx.db, 'Sandbox', txn.transaction_id)
    assert (await sandbox_wallet.snapshot(ctx.db, ctx.buyer.id))['balance_fen'] == 0
    assert ctx.buyer.balance_fen == 0


@pytest.mark.asyncio
async def test_app_entries_read_only_sandbox_ledger(sandbox):
    ctx = sandbox
    await purchase(ctx)
    await wallet.credit(ctx.db, ctx.buyer.id, 10, source_type='admin_grant', source_ref='production-only')
    response = await coin_api.wallet_entries(ctx.db, ctx.buyer, cursor=None, page_size=20)
    assert [row['delta_fen'] for row in response['items']] == [600]
    assert await ctx.db.scalar(select(func.count()).select_from(SandboxEntry)) == 1


@pytest.mark.asyncio
async def test_legacy_ios_wallet_and_explicit_web_view_are_isolated(sandbox, monkeypatch):
    from test_unified_wallet_api import client_for
    ctx = sandbox
    ctx.owner = ctx.other
    await purchase(ctx)
    await wallet.credit(ctx.db, ctx.buyer.id, 100, source_type='admin_grant', source_ref='real-web-points')
    await wallet.reserve_task(ctx.db, ctx.buyer.id, 102, 25)
    async with client_for(ctx, monkeypatch) as client:
        legacy = (await client.get('/api/billing/wallet')).json()
        app = (await client.get('/api/marketplace/app/v1/me/wallet')).json()
        web = (await client.get('/api/billing/wallet?view=production')).json()
        assert legacy['balance_fen'] == app['balance_fen'] == 600
        assert legacy['balance_yuan'] == 6
        assert legacy['frozen_fen'] == 0 and legacy['frozen_yuan'] == 0
        assert legacy['environment'] == 'Sandbox' and legacy['test_only']
        assert legacy['wallet_type'] == 'sandbox_test'
        assert web['balance_fen'] == 75 and web['balance_yuan'] == .75
        assert web['frozen_fen'] == 25 and web['frozen_yuan'] == .25
        assert web['environment'] == 'Production' and not web['test_only']
        assert (await client.get('/api/billing/wallet?view=Sandbox')).status_code == 422
    assert ctx.buyer.balance_fen == 75 and ctx.buyer.frozen_fen == 25


@pytest.mark.asyncio
async def test_removing_whitelist_restores_legacy_wallet_view(sandbox, monkeypatch):
    from app.api.billing import wallet as wallet_endpoint
    ctx = sandbox
    await purchase(ctx)
    await wallet.credit(ctx.db, ctx.buyer.id, 100, source_type='admin_grant', source_ref='real-balance')
    monkeypatch.setattr(get_settings(), 'apple_sandbox_enabled', False)
    assert (await wallet_endpoint(ctx.buyer, ctx.db))['balance_fen'] == 600
    monkeypatch.setattr(get_settings(), 'apple_sandbox_user_ids', '')
    state = await wallet_endpoint(ctx.buyer, ctx.db)
    assert state['balance_fen'] == 100 and state['environment'] == 'Production'
    assert not state['test_only']
    assert (await sandbox_wallet.snapshot(ctx.db, ctx.buyer.id))['balance_fen'] == 600


@pytest.mark.asyncio
async def test_official_verifiers_select_environment_without_context_leak(apple_cfg, monkeypatch):
    import asyncio
    from app.marketplace import apple_client
    from test_marketplace_apple_iap import signed_payload

    def objects():
        env = apple_client._selected_environment.get()
        def verify(signed):
            if signed != env:
                raise ValueError('signature environment mismatch')
            return signed_payload(environment=env)
        return SimpleNamespace(verify_and_decode_signed_transaction=verify), None

    monkeypatch.setattr(apple_client, '_objects', objects)
    production, sandbox = await asyncio.gather(apple_client.verify_transaction('Production'),
                                               apple_client.verify_transaction('Sandbox'))
    assert production['environment'] == 'Production'
    assert sandbox['environment'] == 'Sandbox'
    assert apple_client._selected_environment.get() is None
    with pytest.raises(HTTPException):
        await apple_client.verify_transaction('forged')


@pytest.mark.asyncio
async def test_sandbox_finance_is_rejected_and_admin_queries_are_separate(sandbox):
    from app.marketplace import app_finance, unified_admin
    ctx = sandbox
    await purchase(ctx)
    await apple_service.purchase_intent(ctx.db, ctx.buyer.id, 'Sandbox', 'coins.600', 'pending-test')
    for operation in (app_finance.reconcile, app_finance.create_payout):
        with pytest.raises(HTTPException) as error:
            await operation(ctx.db, SimpleNamespace(environment='Sandbox'), ctx.other.id)
        assert error.value.detail['code'] == 'SANDBOX_FINANCE_FORBIDDEN'
    test_wallets = await unified_admin.records(ctx.db, 'wallets', 'Sandbox', 1, 20)
    assert test_wallets['items'][0]['balance_fen'] == 600
    assert test_wallets['items'][0]['test_only']
    test_orders = await unified_admin.records(ctx.db, 'recharge-orders', 'Sandbox', 1, 20)
    real_orders = await unified_admin.records(ctx.db, 'recharge-orders', 'Production', 1, 20)
    assert test_orders['meta']['total'] == 2
    assert real_orders['meta']['total'] == 0
