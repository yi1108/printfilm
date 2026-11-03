"""统一钱包结构和历史回放工具。

默认只读；``--schema`` 只建立新增表，``--apply`` 必须带备份凭证，且所有账户
通过来源回放后才会写入。不会猜测历史余额，也不会自动启动统一钱包开关。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys


async def run(args):
    from sqlalchemy import inspect, select, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import get_settings
    from app.models_tasks import TaskRun
    from app.services.billing.wallet_migration import apply_plans, assert_no_active_tasks, build_report
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
            if args.apply:
                if get_settings().unified_wallet_enabled:
                    raise RuntimeError("切换前必须关闭 UNIFIED_WALLET_ENABLED 并暂停新充值和 AI 任务")
                if not args.backup_file:
                    raise RuntimeError("--apply 必须提供已完成的数据库备份 --backup-file")
                backup = Path(args.backup_file).resolve(strict=True)
                if not backup.is_file() or backup.stat().st_size == 0:
                    raise RuntimeError("备份文件不存在或为空，不能执行切换")
                digest = hashlib.sha256()
                with backup.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                backup_reference = (args.backup_reference or "backup")[:80] + ":" + digest.hexdigest()
                await transaction.execute(text("SET LOCAL lock_timeout = '5s'"))
                await transaction.execute(text("SET LOCAL statement_timeout = '60s'"))
                # 先冻结任务写入，再锁钱包相关表，避免扫描通过后新任务进入。
                await transaction.execute(text("LOCK TABLE task_runs IN SHARE MODE"))
                await transaction.execute(text("LOCK TABLE users, wallet_ledger, orders IN SHARE ROW EXCLUSIVE MODE"))
                tables = await transaction.run_sync(lambda sync: set(inspect(sync).get_table_names()))
                for name in ("marketplace_coin_wallets", "marketplace_coin_lots", "marketplace_coin_allocations",
                             "marketplace_coin_unlocks", "marketplace_apple_transactions"):
                    if name in tables:
                        await transaction.execute(text(f'LOCK TABLE "{name}" IN SHARE ROW EXCLUSIVE MODE'))
            session = AsyncSession(bind=transaction, expire_on_commit=False)
            try:
                await assert_no_active_tasks(session)
                reports, plans = await build_report(session, environment())
                blocked = [row for row in reports if row.get("status") == "blocked"]
                if blocked:
                    print(json.dumps(reports, ensure_ascii=False, indent=2), file=sys.stderr)
                    return 1
                if not args.apply:
                    print(json.dumps(reports, ensure_ascii=False, indent=2))
                    return 0
                await apply_plans(session, plans, environment(), backup_reference)
                await session.flush()
            finally:
                await session.close()
        print("统一钱包历史来源迁移完成；请人工核对报告后再开启 UNIFIED_WALLET_ENABLED。")
        return 0
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--schema", action="store_true", help="建立新增表，不迁移余额")
    mode.add_argument("--check", action="store_true", help="只读结构检查")
    mode.add_argument("--report", action="store_true", help="输出历史核对报告")
    mode.add_argument("--apply", action="store_true", help="应用已通过核对的历史回放")
    parser.add_argument("--backup-file", help="已完成且非空的数据库备份文件；--apply 必填")
    parser.add_argument("--backup-reference", help="可选备份工单编号，与备份 SHA256 一起保留")
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
