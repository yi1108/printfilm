"""仅 App 使用的资金路由；AI/Web 不导入，不能消费测试积分。"""
from app.services.billing import wallet as production
from . import sandbox_wallet


def isolated(environment):
    return environment == 'Sandbox' and production.configured_environment() == 'Production'


async def lock_account(db, user_id, environment):
    if isolated(environment):
        return await sandbox_wallet.lock_account(db, user_id)
    return await production.lock_account(db, user_id, environment)


async def snapshot(db, user_id, environment):
    if isolated(environment):
        return await sandbox_wallet.snapshot(db, user_id)
    return await production.snapshot(db, user_id, environment)


async def consume(db, user_id, amount, **kwargs):
    if isolated(kwargs.get('environment')):
        return await sandbox_wallet.consume(db, user_id, amount, **kwargs)
    return await production.consume(db, user_id, amount, **kwargs)
