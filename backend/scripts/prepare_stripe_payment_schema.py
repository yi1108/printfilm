"""关闭自动建表时使用的独立充值订单迁移；不执行其他迁移或种子数据。"""
import argparse
import asyncio
import os
from pathlib import Path
import sys


async def prepare(*, check_only: bool = False) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import get_settings
    from app.payment_schema import apply_payment_schema_patches, assert_payment_schema_ready

    engine = create_async_engine(get_settings().database_url, connect_args={"server_settings": {
        "application_name": "printfilm-stripe-payment-schema", "jit": "off",
        "statement_timeout": "45000", "idle_in_transaction_session_timeout": "45000",
        "lock_timeout": "10000",
    }})
    try:
        async with engine.begin() as conn:
            if check_only:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
            else:
                await apply_payment_schema_patches(conn)
            await assert_payment_schema_ready(conn)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Stripe 订单增量迁移（仅添加可空快照字段）")
    parser.add_argument("--check", action="store_true", help="只读校验结构，缺失时退出码为 1")
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    from app.payment_schema import PaymentSchemaNotReady
    try:
        asyncio.run(prepare(check_only=args.check))
    except PaymentSchemaNotReady as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"充值订单结构准备失败（{type(exc).__name__}），请检查本地数据库配置。", file=sys.stderr)
        return 1
    print("充值订单结构检查通过。" if args.check else "充值订单结构已就绪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
