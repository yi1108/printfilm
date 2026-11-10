"""钱包环境切换仅允许空账本，不能用配置转换正式或测试资金。"""
from sqlalchemy import inspect, or_, select, text

from app.models import User
from app.models_wallet import WalletAccount


async def lock_environment(db):
    # 与新钱包账户初始化串行，避免检查空库后同时写入账户。
    await db.execute(text("SELECT pg_advisory_xact_lock(734091, 11)"))


async def validate_environment_change(db):
    await lock_environment(db)
    def has_accounts(sync):
        connection = sync.connection()
        schema = (connection.get_execution_options().get("schema_translate_map") or {}).get(None)
        return inspect(connection).has_table(WalletAccount.__tablename__, schema=schema)
    if await db.run_sync(has_accounts):
        if await db.scalar(select(WalletAccount.id).limit(1)) is not None:
            raise ValueError("已有统一钱包账户，禁止直接切换钱包环境；请使用独立测试数据库，历史账目需专项核对。")
    if await db.scalar(select(User.id).where(or_(User.balance_fen != 0, User.frozen_fen != 0)).limit(1)) is not None:
        raise ValueError("已有历史余额或冻结额度，禁止切换钱包环境；请先核对资金并使用独立测试数据库。")
