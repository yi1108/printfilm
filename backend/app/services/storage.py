"""Download / persist generated assets under backend/static/generated.

When OSS is enabled:
- Default (async): return /static URL immediately and enqueue upload+DB backfill.
- sync=True: upload inline (template seed, celery unavailable, etc.).
- skip_oss_intermediates(): 科普流水线只上传 final.mp4，分镜图/配音/镜头视频留本地。
FFmpeg always reads local files.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

import httpx

from app.config import get_settings

# 科普成片文件名：仅此文件在 skip_oss_intermediates 下仍入 OSS
_KEPU_FINAL_NAMES = frozenset({"final.mp4"})
# True 时 publish_local 跳过中间文件的异步 OSS 入队
_skip_oss_intermediates: ContextVar[bool] = ContextVar("skip_oss_intermediates", default=False)

logger = logging.getLogger(__name__)

STATIC_ROOT = Path(__file__).resolve().parents[2] / "static"
GENERATED_ROOT = STATIC_ROOT / "generated"


def project_dir(project_id: int) -> Path:
    path = GENERATED_ROOT / f"p{project_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_dir(user_id: int) -> Path:
    path = GENERATED_ROOT / "users" / f"u{user_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def to_public_url(rel_or_abs: str) -> str:
    """Convert /static/... path to absolute URL for frontend."""
    if rel_or_abs.startswith("http://") or rel_or_abs.startswith("https://"):
        return rel_or_abs
    settings = get_settings()
    if not rel_or_abs.startswith("/"):
        rel_or_abs = "/" + rel_or_abs
    return f"{settings.public_base_url.rstrip('/')}{rel_or_abs}"


def local_path_from_url(url: str) -> Path | None:
    """Resolve DB/media URL to a local filesystem path when possible."""
    if not url:
        return None
    if url.startswith("/static/"):
        return STATIC_ROOT / url.removeprefix("/static/")
    settings = get_settings()
    prefix = settings.public_base_url.rstrip("/") + "/static/"
    if url.startswith(prefix):
        return STATIC_ROOT / url.removeprefix(prefix)

    # OSS public URL → kepu/generated/... → static/generated/...
    if url.startswith("http://") or url.startswith("https://"):
        from app.services import oss as oss_svc

        if oss_svc.oss_enabled():
            folder = oss_svc.folder_prefix()
            marker = f"/{folder}/"
            idx = url.find(marker)
            if idx >= 0:
                rest = url[idx + len(marker) :].split("?", 1)[0]
                return STATIC_ROOT / rest
        # Generic: .../generated/pN/...
        marker2 = "/generated/"
        idx2 = url.find(marker2)
        if idx2 >= 0:
            rest = url[idx2 + 1 :].split("?", 1)[0]  # generated/pN/...
            return STATIC_ROOT / rest
    return None


async def download_to(
    url: str,
    dest: Path,
    *,
    timeout: float = 120.0,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def file_to_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def ensure_local_media(url: str, dest: Path) -> Path:
    """If url is remote, download; if already local, copy/resolve."""
    local = local_path_from_url(url)
    if local and local.exists():
        if local.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(local.read_bytes())
        return dest
    if url.startswith("http://") or url.startswith("https://"):
        return await download_to(url, dest)
    raise FileNotFoundError(f"cannot resolve media: {url}")


def rel_static_url(path: Path) -> str:
    rel = path.resolve().relative_to(STATIC_ROOT.resolve())
    return f"/static/{rel.as_posix()}"


def is_local_static_url(url: str | None) -> bool:
    """True when url points at media under backend/static (relative or site /static/).

    HTTPS OSS/CDN 地址即使本地仍保留 FFmpeg 副本，也不算本地 URL。
    """
    if not url:
        return False
    if url.startswith("/static/"):
        return True
    settings = get_settings()
    base = settings.public_base_url.rstrip("/")
    if url.startswith(f"{base}/static/"):
        return True
    # 主站 / 旧站 / 历史拼写错误域名、本地调试地址
    for host in (
        "www.printfilm.com",
        "printfilm.com",
        "kepu.printfilm.com",
        "kepu.printtfilm.com",
        "127.0.0.1:8000",
        "localhost:8000",
    ):
        for scheme in ("https://", "http://"):
            if url.startswith(f"{scheme}{host}/static/"):
                return True
    # 远程 http(s)（含 OSS public_base）一律非本地；勿因磁盘副本误判
    if url.startswith("http://") or url.startswith("https://"):
        return False
    return False


@contextmanager
def skip_oss_intermediates() -> Iterator[None]:
    """科普流水线：中间分镜不入 OSS 队列，成片 final.mp4 仍上传。"""
    token = _skip_oss_intermediates.set(True)
    try:
        yield
    finally:
        _skip_oss_intermediates.reset(token)


F = TypeVar("F", bound=Callable[..., Any])


def without_intermediate_oss(fn: F) -> F:
    """装饰科普入口：调用期间跳过中间文件异步 OSS 上传。"""

    @wraps(fn)
    async def _wrapped(*args: Any, **kwargs: Any):
        with skip_oss_intermediates():
            return await fn(*args, **kwargs)

    return _wrapped  # type: ignore[return-value]


def is_kepu_final_media(path: Path) -> bool:
    """是否为科普最终成片文件（当前仅 final.mp4）。"""
    return Path(path).name.lower() in _KEPU_FINAL_NAMES


def upload_local_sync(path: Path, *, retries: int = 2) -> str:
    """Upload file to OSS synchronously; raises if OSS disabled or all retries fail."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    from app.services import oss as oss_svc

    if not oss_svc.oss_enabled():
        return rel_static_url(path)
    last_err: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return oss_svc.upload_file(path)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning(
                "OSS upload attempt %s/%s failed for %s: %s",
                attempt + 1,
                retries,
                path,
                exc,
            )
    raise RuntimeError(f"OSS upload failed for {path}: {last_err}")


def publish_local(path: Path, *, sync: bool = False, retries: int = 2) -> str:
    """Publish media for the frontend.

    Default: return /static URL immediately; when OSS async is on, enqueue
    upload and DB backfill. Use sync=True for startup seeds or when immediate OSS
    URL is required.

    科普 skip_oss_intermediates 下：非 final.mp4 的异步上传会被跳过；sync=True
    仍上传（Seedance 参考图需要公网 https）。
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    local_url = rel_static_url(path)
    from app.services import oss as oss_svc

    if not oss_svc.oss_enabled():
        return local_url

    # 科普中间文件：异步不入队；显式 sync 仍走公网（方舟拉参考图）
    skip_mid = _skip_oss_intermediates.get() and not is_kepu_final_media(path)
    if skip_mid and not sync:
        return local_url

    settings = get_settings()
    want_async = (
        not sync
        and bool(settings.oss_upload_async)
    )
    if want_async:
        try:
            from app.services.oss_queue import enqueue_oss_upload

            enqueue_oss_upload(local_url)
            return local_url
        except Exception:  # noqa: BLE001
            logger.exception("OSS enqueue failed for %s, falling back to sync upload", path)

    try:
        return upload_local_sync(path, retries=retries)
    except Exception as exc:  # noqa: BLE001
        logger.error("OSS sync upload failed for %s, keeping local URL: %s", path, exc)
        return local_url


def republish_url(url: str | None, *, sync: bool = True) -> str | None:
    """If url is a local /static path and file exists, upload to OSS and return new URL."""
    if not url:
        return url
    if not is_local_static_url(url):
        return url
    from app.services import oss as oss_svc

    if not oss_svc.oss_enabled():
        return url
    local = local_path_from_url(url)
    if not local or not local.is_file():
        logger.warning("cannot republish missing local media: %s", url)
        return url
    return publish_local(local, sync=sync)
