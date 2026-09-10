"""Generate template preview covers via Seedream (image model).

Usage (from backend/):
  .venv\\Scripts\\python.exe -m scripts.gen_template_covers
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

# Allow `python -m scripts.gen_template_covers` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Template
from app.services.ark import get_ark
from app.services.storage import local_path_from_url
from app.services.templates_seed import TEMPLATES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gen_covers")

COVER_DIR = Path(__file__).resolve().parents[1] / "static" / "templates" / "covers"
SIZE = "2560x1440"  # 16:9, meets Seedream min pixels
CONCURRENCY = 3


def cover_prompt(tpl: dict) -> tuple[str, str]:
    name = tpl["name"]
    style = tpl.get("style_prefix") or ""
    cats = "、".join(tpl.get("category") or [])
    prompt = (
        f"{style}。"
        f"作为「{name}」风格模板的封面代表画面，横构图 16:9，"
        f"主体清晰、氛围强烈，适合作为风格预览缩略图。"
        f"分类气质：{cats}。"
        f"画面干净，绝对不要出现任何文字、字幕、logo、水印、边框、UI。"
    )
    negative = (
        f"{tpl.get('negative_prompt') or ''}，"
        "文字，字幕，水印，logo，标题字，边框，海报排版，二维码"
    )
    return prompt, negative


async def gen_one(sem: asyncio.Semaphore, tpl: dict, ark) -> tuple[str, Path | None, str]:
    tid = tpl["id"]
    dest = COVER_DIR / f"{tid}.png"
    if dest.exists() and dest.stat().st_size > 10_000:
        logger.info("skip existing %s", tid)
        return tid, dest, "skip"

    prompt, negative = cover_prompt(tpl)
    async with sem:
        logger.info("generating %s …", tid)
        try:
            img = await ark.gen_image(
                prompt,
                negative,
                project_id=0,
                shot_no=0,
                size=SIZE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("fail %s: %s", tid, exc)
            return tid, None, str(exc)

    src = local_path_from_url(img.local_url) if img.local_url else None
    if not src or not src.exists():
        return tid, None, "missing local file"
    COVER_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    logger.info("saved %s (%s bytes)", dest.name, dest.stat().st_size)
    return tid, dest, "ok"


async def run() -> None:
    settings = get_settings()
    if settings.ark_mock or not settings.ark_api_key:
        raise SystemExit("ARK_MOCK is on or ARK_API_KEY missing — cannot generate covers")

    COVER_DIR.mkdir(parents=True, exist_ok=True)
    ark = get_ark()
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*[gen_one(sem, t, ark) for t in TEMPLATES])

    # Patch seed file preview paths in DB
    engine = create_engine(settings.database_url_sync)
    ok = 0
    with Session(engine) as db:
        for tid, dest, status in results:
            if not dest or not dest.exists():
                continue
            rel = f"/static/templates/covers/{tid}.png"
            row = db.get(Template, tid)
            if row:
                row.preview_cover = rel
                ok += 1
            # also update in-memory seed for next restart consistency
            for t in TEMPLATES:
                if t["id"] == tid:
                    t["preview_cover"] = rel
        db.commit()
        total = len(db.scalars(select(Template)).all())
    logger.info("covers ready: %s/%s templates (db rows=%s)", ok, len(TEMPLATES), total)
    for tid, dest, status in results:
        logger.info("  %s -> %s", tid, status)


if __name__ == "__main__":
    asyncio.run(run())
