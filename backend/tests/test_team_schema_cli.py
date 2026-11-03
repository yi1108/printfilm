"""数据库结构 CLI 的离线回归，不连接数据库或执行真实迁移。"""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import database, main, media_schema, team_schema
from scripts import prepare_team_schema as cli


def stub_engine(dialect="postgresql"):
    """提供记录事务入口的假引擎与假连接，DDL 只由 AsyncMock 接收。"""
    connection = SimpleNamespace(dialect=SimpleNamespace(name=dialect), run_sync=AsyncMock(), execute=AsyncMock())
    entered = []

    @asynccontextmanager
    async def begin():
        """记录真正被选中的引擎，模拟正常结束事务。"""
        entered.append(True)
        yield connection

    return SimpleNamespace(begin=begin, dispose=AsyncMock()), connection, entered


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_init_db_uses_requested_engine_without_replacing_global(monkeypatch, explicit):
    """默认启动入口不变；显式迁移引擎只用于该次初始化。"""
    default, default_connection, default_entered = stub_engine()
    override, override_connection, override_entered = stub_engine()
    monkeypatch.setattr(database, "engine", default)
    await database.init_db(engine_override=override if explicit else None)
    selected = override_connection if explicit else default_connection
    selected.run_sync.assert_awaited_once_with(database.Base.metadata.create_all)
    assert database.engine is default
    assert len(default_entered) == (0 if explicit else 1)
    assert len(override_entered) == (1 if explicit else 0)


@pytest.mark.asyncio
async def test_schema_patches_skip_postgres_ddl_for_sqlite(monkeypatch):
    """SQLite 测试库不执行团队、媒体及市场的 PostgreSQL 增量补列。"""
    engine, connection, entered = stub_engine("sqlite")
    team_patches = AsyncMock()
    media_patches = AsyncMock()
    monkeypatch.setattr(team_schema, "apply_team_schema_patches", team_patches)
    monkeypatch.setattr(media_schema, "apply_media_schema_patches", media_patches)
    monkeypatch.setattr("app.payment_schema.apply_payment_schema_patches", AsyncMock())
    await main._apply_schema_patches(engine_override=engine)
    assert entered == [True]
    team_patches.assert_not_awaited()
    media_patches.assert_not_awaited()
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_schema_patches_use_requested_engine_without_replacing_global(monkeypatch, explicit):
    """补列与团队迁移共享显式引擎，不临时更换应用全局连接池。"""
    default, default_connection, default_entered = stub_engine()
    override, override_connection, override_entered = stub_engine()
    team_patches = AsyncMock()
    media_patches = AsyncMock()
    monkeypatch.setattr(main, "engine", default)
    monkeypatch.setattr(main, "_pg_columns", AsyncMock(return_value=set()))
    monkeypatch.setattr(team_schema, "apply_team_schema_patches", team_patches)
    monkeypatch.setattr(media_schema, "apply_media_schema_patches", media_patches)
    monkeypatch.setattr("app.payment_schema.apply_payment_schema_patches", AsyncMock())
    await main._apply_schema_patches(engine_override=override if explicit else None)
    selected = override_connection if explicit else default_connection
    team_patches.assert_awaited_once_with(selected)
    media_patches.assert_awaited_once_with(selected)
    assert selected.execute.await_count > 0
    assert main.engine is default
    assert len(default_entered) == (0 if explicit else 1)
    assert len(override_entered) == (1 if explicit else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "init", "patch"])
async def test_schema_cli_owns_configured_engine_and_always_disposes(monkeypatch, failure):
    """两个步骤按顺序使用限时迁移连接，任一失败都关闭独立连接池。"""
    from app import config
    from sqlalchemy.ext import asyncio as sqlalchemy_asyncio

    engine, _, _ = stub_engine()
    created = Mock(return_value=engine)
    url = "postgresql+asyncpg://test.invalid/schema_test"
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(database_url=url))
    monkeypatch.setattr(sqlalchemy_asyncio, "create_async_engine", created)
    steps = []
    deadlines = []

    async def init(*, engine_override):
        """模拟建表入口，记录执行顺序并可主动失败。"""
        assert engine_override is engine
        steps.append("init")
        if failure == "init":
            raise RuntimeError("init failed")

    async def patches(*, engine_override):
        """模拟补列入口，确认其复用同一独立引擎。"""
        assert engine_override is engine
        steps.append("patch")
        if failure == "patch":
            raise RuntimeError("patch failed")

    async def limited(awaitable, timeout):
        """仅记录生产超时参数，离线步骤直接执行。"""
        deadlines.append(timeout)
        return await awaitable

    monkeypatch.setattr(database, "init_db", init)
    monkeypatch.setattr(main, "_apply_schema_patches", patches)
    monkeypatch.setattr(cli.asyncio, "wait_for", limited)
    if failure:
        with pytest.raises(RuntimeError, match=failure):
            await cli.prepare()
    else:
        await cli.prepare()
    assert steps == (["init"] if failure == "init" else ["init", "patch"])
    assert deadlines == [60] * len(steps)
    created.assert_called_once_with(url, connect_args={"server_settings": {
        "application_name": "printfilm-team-schema", "jit": "off",
        "statement_timeout": "45000", "idle_in_transaction_session_timeout": "45000",
    }})
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_cli_timeout_cancels_step_before_disposing_engine(monkeypatch):
    """超时会取消在途建表协程，再释放专属连接，避免留下客户端孤儿。"""
    from app import config
    from sqlalchemy.ext import asyncio as sqlalchemy_asyncio

    engine, _, _ = stub_engine()
    cancelled = []
    wait_for = asyncio.wait_for

    async def blocked(*, engine_override):
        """模拟等待数据库响应，在取消时记录 finally 已执行。"""
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(engine_override)

    async def expire(awaitable, timeout):
        """缩短测试等待，但断言 CLI 生产配置仍为六十秒。"""
        assert timeout == 60
        return await wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(database_url="postgresql+asyncpg://test.invalid/schema_test"))
    monkeypatch.setattr(sqlalchemy_asyncio, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(database, "init_db", blocked)
    monkeypatch.setattr(cli.asyncio, "wait_for", expire)
    patches = AsyncMock()
    monkeypatch.setattr(main, "_apply_schema_patches", patches)
    with pytest.raises(TimeoutError):
        await cli.prepare()
    assert cancelled == [engine]
    patches.assert_not_awaited()
    engine.dispose.assert_awaited_once()
