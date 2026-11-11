"""统一钱包结构和历史回放工具。

默认只读；``--schema`` 只建立新增表。资金写入已统一到后台迁移入口，
旧 ``--apply`` 明确拒绝，避免绕过维护锁、逐户确认及备份审计。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


async def run(args):
    if args.apply:
        raise RuntimeError("旧命令行资金写入已停用；请使用系统管理 → 支付与通知 → 统一钱包迁移与核对，完成暂停、逐户确认和备份后迁移。")
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import get_settings
    from app.services.billing.wallet_migration import build_report
    from app.services.billing.wallet_schema import apply_schema, check_schema
    from app.services.billing.wallet_base import environment

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        if args.schema:
            async with engine.begin() as connection:
                await connection.run_sync(apply_schema)
            print("统一钱包新增表已建立，尚未迁移历史余额。")
            return 0
        async with engine.connect() as connection:
            missing = await connection.run_sync(check_schema)
        if missing:
            print("统一钱包结构未就绪：" + ", ".join(missing), file=sys.stderr)
            return 1
        if args.check:
            print("统一钱包结构检查通过。")
            return 0
        async with engine.begin() as transaction:
            from sqlalchemy.ext.asyncio import AsyncSession
            session = AsyncSession(bind=transaction, expire_on_commit=False)
            try:
                reports, _ = await build_report(session, environment())
                blocked = [row for row in reports if row.get("status") == "blocked" or row.get("approval_status") == "required"]
                if blocked:
                    print(json.dumps(reports, ensure_ascii=False, indent=2), file=sys.stderr)
                    return 1
                print(json.dumps(reports, ensure_ascii=False, indent=2))
                return 0
            finally:
                await session.close()
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--schema", action="store_true", help="建立新增表，不迁移余额")
    mode.add_argument("--check", action="store_true", help="只读结构检查")
    mode.add_argument("--report", action="store_true", help="输出历史核对报告")
    mode.add_argument("--apply", action="store_true", help="已停用；资金写入请使用后台迁移入口")
    parser.add_argument("--backup-file", help="旧参数保留兼容；--apply 已停用")
    parser.add_argument("--backup-reference", help="旧参数保留兼容；资金操作请使用后台")
    args = parser.parse_args()
    if not (args.schema or args.check or args.report or args.apply):
        parser.error("请选择 --schema、--check、--report 或 --apply")
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.getcwd())
    try:
        return asyncio.run(run(args))
    except Exception as error:  # noqa: BLE001
        message = str(error) if isinstance(error, RuntimeError) else "请检查数据库结构和连接，未自动改写来源或余额。"
        print(f"统一钱包操作失败（{type(error).__name__}）：{message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
