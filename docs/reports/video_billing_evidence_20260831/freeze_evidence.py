#!/usr/bin/env python3
"""将 .tmp/video_billing_report 关键产物复制到 docs/reports 固定证据目录。"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / ".tmp" / "video_billing_report"
DST = Path(__file__).resolve().parent

COPY_FILES = [
    "aug26_27_analysis.json",
    "user_2929455133_aug26_27.json",
    "meta_20260831_1044.json",
    "video_billing_20260831_1044.xlsx",
    "video_tasks_20260831_1044.csv",
    "video_usage_20260831_1044.csv",
    "video_billing_analysis.html",
    "aug26_27_cost_analysis.html",
]

COPY_DIRS = [
    ("charts_20260831_1044", "charts"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    for name in COPY_FILES:
        src = SRC / name
        if not src.exists():
            print(f"SKIP missing: {src}")
            continue
        dst_name = "meta_export.json" if name.startswith("meta_") else name
        dst = DST / dst_name
        shutil.copy2(src, dst)
        manifest.append({"file": dst_name, "bytes": dst.stat().st_size, "sha256": sha256(dst)})
        print(f"copied {dst_name}")

    for src_dir, dst_dir in COPY_DIRS:
        src = SRC / src_dir
        dst = DST / dst_dir
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst)
            for p in sorted(dst.rglob("*")):
                if p.is_file():
                    rel = p.relative_to(DST).as_posix()
                    manifest.append({"file": rel, "bytes": p.stat().st_size, "sha256": sha256(p)})
            print(f"copied dir {dst_dir}/")

    out = {
        "frozen_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "source_dir": str(SRC),
        "evidence_dir": str(DST),
        "files": manifest,
    }
    (DST / "MANIFEST.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {DST / 'MANIFEST.json'} ({len(manifest)} files)")


if __name__ == "__main__":
    main()
