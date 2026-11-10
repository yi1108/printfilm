"""沙箱只测试 Apple 和视频；生产 AI 永远不调用本模块。"""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.config import get_settings
from app.models import User
from .sandbox_models import SandboxAccount, SandboxLot, SandboxAllocation, SandboxEntry
def app_fail(*args):
    from .coin_service import app_fail as fail
    return fail(*args)


def tester(user_id):
    ids = get_settings().apple_sandbox_user_ids
    return user_id is not None and str(user_id) in {part.strip() for part in ids.split(',') if part.strip()}


def environment(user_id=None):
    from app.services.billing.wallet_base import environment as production_environment
    return "Sandbox" if tester(user_id) else production_environment()


def new_purchase_allowed(user_id):
    return bool(tester(user_id) and get_settings().apple_sandbox_enabled)


async def lock_account(db, user_id):
    # 与生产 AI 共用 User 行锁，沙箱余额则完全独立。
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update(key_share=True))
    if not user:
        app_fail("WALLET_ACCOUNT_NOT_FOUND", "账号不存在。", 404)
    await db.execute(insert(SandboxAccount).values(user_id=user_id, balance_fen=0).on_conflict_do_nothing(index_elements=['user_id']))
    return await db.scalar(select(SandboxAccount).where(SandboxAccount.user_id == user_id)
                           .execution_options(populate_existing=True))


async def authorize_transaction(db, user_id, txn):
    """停新购仍处理已创建意向/已入账交易，移出白名单也不丢失退款。"""
    from .apple_models import ApplePurchaseIntent
    from .app_models import AppleTransaction
    if tester(user_id):
        return
    previous = await db.scalar(select(AppleTransaction.id).where(AppleTransaction.user_id == user_id,
        AppleTransaction.environment == 'Sandbox', AppleTransaction.transaction_id == txn['transaction_id']))
    intent = await db.scalar(select(ApplePurchaseIntent.id).where(ApplePurchaseIntent.user_id == user_id,
        ApplePurchaseIntent.environment == 'Sandbox', ApplePurchaseIntent.product_id == txn['product_id']))
    if not previous and not intent:
        app_fail("WALLET_ENVIRONMENT_MISMATCH", "该账号未获准使用沙箱交易，未计入正式余额。", 403)


async def post(db, account, delta, kind, reference):
    account.balance_fen += delta
    db.add(SandboxEntry(user_id=account.user_id, delta_fen=delta, balance_after=account.balance_fen,
                        kind=kind, reference=reference))
    await db.flush()


async def snapshot(db, user_id, environment=None):
    account = await lock_account(db, user_id)
    return dict(environment='Sandbox', wallet_type='sandbox_test', balance_fen=account.balance_fen,
                frozen_fen=0, debt_fen=0, pending_commitment_fen=0, refund_pending=False,
                spendable_fen=account.balance_fen, test_only=True)


async def credit_transaction(db, item):
    account = await lock_account(db, item.user_id)
    db.add(SandboxLot(user_id=item.user_id, transaction_id=item.id, total_units=item.coins,
                      available_units=item.coins, active=True))
    await post(db, account, item.coins, 'recharge', f'apple:{item.id}:credit')
    item.settlement_status = 'test_only'


async def consume(db, user_id, amount, *, business_type, business_ref, environment=None):
    if not new_purchase_allowed(user_id):
        app_fail('SANDBOX_PURCHASE_DISABLED', '沙箱新购及测试解锁已暂停。', 403)
    account = await lock_account(db, user_id)
    lots = list((await db.scalars(select(SandboxLot).where(SandboxLot.user_id == user_id,
        SandboxLot.active.is_(True)).order_by(SandboxLot.id))).all())
    if sum(lot.available_units for lot in lots) != account.balance_fen:
        app_fail('WALLET_ACCOUNT_INCONSISTENT', '沙箱余额与来源不一致。', 503)
    if account.balance_fen < amount:
        app_fail('MARKETPLACE_COIN_BALANCE_INSUFFICIENT', '沙箱测试积分不足。', 409)
    remaining = amount
    for lot in lots:
        count = min(remaining, lot.available_units)
        if count:
            lot.available_units -= count
            db.add(SandboxAllocation(unlock_id=int(business_ref), lot_id=lot.id, units=count, returned=False))
            remaining -= count
    await post(db, account, -amount, 'video_unlock', f'unlock:{business_ref}')
    return []  # 沙箱不产生真实实付分摊或创作者收益。


async def refund(db, item, reversed=False):
    from .app_models import CoinUnlock, CoinGrant
    from .models import ContentOrder
    account = await lock_account(db, item.user_id)
    lot = await db.scalar(select(SandboxLot).where(SandboxLot.transaction_id == item.id))
    if not lot:
        app_fail('SANDBOX_LEGACY_REVIEW_REQUIRED', '历史沙箱资金不在隔离账本中，请人工核对，不自动搬入正式余额。', 409)
    if reversed:
        if lot.active:
            return
        lot.active = True
        await post(db, account, lot.available_units, 'refund_reversed', f'apple:{item.id}:restore:{item.revision}')
        return
    if not lot.active:
        return
    lot.active = False
    await post(db, account, -lot.available_units, 'refund', f'apple:{item.id}:refund:{item.revision}')
    allocations = list((await db.scalars(select(SandboxAllocation).where(
        SandboxAllocation.lot_id == lot.id, SandboxAllocation.returned.is_(False)))).all())
    for allocation in allocations:
        unlock = await db.get(CoinUnlock, allocation.unlock_id)
        if not unlock or unlock.status != 'paid' or unlock.environment != 'Sandbox':
            continue
        unlock.status = 'revoked'
        order = await db.get(ContentOrder, unlock.order_id)
        if order:
            order.status = 'revoked'
        grant = await db.scalar(select(CoinGrant).where(CoinGrant.unlock_id == unlock.id))
        if grant:
            grant.active = False
        rows = list((await db.scalars(select(SandboxAllocation).where(
            SandboxAllocation.unlock_id == unlock.id, SandboxAllocation.returned.is_(False)))).all())
        returned = 0
        for row in rows:
            source = await db.get(SandboxLot, row.lot_id)
            source.available_units += row.units
            row.returned = True
            if source.active:
                returned += row.units
        await post(db, account, returned, 'unlock_reversed', f'unlock:{unlock.id}:refund')
    await db.flush()


async def records(db, kind, page, page_size, user_id=None):
    """复用现有运营页环境选择器，测试账目不冒充正式资金。"""
    from sqlalchemy import func
    models = {'wallets': SandboxAccount, 'wallet-entries': SandboxEntry, 'funding-sources': SandboxLot}
    model = models.get(kind)
    if model is None:
        return {'items': [], 'meta': {'page': page, 'page_size': page_size, 'total': 0}}
    query = select(model)
    if user_id:
        query = query.where(model.user_id == user_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list((await db.scalars(query.order_by(model.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
    items = []
    for row in rows:
        item = {column.name: getattr(row, column.name) for column in model.__table__.columns if column.name != 'details'}
        item.update(environment='Sandbox', test_only=True)
        if kind == 'wallets':
            item.update(frozen_fen=0, debt_fen=0)
        elif kind == 'funding-sources':
            item.update(total_amount_fen=0, source_type='apple_sandbox', source_ref=str(row.transaction_id),
                        settlement_status='test_only')
        items.append(item)
    return {'items': items, 'meta': {'page': page, 'page_size': page_size, 'total': total}}
