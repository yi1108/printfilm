"""Generate drama image-style preview covers via Seedream.

Usage (from backend/):
  .venv\\Scripts\\python.exe -m scripts.gen_image_style_previews

Outputs:
  backend/static/drama/image-styles/{id}.png
  frontend/public/image-styles/{id}.jpg  (copy for static hosting)
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.ark import get_ark
from app.services.drama.image_styles import IMAGE_STYLE_IDS, IMAGE_STYLE_LABELS, IMAGE_STYLE_PROMPTS
from app.services.storage import local_path_from_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gen_style_previews")

BACKEND_DIR = Path(__file__).resolve().parents[1] / "static" / "drama" / "image-styles"
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "image-styles"
SIZE = "2560x1440"
CONCURRENCY = 2


def cover_prompt(style_id: str) -> tuple[str, str]:
    label = IMAGE_STYLE_LABELS.get(style_id, style_id)
    style = IMAGE_STYLE_PROMPTS.get(style_id, "")
    prompt = (
        f"{style}。"
        f"作为「{label}」画面风格的代表预览图，横构图 16:10，"
        f"主体清晰、氛围强烈，适合 UI 风格选择缩略图。"
        f"画面干净，绝对不要出现任何文字、字幕、logo、水印、边框、UI。"
    )
    negative = "文字，字幕，水印，logo，标题字，边框，海报排版，二维码，UI界面"
    return prompt, negative


async def gen_one(sem: asyncio.Semaphore, style_id: str, ark) -> tuple[str, str]:
    dest = BACKEND_DIR / f"{style_id}.png"
    if dest.exists() and dest.stat().st_size > 10_000:
        logger.info("skip existing %s", style_id)
        return style_id, "skip"

    prompt, negative = cover_prompt(style_id)
    async with sem:
        logger.info("generating %s …", style_id)
        try:
            img = await ark.gen_image(
                prompt,
                negative,
                project_id=0,
                shot_no=0,
                size=SIZE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("fail %s: %s", style_id, exc)
            return style_id, str(exc)

    src = local_path_from_url(img.local_url) if img.local_url else None
    if not src or not src.exists():
        return style_id, "missing local file"

    BACKEND_DIR.mkdir(parents=True, exist_ok=True)
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    shutil.copy2(src, FRONTEND_DIR / f"{style_id}.jpg")
    logger.info("saved %s (%s bytes)", style_id, dest.stat().st_size)
    return style_id, "ok"


async def run() -> None:
    settings = get_settings()
    if settings.ark_mock or not settings.ark_api_key:
        raise SystemExit("ARK_MOCK is on or ARK_API_KEY missing — cannot generate style previews")

    ark = get_ark()
    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*[gen_one(sem, sid, ark) for sid in IMAGE_STYLE_IDS])
    for style_id, status in results:
        logger.info("  %s -> %s", style_id, status)


if __name__ == "__main__":
    asyncio.run(run())
