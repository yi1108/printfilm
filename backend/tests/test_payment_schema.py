"""Exercise the additive Stripe migration in private PostgreSQL schemas."""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.payment_schema import (
    PAYMENT_COLUMNS,
    PaymentSchemaNotReady,
    apply_payment_schema_patches,
    assert_payment_schema_ready,
)


LEGACY_COLUMNS = "id, out_trade_no, amount_fen, credit_fen, pay_type, status, trade_no"


@pytest_asyncio.fixture
async def payment_schema_db():
    """Use a separate search_path and never the developer/demo database port."""
    url = os.environ.get("PAYMENT_SCHEMA_TEST_DATABASE_URL") or get_settings().database_url
    parsed = make_url(url)
    if (not parsed.drivername.startswith("postgresql") or "test" not in (parsed.database or "")
            or parsed.port == 15432):
        pytest.skip("Payment migration tests require an isolated PostgreSQL test URL; port 15432 is excluded")
    schema = f"stripe_payment_test_{uuid.uuid4().hex}"
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as setup:
            await setup.execute(text(f'CREATE SCHEMA "{schema}"'))
            assert await setup.scalar(text("SELECT current_schema()")) == schema
        async with engine.connect() as conn:
            yield engine, conn
    finally:
        # The generated identifier is internal, and contains only this fixed
        # prefix plus a UUID. No shared schema, table, or application data is used.
        async with engine.begin() as cleanup:
            await cleanup.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def create_legacy_orders(conn):
    await conn.execute(text("""
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            out_trade_no VARCHAR(64) UNIQUE NOT NULL,
            amount_fen INTEGER NOT NULL,
            credit_fen INTEGER NOT NULL,
            pay_type VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL,
            trade_no VARCHAR(128)
        )
    """))
    await conn.execute(text("""
        INSERT INTO orders (id, out_trade_no, amount_fen, credit_fen, pay_type, status, trade_no)
        VALUES (1, 'PF_LEGACY_PENDING', 49000, 52000, 'stripe', 'pending', 'cs_test_legacy'),
               (2, 'PF_LEGACY_PAID', 99000, 104000, 'alipay', 'paid', 'epay_legacy_paid')
    """))


async def column_metadata(conn):
    columns = await conn.run_sync(lambda sync: inspect(sync).get_columns("orders"))
    # Reflected SQL type instances compare by identity; compare their SQL form.
    return [{**column, "type": str(column["type"])} for column in columns]


async def legacy_rows(conn):
    return (await conn.execute(text(f"SELECT {LEGACY_COLUMNS} FROM orders ORDER BY id"))).all()


@pytest.mark.asyncio
async def test_legacy_rows_are_unchanged_and_added_snapshot_columns_are_nullable(payment_schema_db):
    _, conn = payment_schema_db
    await create_legacy_orders(conn)
    before = await legacy_rows(conn)
    await apply_payment_schema_patches(conn)
    await assert_payment_schema_ready(conn)
    assert await legacy_rows(conn) == before
    snapshots = (await conn.execute(text(
        "SELECT payment_currency, payment_amount_minor, payment_exchange_rate FROM orders ORDER BY id"
    ))).all()
    assert snapshots == [(None, None, None), (None, None, None)]
    added = {column["name"]: column for column in await column_metadata(conn) if column["name"] in PAYMENT_COLUMNS}
    assert set(added) == set(PAYMENT_COLUMNS)
    for column in added.values():
        assert column["nullable"] is True
        assert column["default"] is None
    assert str(added["payment_currency"]["type"]) == "VARCHAR(3)"
    assert str(added["payment_amount_minor"]["type"]) == "INTEGER"
    assert str(added["payment_exchange_rate"]["type"]) == "VARCHAR(32)"


@pytest.mark.asyncio
async def test_partial_and_repeated_migrations_preserve_existing_quotes(payment_schema_db):
    _, conn = payment_schema_db
    await create_legacy_orders(conn)
    await conn.execute(text("ALTER TABLE orders ADD COLUMN payment_currency VARCHAR(3)"))
    await conn.execute(text("ALTER TABLE orders ADD COLUMN payment_amount_minor INTEGER"))
    await conn.execute(text("UPDATE orders SET payment_currency = 'usd', payment_amount_minor = 7000 WHERE id = 1"))
    before = await legacy_rows(conn)
    await apply_payment_schema_patches(conn)
    await conn.execute(text("UPDATE orders SET payment_exchange_rate = '7' WHERE id = 1"))
    first = await column_metadata(conn)
    for _ in range(2):
        await apply_payment_schema_patches(conn)
        await assert_payment_schema_ready(conn)
    assert await column_metadata(conn) == first
    assert await legacy_rows(conn) == before
    assert (await conn.execute(text(
        "SELECT payment_currency, payment_amount_minor, payment_exchange_rate FROM orders WHERE id = 1"
    ))).one() == ("usd", 7000, "7")


@pytest.mark.asyncio
async def test_readonly_check_reports_missing_fields_without_applying_migration(payment_schema_db):
    _, conn = payment_schema_db
    await create_legacy_orders(conn)
    await conn.execute(text("ALTER TABLE orders ADD COLUMN payment_currency VARCHAR(3)"))
    before_rows = await legacy_rows(conn)
    before_columns = await column_metadata(conn)
    await conn.commit()
    async with conn.begin():
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        assert await conn.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(PaymentSchemaNotReady) as error:
            await assert_payment_schema_ready(conn)
        assert "orders.payment_amount_minor" in str(error.value)
        assert "orders.payment_exchange_rate" in str(error.value)
        assert "orders.payment_currency" not in str(error.value)
        assert await column_metadata(conn) == before_columns
        assert await legacy_rows(conn) == before_rows


@pytest.mark.asyncio
async def test_readonly_check_accepts_ready_schema_without_mutating_values(payment_schema_db):
    _, conn = payment_schema_db
    await create_legacy_orders(conn)
    await apply_payment_schema_patches(conn)
    await conn.execute(text("UPDATE orders SET payment_currency = 'hkd', payment_amount_minor = 54444, payment_exchange_rate = '0.9' WHERE id = 1"))
    before = (await conn.execute(text("SELECT * FROM orders ORDER BY id"))).all()
    before_columns = await column_metadata(conn)
    await conn.commit()
    async with conn.begin():
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        await assert_payment_schema_ready(conn)
        assert await conn.scalar(text("SHOW transaction_read_only")) == "on"
        assert (await conn.execute(text("SELECT * FROM orders ORDER BY id"))).all() == before
        assert await column_metadata(conn) == before_columns


@pytest.mark.asyncio
async def test_missing_orders_readonly_check_does_not_create_table(payment_schema_db):
    _, conn = payment_schema_db
    async with conn.begin():
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        with pytest.raises(PaymentSchemaNotReady, match="orders"):
            await assert_payment_schema_ready(conn)
        assert await conn.run_sync(lambda sync: inspect(sync).get_table_names()) == []


@pytest.mark.asyncio
async def test_migration_requires_existing_orders_instead_of_creating_financial_data(payment_schema_db):
    _, conn = payment_schema_db
    with pytest.raises(PaymentSchemaNotReady, match="orders"):
        await apply_payment_schema_patches(conn)
    assert await conn.run_sync(lambda sync: inspect(sync).get_table_names()) == []


@pytest.mark.asyncio
async def test_concurrent_migrations_are_serialized_and_preserve_legacy_data(payment_schema_db):
    engine, conn = payment_schema_db
    await create_legacy_orders(conn)
    before = await legacy_rows(conn)
    await conn.commit()

    async def migrate():
        async with engine.begin() as separate:
            await apply_payment_schema_patches(separate)
            await assert_payment_schema_ready(separate)

    await asyncio.gather(*(migrate() for _ in range(3)))
    assert await legacy_rows(conn) == before
    columns = [column["name"] for column in await column_metadata(conn)]
    assert len(columns) == 10
    assert len(set(columns)) == len(columns)
    assert set(PAYMENT_COLUMNS).issubset(columns)
