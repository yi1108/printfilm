"""把库中仍为 /static 的媒体补传到 OSS 并回写 URL。

用法（在 backend 目录）:
  .\\.venv\\Scripts\\python -m scripts.backfill_oss_media
  .\\.venv\\Scripts\\python -m scripts.backfill_oss_media --dry-run
  .\\.venv\\Scripts\\python -m scripts.backfill_oss_media --limit 100
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


# 解析 CLI 并执行补传
def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill local /static media to OSS")
    parser.add_argument("--limit", type=int, default=500, help="最多处理多少条本地 URL")
    parser.add_argument("--dry-run", action="store_true", help="只列出待补传，不上传")
    args = parser.parse_args()

    from app.logging_setup import configure_logging
    from app.services.oss_queue import backfill_pending_local_media

    configure_logging(level="INFO", sql_echo=False)
    result = asyncio.run(
        backfill_pending_local_media(limit=max(1, args.limit), dry_run=bool(args.dry_run))
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
