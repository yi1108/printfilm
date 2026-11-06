"""PostgreSQL 钱包写锁应串行化扣款，同时允许用量外键校验。"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models_teams  # noqa: F401
from app.config import get_settings
from app.models import User
from app.models_wallet import WalletAccount
from app.services.billing import wallet_base
from app.services.billing.settlement import _lock_user
from tests.conftest import _ensure_test_database, _resolve_test_database_url


@pytest.mark.parametrize("unified", [False, True])
async def test_wallet_lock_allows_usage_fk_and_still_serializes_writers(monkeypatch, unified):
    """独立测试库和临时 schema，不接触业务表；复现线上 users 外键锁冲突。"""
    url, name = _resolve_test_database_url(get_settings().database_url)
    await _ensure_test_database(url, name)
    schema = "wallet_lock_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(wallet_base, "enabled", lambda: unified)
    monkeypatch.setattr("app.services.billing.wallet.enabled", lambda: unified)
    monkeypatch.setattr(wallet_base, "environment", lambda value=None: "Production")
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as conn:
            await conn.run_sync(User.__table__.create)
            await conn.run_sync(WalletAccount.__table__.create)
            await conn.execute(text("CREATE TABLE usage_fk_probe (user_id integer REFERENCES users(id))"))
        async with sessions() as db:
            db.add(User(id=1, email="lock@test.local", hashed_password="unused", balance_fen=1000))
            await db.flush()
            if unified:
                db.add(WalletAccount(user_id=1, environment="Production"))
            await db.commit()
        async with sessions() as wallet, sessions() as usage, sessions() as contender:
            owner = await _lock_user(wallet, 1)
            owner.balance_fen -= 100
            await wallet.flush()
            await usage.execute(text("SET LOCAL lock_timeout = '300ms'"))
            # usage_events INSERT 对 users.id 的外键检查需要 KEY SHARE。
            await usage.execute(text("INSERT INTO usage_fk_probe (user_id) VALUES (1)"))
            await usage.commit()
            await contender.execute(text("SET LOCAL lock_timeout = '300ms'"))
            with pytest.raises(DBAPIError) as error:
                await _lock_user(contender, 1)
            assert error.value.orig.sqlstate == "55P03"
            await contender.rollback()
            await wallet.commit()
            owner = await _lock_user(contender, 1)
            assert owner.balance_fen == 900
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
