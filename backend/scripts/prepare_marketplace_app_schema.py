"""显式建立 App 独立表；--check 严格只读。"""
import argparse
import asyncio
import os
from pathlib import Path
import sys


async def prepare(check=False):
    """独立连接限定DDL时长，不启动媒体Worker或外部支付。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import get_settings
    from app.marketplace.app_schema import apply_schema, check_schema
    engine = create_async_engine(get_settings().database_url, connect_args={"server_settings": {
        "application_name": "printfilm-marketplace-app-schema", "statement_timeout": "45000", "idle_in_transaction_session_timeout": "45000"}})
    try:
        async with engine.begin() as connection:
            if check:
                missing = await connection.run_sync(check_schema)
                if missing:
                    raise RuntimeError("缺少结构：" + ", ".join(missing))
            else:
                await connection.run_sync(apply_schema)
    finally:
        await engine.dispose()


def main():
    """错误不输出数据库凭据，调用方可通过退出码阻止发布。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只读验证，绝不建表或修改记录")
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    try:
        asyncio.run(prepare(args.check))
    except Exception as error:
        reason = str(error) if isinstance(error, RuntimeError) else "请检查数据库连接与结构；不会输出连接凭据。"
        print(f"App数据库结构未就绪（{type(error).__name__}）：{reason}", file=sys.stderr)
        return 1
    print("App数据库结构检查通过。" if args.check else "App新增表迁移及结构检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
