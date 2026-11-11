"""Migrate saved legacy project canvases. Default: read-only preview.

Run from any directory; configuration is loaded from backend/.env.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--project-id", type=int, action="append", help="Repeat for selected projects")
    scope.add_argument("--all", action="store_true", help="Preview/migrate projects with saved legacy nodes")
    scope.add_argument("--restore", type=Path, help="Restore the target from one migration backup")
    scope.add_argument("--verify-backups", type=Path, help="Read-only verification of all backup JSON files in this directory")
    parser.add_argument("--apply", action="store_true", help="Write changes; otherwise preview only")
    parser.add_argument("--repair-legacy", action="store_true", help="Repair duplicate IDs and confirmed deleted asset references in the new copy only")
    parser.add_argument("--report", type=Path, help="Write JSONL results to a new file (refuses to overwrite)")
    parser.add_argument("--backup-dir", type=Path, default=BACKEND.parent / ".tmp" / "legacy-canvas-backups")
    return parser.parse_args()


async def run(args):
    # Resolve user paths before changing directory for the app's dotenv loading.
    backup_dir = args.backup_dir.resolve()
    restore_path = args.restore.resolve() if args.restore else None
    verify_dir = args.verify_backups.resolve() if args.verify_backups else None
    report_path = args.report.resolve() if args.report else None
    if verify_dir and args.apply:
        raise ValueError("--verify-backups is read-only; do not combine with --apply")
    os.chdir(BACKEND)
    from sqlalchemy import select, text
    from app.database import AsyncSessionLocal, engine
    from app.printfilm_studio.canvas.legacy_migration import PROJECT, migrate_project, restore_project, verify_backup

    report_stream = None

    def emit(report):
        line = json.dumps(report, ensure_ascii=False)
        if report_stream:
            report_stream.write(line + "\n")
            report_stream.flush()
            os.fsync(report_stream.fileno())
        print(line, flush=True)

    def write_backup(payload):
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = backup_dir / f"project-{payload['project_id']}-{stamp}-{uuid.uuid4().hex[:8]}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        return path

    try:
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_stream = report_path.open("x", encoding="utf-8")
        if verify_dir:
            backups = sorted(verify_dir.glob("project-*.json"))
            if not backups:
                raise ValueError("no project backups found in verification directory")
            errors = 0
            for path in backups:
                backup = json.loads(path.read_text(encoding="utf-8"))
                async with AsyncSessionLocal.begin() as db:
                    await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                    report = await verify_backup(db, backup)
                emit(report)
                errors += report["status"] != "verified"
            return 1 if errors else 0
        if restore_path:
            if not args.apply:
                raise ValueError("restore requires --apply; it refuses targets edited after migration")
            backup = json.loads(restore_path.read_text(encoding="utf-8"))
            async with AsyncSessionLocal.begin() as db:
                report = await restore_project(db, backup)
            emit(report)
            return
        ids = sorted(set(args.project_id or []))
        if args.all:
            async with AsyncSessionLocal.begin() as db:
                await db.execute(text("SET TRANSACTION READ ONLY"))
                rows = (await db.execute(select(PROJECT.c.id, PROJECT.c.content))).mappings()
                ids = sorted(row["id"] for row in rows if isinstance(row["content"], dict) and row["content"].get("canvas_nodes"))
        errors = 0
        for project_id in ids:
            try:
                async with AsyncSessionLocal.begin() as db:
                    if not args.apply:
                        await db.execute(text("SET TRANSACTION READ ONLY"))
                    else:
                        await db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    report = await migrate_project(db, project_id, apply=args.apply, write_backup=write_backup, repair_legacy=args.repair_legacy)
            except ValueError as exc:
                errors += 1
                report = {"project_id": project_id, "status": "invalid_source", "error": str(exc)}
            # Only print after commit, with no prompts, media URLs or credentials.
            emit(report)
        return 1 if errors else 0
    finally:
        if report_stream:
            report_stream.close()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(run(arguments())))
