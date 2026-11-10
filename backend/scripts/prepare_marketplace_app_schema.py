"""显式建立 App 独立表；--check 严格只读。"""
import argparse
import asyncio
import os
from pathlib import Path
import socket
import sys

CONNECT_ATTEMPTS = 5


def _is_transient_connection_error(error: BaseException) -> bool:
    """识别 SQLAlchemy 异常链中的 DNS、连接及超时错误，避免重试结构错误。"""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (socket.gaierror, ConnectionError, TimeoutError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _database_target() -> str:
    """只返回脱敏的主机、端口和库名，用于容器网络故障诊断。"""
    from sqlalchemy.engine.url import make_url
    from app.config import get_settings

    url = make_url(get_settings().database_url)
    return f"{url.host or '127.0.0.1'}:{url.port or 5432}/{url.database or ''}"


async def prepare(check=False):
    """独立连接限定 DDL 时长；数据库 DNS/连接暂未就绪时进行有限重试。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import get_settings
    from app.marketplace.app_schema import apply_schema, check_schema

    engine = create_async_engine(get_settings().database_url, connect_args={
        "timeout": 10,
        "server_settings": {
            "application_name": "printfilm-marketplace-app-schema",
            "statement_timeout": "45000",
            "idle_in_transaction_session_timeout": "45000",
        },
    })
    try:
        for attempt in range(CONNECT_ATTEMPTS):
            try:
                async with engine.begin() as connection:
                    if check:
                        missing = await connection.run_sync(check_schema)
                        if missing:
                            raise RuntimeError("缺少结构：" + ", ".join(missing))
                    else:
                        await connection.run_sync(apply_schema)
                break
            except Exception as error:
                if not _is_transient_connection_error(error) or attempt + 1 >= CONNECT_ATTEMPTS:
                    raise
                # Compose 启动时 DNS 和 PostgreSQL 可能尚未就绪；退避有上限，不无限等待。
                await asyncio.sleep(min(2 ** attempt, 8))
    finally:
        await engine.dispose()


def main(argv=None):
    """错误不输出数据库凭据，调用方可通过退出码阻止发布。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只读验证，绝不建表或修改记录")
    args = parser.parse_args(argv)
    backend = Path(__file__).resolve().parents[1]
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    target = "未知"
    try:
        target = _database_target()
        action = "检查" if args.check else "迁移"
        print(f"开始 App 数据库结构{action}，目标 {target}。", flush=True)
        asyncio.run(prepare(args.check))
    except Exception as error:
        if isinstance(error, RuntimeError) and not _is_transient_connection_error(error):
            reason = str(error)
        else:
            reason = f"数据库目标 {target}；请检查数据库服务名、容器网络与结构。"
        print(f"App数据库结构未就绪（{type(error).__name__}）：{reason}", file=sys.stderr)
        return 1
    print("App数据库结构检查通过。" if args.check else "App新增表迁移及结构检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
