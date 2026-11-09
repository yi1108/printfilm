"""App 发布迁移：瞬态 DNS 重试、有限次数及脱敏诊断。"""
import asyncio
from contextlib import asynccontextmanager
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import config
from scripts import prepare_marketplace_app_schema as cli


@pytest.mark.asyncio
async def test_prepare_retries_temporary_dns_failure(monkeypatch):
    """数据库服务名前两次未解析时等待恢复，第三次成功后执行只读检查。"""
    attempts = 0
    connection = SimpleNamespace(run_sync=AsyncMock(return_value=[]))

    @asynccontextmanager
    async def begin():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            error = RuntimeError("wrapped database DNS failure")
            error.__cause__ = socket.gaierror(-2, "Name or service not known")
            raise error
        yield connection

    engine = SimpleNamespace(begin=begin, dispose=AsyncMock())
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://user:secret-password@postgres:5432/printfilm_test"),
    )
    from sqlalchemy.ext import asyncio as sqlalchemy_asyncio
    monkeypatch.setattr(sqlalchemy_asyncio, "create_async_engine", Mock(return_value=engine))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    await cli.prepare(check=True)

    assert attempts == 3
    assert sleep.await_count == 2
    connection.run_sync.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_prepare_does_not_retry_permanent_schema_error(monkeypatch):
    """缺少前置表属于确定性结构错误，不应进行无意义的连接重试。"""
    attempts = 0

    @asynccontextmanager
    async def begin():
        nonlocal attempts
        attempts += 1
        raise RuntimeError("请先初始化原数字资产市场表")
        yield

    engine = SimpleNamespace(begin=begin, dispose=AsyncMock())
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(database_url="postgresql+asyncpg://postgres/db"))
    from sqlalchemy.ext import asyncio as sqlalchemy_asyncio
    monkeypatch.setattr(sqlalchemy_asyncio, "create_async_engine", Mock(return_value=engine))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    with pytest.raises(RuntimeError, match="请先初始化"):
        await cli.prepare()

    assert attempts == 1
    sleep.assert_not_awaited()
    engine.dispose.assert_awaited_once()


def test_cli_reports_safe_database_target_without_credentials(monkeypatch, capsys):
    """DNS 失败显示主机、端口和库名，但绝不输出连接用户名或密码。"""
    monkeypatch.setattr(cli, "prepare", AsyncMock(side_effect=socket.gaierror(-2, "Name or service not known")))
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql+asyncpg://private-user:private-password@postgres:5432/printfilm_test"),
    )

    assert cli.main(["--check"]) == 1
    output = capsys.readouterr().err
    assert "gaierror" in output
    assert "postgres:5432/printfilm_test" in output
    assert "private-user" not in output
    assert "private-password" not in output
