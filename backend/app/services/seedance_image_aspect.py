"""Seedance 参考图宽高比钳制：上游要求约 0.40–2.50，边界/略超会被拒。"""

from __future__ import annotations

import asyncio
import logging
import math
import subprocess
import uuid
from pathlib import Path

from PIL import Image

from app.services.ffmpeg_compose import _which

logger = logging.getLogger(__name__)

# 官方口径 [0.40, 2.50]；实测 1983×793≈2.5006 会被报成 2.50 并拒绝
SEEDANCE_AR_MIN = 0.40
SEEDANCE_AR_MAX = 2.50
SEEDANCE_AR_SAFE_MIN = 0.41
SEEDANCE_AR_SAFE_MAX = 2.49


# 计算 letterbox 后的画布尺寸（只垫黑边、不裁切）
def target_canvas_for_seedance_ar(
    width: int,
    height: int,
    *,
    ar_min: float = SEEDANCE_AR_SAFE_MIN,
    ar_max: float = SEEDANCE_AR_SAFE_MAX,
) -> tuple[int, int] | None:
    """若已在安全区间返回 None；否则返回需 pad 到的 (canvas_w, canvas_h)。"""
    w = int(width)
    h = int(height)
    if w <= 0 or h <= 0:
        return None
    ar = w / h
    if ar_min <= ar <= ar_max:
        return None
    if ar > ar_max:
        canvas_w, canvas_h = w, max(h, int(math.ceil(w / ar_max)))
    else:
        canvas_w, canvas_h = max(w, int(math.ceil(h * ar_min))), h
    # 偶数字对齐后可能把 AR 推回 2.50/0.40 边界，循环微调直到落在安全区
    for _ in range(16):
        if canvas_w % 2:
            canvas_w += 1
        if canvas_h % 2:
            canvas_h += 1
        out_ar = canvas_w / canvas_h
        if ar_min <= out_ar <= ar_max:
            break
        if out_ar > ar_max:
            canvas_h += 2
        else:
            canvas_w += 2
    else:
        logger.warning(
            "seedance ar: cannot stabilize canvas for %sx%s",
            w,
            h,
        )
        return None
    if canvas_w == w and canvas_h == h:
        return None
    return canvas_w, canvas_h


# 从文件头读宽高（PNG / JPEG / WEBP）
def read_image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, Image.DecompressionBombError):
        return None


def _run_ffmpeg_pad(src: Path, dest: Path, cw: int, ch: int) -> None:
    ffmpeg = _which("ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:black"
    cmd = [ffmpeg, "-y", "-i", str(src), "-vf", vf, str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size <= 0:
        raise RuntimeError(
            f"seedance ar pad failed: {(proc.stderr or '')[-400:] or 'empty output'}"
        )


# 本地图若超 Seedance 比例，FFmpeg 居中垫黑边写出新文件
def pad_image_to_seedance_ar(src: Path, dest: Path) -> Path | None:
    """需要钳制时写出 dest 并返回路径；无需改动返回 None；失败抛 RuntimeError。"""
    dims = read_image_size(src)
    if not dims:
        raise RuntimeError(f"无法读取参考图尺寸：{src.name}")
    canvas = target_canvas_for_seedance_ar(*dims)
    if not canvas:
        return None
    cw, ch = canvas
    _run_ffmpeg_pad(src, dest, cw, ch)
    out_dims = read_image_size(dest)
    if out_dims:
        out_ar = out_dims[0] / out_dims[1]
        if not (SEEDANCE_AR_SAFE_MIN <= out_ar <= SEEDANCE_AR_SAFE_MAX):
            raise RuntimeError(
                f"垫边后宽高比仍超限：{out_dims[0]}x{out_dims[1]} ar={out_ar:.4f}"
            )
    logger.info(
        "seedance ar padded %sx%s -> %sx%s src=%s",
        dims[0],
        dims[1],
        cw,
        ch,
        src.name,
    )
    return dest


# 确保参考图比例可被 Seedance 接受；必要时本地垫边并同步 OSS
async def ensure_seedance_compatible_image_url(image_url: str) -> str:
    from app.services import storage

    raw = (image_url or "").strip()
    if not raw:
        return raw

    local = storage.local_path_from_url(raw)
    work_dir = storage.GENERATED_ROOT / "_seedance_ar"
    if not local or not local.exists():
        if not raw.startswith(("http://", "https://")):
            return raw
        work_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(raw.split("?", 1)[0]).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        local = work_dir / f"dl_{uuid.uuid4().hex[:12]}{suffix}"
        try:
            await storage.download_to(raw, local)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"下载参考图失败，无法校验宽高比：{exc}") from exc

    dims = read_image_size(local)
    if not dims:
        # 读不出尺寸时不硬失败（SVG/少见格式），交给上游
        logger.warning("seedance ar: cannot read size, pass-through path=%s", local)
        return raw
    if target_canvas_for_seedance_ar(*dims) is None:
        return raw

    out = local.parent / f"{local.stem}_ar{uuid.uuid4().hex[:8]}{local.suffix or '.png'}"
    try:
        padded = await asyncio.to_thread(pad_image_to_seedance_ar, local, out)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"参考图宽高比超限且垫边失败：{exc}") from exc
    if not padded:
        return raw

    local_url = storage.rel_static_url(padded)
    public = storage.republish_url(local_url, sync=True)
    if public and str(public).startswith(("http://", "https://", "/static/")):
        return str(public)
    return local_url
