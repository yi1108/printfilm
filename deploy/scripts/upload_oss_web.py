#!/usr/bin/env python3
"""Upload frontend/dist to Aliyun OSS under kepu/ (SPA + assets).

Usage (from repo root, with backend venv):
  backend\\.venv\\Scripts\\python deploy/scripts/upload_oss_web.py
  backend\\.venv\\Scripts\\python deploy/scripts/upload_oss_web.py --dist frontend/dist
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

# Load backend/.env via settings
from app.config import reload_settings  # noqa: E402
from app.services import oss as oss_svc  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload SPA dist to OSS kepu/")
    parser.add_argument("--dist", type=Path, default=ROOT / "frontend" / "dist")
    parser.add_argument(
        "--prefix",
        default=None,
        help="OSS key prefix (default: oss_folder from settings, e.g. kepu)",
    )
    args = parser.parse_args()
    dist: Path = args.dist
    if not dist.is_dir():
        raise SystemExit(f"dist not found: {dist} — run npm run build first")

    reload_settings()
    if not oss_svc.oss_enabled():
        raise SystemExit("OSS not enabled — set OSS_ENABLED=true and credentials in backend/.env")

    prefix = (args.prefix or oss_svc.folder_prefix()).strip().strip("/")
    print(f"Uploading {dist} → oss://{reload_settings().oss_bucket}/{prefix}/")
    n = oss_svc.upload_dir(dist, prefix)
    base = oss_svc.public_base()
    print(f"Uploaded {n} files")
    print(f"Index: {base}/{prefix}/index.html")


if __name__ == "__main__":
    main()
