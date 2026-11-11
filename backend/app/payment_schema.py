"""充值订单的增量结构：只加可空字段，不改写历史财务数据。

回退代码时保留这些字段；删除会丢失已成交外币报价，因此不提供自动 DOWN。
"""
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection


PAYMENT_COLUMNS = {
    "payment_environment": "VARCHAR(16)",
    "payment_currency": "VARCHAR(3)",
    "payment_amount_minor": "INTEGER",
    "payment_exchange_rate": "VARCHAR(32)",
}


class PaymentSchemaNotReady(RuntimeError):
    def __init__(self, missing: list[str]):
        super().__init__("充值订单结构未就绪：" + "、".join(missing))


async def apply_payment_schema_patches(conn: AsyncConnection) -> None:
    """幂等添加外币报价字段，旧订单 NULL 保持人民币含义。"""
    from app.marketplace.app_schema import acquire_schema_lock
    await conn.run_sync(acquire_schema_lock)
    if conn.dialect.name == "postgresql":
        await conn.execute(text("SELECT pg_advisory_xact_lock(82632024, 1101)"))
    tables = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    if "orders" not in tables:
        raise PaymentSchemaNotReady(["orders"])
    columns = await conn.run_sync(lambda sync: {col["name"] for col in inspect(sync).get_columns("orders")})
    for name, definition in PAYMENT_COLUMNS.items():
        if name not in columns:
            # 字段名和类型仅取自上述静态清单。
            await conn.execute(text(f"ALTER TABLE orders ADD COLUMN {name} {definition}"))


async def assert_payment_schema_ready(conn: AsyncConnection) -> None:
    """只读确认新增字段存在。"""
    tables = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    if "orders" not in tables:
        raise PaymentSchemaNotReady(["orders"])
    columns = await conn.run_sync(lambda sync: {col["name"] for col in inspect(sync).get_columns("orders")})
    missing = sorted(set(PAYMENT_COLUMNS) - columns)
    if missing:
        raise PaymentSchemaNotReady([f"orders.{name}" for name in missing])
