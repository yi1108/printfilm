"""一次性修复超长 reference_audio（截断至 15s 并回写绑定）。

用法（在 backend 目录）:
  .\\.venv\\Scripts\\python -m scripts.backfill_voice_reference_audio
  .\\.venv\\Scripts\\python -m scripts.backfill_voice_reference_audio --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def _run(*, dry_run: bool, limit: int) -> dict:
    from app import models  # noqa: F401
    from app import models_drama  # noqa: F401
    from app.database import AsyncSessionLocal
    from app.services.drama.voice_reference_audio import backfill_long_voice_references

    async with AsyncSessionLocal() as db:
        return await backfill_long_voice_references(db, dry_run=dry_run, limit=limit)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill long voice reference audio")
    parser.add_argument("--limit", type=int, default=2000, help="每类资产最多处理条数")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    args = parser.parse_args()

    from app.logging_setup import configure_logging

    configure_logging(level="INFO", sql_echo=False)
    result = asyncio.run(_run(dry_run=bool(args.dry_run), limit=max(1, args.limit)))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
