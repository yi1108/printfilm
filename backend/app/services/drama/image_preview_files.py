"""Keep generated image-style preview filenames aligned with their bytes."""

from __future__ import annotations

import shutil
from pathlib import Path


def detect_preview_extension(path: Path) -> str:
    """Return the supported preview extension from the file signature."""
    with path.open("rb") as image_file:
        header = image_file.read(8)

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise ValueError(f"unsupported preview image format: {path}")


def _copy_unless_same(source: Path, destination: Path) -> None:
    """Copy a preview unless it already occupies the destination path."""
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def write_preview_pair(
    source: Path,
    style_id: str,
    backend_dir: Path,
    frontend_dir: Path,
) -> str:
    """Copy one image to both preview roots using its actual format suffix."""
    extension = detect_preview_extension(source)
    backend_dir.mkdir(parents=True, exist_ok=True)
    frontend_dir.mkdir(parents=True, exist_ok=True)

    backend_path = backend_dir / f"{style_id}{extension}"
    frontend_path = frontend_dir / f"{style_id}{extension}"
    _copy_unless_same(source, backend_path)
    _copy_unless_same(source, frontend_path)

    for stale_extension in (".png", ".jpg"):
        if stale_extension == extension:
            continue
        (backend_dir / f"{style_id}{stale_extension}").unlink(missing_ok=True)
        (frontend_dir / f"{style_id}{stale_extension}").unlink(missing_ok=True)

    return extension


def repair_cached_preview_pair(
    style_id: str,
    backend_dir: Path,
    frontend_dir: Path,
    min_size: int = 10_001,
) -> str | None:
    """Repair and reuse an existing backend preview when its signature is known."""
    for extension in (".png", ".jpg"):
        cached = backend_dir / f"{style_id}{extension}"
        if not cached.is_file() or cached.stat().st_size < min_size:
            continue
        try:
            detect_preview_extension(cached)
        except (OSError, ValueError):
            continue
        return write_preview_pair(cached, style_id, backend_dir, frontend_dir)
    return None
