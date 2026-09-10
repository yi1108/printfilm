#!/usr/bin/env python3
"""Upload drama image-style preview images to Aliyun OSS.

Usage (from repo root, with backend venv):
  backend\\.venv\\Scripts\\python deploy/scripts/upload_oss_image_styles.py
  backend\\.venv\\Scripts\\python deploy/scripts/upload_oss_image_styles.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import os

os.chdir(BACKEND)

from app.config import reload_settings  # noqa: E402
from app.services import oss as oss_svc  # noqa: E402

FRONTEND_STYLES = ROOT / "frontend" / "public" / "image-styles"
BACKEND_STYLES = BACKEND / "static" / "drama" / "image-styles"


def upload_glob(local_dir: Path, oss_prefix: str, pattern: str, *, dry_run: bool) -> int:
    """上传目录下匹配 pattern 的文件到 OSS"""
    if not local_dir.is_dir():
        raise SystemExit(f"directory not found: {local_dir}")
    prefix = oss_prefix.strip().strip("/")
    count = 0
    for path in sorted(local_dir.glob(pattern)):
        if not path.is_file():
            continue
        key = f"{prefix}/{path.name}"
        if dry_run:
            print(f"DRY {path} → oss://…/{key} ({path.stat().st_size} bytes)")
        else:
            url = oss_svc.upload_file(path, key)
            print(f"OK {path.name} → {url}")
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload image-style previews to OSS")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    reload_settings()
    if not args.dry_run and not oss_svc.oss_enabled():
        raise SystemExit("OSS not enabled — set OSS_ENABLED=true and credentials in backend/.env")

    folder = oss_svc.folder_prefix()
    print(f"OSS folder prefix: {folder}")

    n_jpg = upload_glob(
        FRONTEND_STYLES,
        f"{folder}/image-styles",
        "*.jpg",
        dry_run=args.dry_run,
    )
    n_png = upload_glob(
        BACKEND_STYLES,
        f"{folder}/drama/image-styles",
        "*.png",
        dry_run=args.dry_run,
    )

    print(f"Done: {n_jpg} jpg (SPA) + {n_png} png (API static)")
    if not args.dry_run and oss_svc.oss_enabled():
        base = oss_svc.public_base()
        print(f"Example: {base}/{folder}/image-styles/ancient-chinese-mythology.jpg")


if __name__ == "__main__":
    main()
