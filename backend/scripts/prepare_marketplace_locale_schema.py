"""市场中英文兼容迁移：默认只读报告，--apply 要求已有数据库备份。"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys


async def prepare(args):
    """使用独立连接，仅操作市场双语列和历史分类映射。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import get_settings
    from app.marketplace.locale_schema import apply_schema, category_report, check_schema
    engine = create_async_engine(get_settings().database_url, connect_args={"server_settings": {"statement_timeout": "45000"}})
    try:
        async with engine.begin() as connection:
            if args.apply:
                backup = Path(args.backup_file or "")
                if not backup.is_file() or backup.stat().st_size == 0:
                    raise RuntimeError("迁移前须提供非空数据库备份文件 --backup-file。")
                result = await connection.run_sync(apply_schema)
            else:
                missing = await connection.run_sync(check_schema)
                result = {"missing": missing, "categories": await connection.run_sync(category_report)}
                if args.check and missing:
                    raise RuntimeError("缺少双语结构：" + ", ".join(missing))
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


def main():
    """迁移失败返回非零；异常不输出数据库连接凭据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--backup-file")
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    try:
        asyncio.run(prepare(args))
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else "双语迁移失败，请检查数据库连接及结构。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
