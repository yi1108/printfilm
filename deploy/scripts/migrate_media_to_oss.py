#!/usr/bin/env python3
"""Upload local /static media to OSS and rewrite DB URLs.

Usage (on server, from backend venv):
  cd /opt/ai_movie/backend && .venv/bin/python /opt/ai_movie/deploy/scripts/migrate_media_to_oss.py
  .venv/bin/python .../migrate_media_to_oss.py --dry-run
  .venv/bin/python .../migrate_media_to_oss.py --enqueue
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.config import reload_settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import Project, Shot, Template  # noqa: E402
from app.services import oss as oss_svc  # noqa: E402
from app.services import storage  # noqa: E402
from app.services.oss_queue import enqueue_oss_upload  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("migrate_oss")


def maybe_republish(url: str | None, *, dry_run: bool, enqueue: bool) -> tuple[str | None, bool]:
    if not url or not storage.is_local_static_url(url):
        return url, False
    local = storage.local_path_from_url(url)
    if not local or not local.is_file():
        log.warning("skip missing file for %s", url)
        return url, False
    if dry_run:
        log.info(
            "DRY would %s %s (%s bytes)",
            "enqueue" if enqueue else "upload",
            local,
            local.stat().st_size,
        )
        return url, True
    if enqueue:
        enqueue_oss_upload(url)
        return url, True
    new_url = storage.publish_local(local, sync=True)
    changed = new_url != url and not storage.is_local_static_url(new_url)
    if changed:
        log.info("%s → %s", url, new_url)
    else:
        log.warning("still local after publish: %s", url)
    return new_url, changed


async def run(*, dry_run: bool, enqueue: bool) -> None:
    reload_settings()
    if not oss_svc.oss_enabled():
        raise SystemExit("OSS not enabled")

    changed = 0
    async with AsyncSessionLocal() as db:
        for tpl in (await db.execute(select(Template))).scalars().all():
            new_url, did = maybe_republish(tpl.preview_cover, dry_run=dry_run, enqueue=enqueue)
            if did and not dry_run and not enqueue and new_url:
                tpl.preview_cover = new_url
                changed += 1

        for p in (await db.execute(select(Project))).scalars().all():
            for field in ("cover_url", "final_video_url", "ref_image_url"):
                old = getattr(p, field)
                new_url, did = maybe_republish(old, dry_run=dry_run, enqueue=enqueue)
                if did and not dry_run and not enqueue:
                    setattr(p, field, new_url)
                    changed += 1

        for s in (await db.execute(select(Shot))).scalars().all():
            for field in ("image_url", "video_url", "audio_url"):
                old = getattr(s, field)
                new_url, did = maybe_republish(old, dry_run=dry_run, enqueue=enqueue)
                if did and not dry_run and not enqueue:
                    setattr(s, field, new_url)
                    changed += 1

        if dry_run:
            log.info("dry-run complete (no DB writes)")
        elif enqueue:
            await db.rollback()
            log.info("enqueued local media for async OSS upload+backfill")
        else:
            await db.commit()
            log.info("updated %s URL fields", changed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate /static media URLs to OSS")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="Enqueue Celery oss uploads instead of sync upload+DB write",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, enqueue=args.enqueue))


if __name__ == "__main__":
    main()
