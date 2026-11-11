"""Combine authorized project assets and delivered standalone tool results."""
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Project, ToolRun
from app.models_drama import DramaAsset, DramaProject
from app.models_tasks import TaskRun
from app.schemas_media_library import LibraryGenerationStatus, MediaLibraryItem, MediaLibraryMeta, MediaLibraryPage
from app.services.drama.workflow import resolve_drama_workflow
from app.services.drama.media_library_video import deduplicate_videos, task_project, video_items
from app.services.drama.media_library_references import hydrate_library_references
from app.services.tasks.generation_references import public_references
from app.services.tasks.generation_history import _safe_url, _tool_link


_MEDIA_EXTENSIONS = {
    "image": frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".svg", ".tif", ".tiff", ".heic"}),
    "video": frozenset({".mp4", ".webm", ".mov", ".m4v", ".mkv", ".avi", ".m3u8"}),
    "audio": frozenset({".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus", ".webm"}),
}
_KNOWN_MEDIA_EXTENSIONS = frozenset().union(*_MEDIA_EXTENSIONS.values())


def has_generated_media(item: MediaLibraryItem) -> bool:
    """Count only the current formal media field, independent of provenance or task status."""
    candidates = (item.url, item.cover) if item.media_kind == "image" else (item.url,)
    for value in candidates:
        url = _safe_url(value)
        if not url:
            continue
        suffix = PurePosixPath(urlsplit(url).path).suffix.casefold()
        if suffix in _KNOWN_MEDIA_EXTENSIONS and suffix not in _MEDIA_EXTENSIONS[item.media_kind]:
            continue
        # CDN/provider content endpoints may have no recognizable extension.
        return True
    return False


def media_kind(primary: str, secondary: str, url: str = "") -> str:
    primary, secondary = primary.lower(), secondary.lower()
    if "video" in (primary, secondary):
        return "video"
    if primary in {"voice", "audio"} or secondary in {"voice", "audio"}:
        return "audio"
    suffix = url.split("?", 1)[0].split("#", 1)[0].lower()
    if suffix.endswith(tuple(_MEDIA_EXTENSIONS["video"])):
        return "video"
    if suffix.endswith(tuple(_MEDIA_EXTENSIONS["audio"])):
        return "audio"
    return "image"


def delivered_urls(value) -> list[tuple[int, str]]:
    """Only formal output URLs count; previews and local upload paths do not."""
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for index, url in enumerate(value):
        if not isinstance(url, str):
            continue
        url = url.strip()
        if url and url not in seen and (url.startswith(("https://", "http://")) or url.startswith("/static/")):
            result.append((index, url))
            seen.add(url)
    return result


def tool_items(run: ToolRun) -> list[MediaLibraryItem]:
    if run.kind not in {"image", "video", "audio"}:
        return []
    params = run.params if isinstance(run.params, dict) else {}
    # Do not return internal task credentials, local file paths or upstream request bodies.
    options = {key: params[key] for key in ("resolution", "aspect_ratio", "size", "generate_audio", "seed")
               if isinstance(params.get(key), (str, int, float, bool))}
    if "ratio" in params and isinstance(params["ratio"], str):
        options["aspect_ratio"] = params["ratio"]
    if run.kind == "video":
        raw = params.get("duration_sec", params.get("duration", ""))
        try:
            duration = float(str(raw).removesuffix("s"))
            if 0 < duration < 36000:
                options["requested_duration_sec"] = duration
        except (TypeError, ValueError):
            pass
    if run.kind == "audio" and isinstance(params.get("voice"), str):
        options["speaker"] = params["voice"]
    labels = {"image": "图片", "video": "视频", "audio": "音频"}
    rows = []
    for index, url in delivered_urls(run.urls):
        poster = run.preview_url if run.kind == "video" and run.preview_url != url else None
        rows.append(MediaLibraryItem(
            key=f"tool:{run.id}:{index}", id=run.id, source_kind="tool", source_id=run.id,
            type=run.kind, asset_type=run.kind, media_kind=run.kind,
            name=f"{labels[run.kind]}生成 · 结果 {index + 1}", url=url,
            cover=url if run.kind == "image" else poster,
            references=public_references(params),
            updated_at=run.updated_at or run.created_at,
            params={"media_metadata": {"source": "generated", "prompt": run.prompt,
                "model_id": params.get("model_id") if isinstance(params.get("model_id"), str) else None,
                **({"parameter_source": "request"} if run.kind == "video" else {}),
                "parameters": options, "created_at": (run.updated_at or run.created_at).isoformat()}},
        ))
    return rows


async def library_page(db, user_id: int, team_id: int | None, *, kind="all", media_filter=None, project_id=None,
                       project_kind="drama", generation_status: LibraryGenerationStatus = "all",
                       unassigned=False, q="", page=1, page_size=12) -> MediaLibraryPage:
    from sqlalchemy import exists, or_
    from app.printfilm_studio.sharing import CanvasMember
    if team_id is not None:
        raise HTTPException(status_code=410, detail="独立团队已停用，请按项目浏览素材")
    scope = or_(DramaProject.user_id == user_id, exists(select(CanvasMember.id).where(CanvasMember.project_id == DramaProject.id, CanvasMember.user_id == user_id)))
    # Project ID namespaces are separate; a short-video ID must never select a drama with the same ID.
    dramas = {row.id: row for row in (await db.scalars(select(DramaProject).where(scope)
        .options(selectinload(DramaProject.script)))).all()}
    shorts = {} if team_id is not None else {row.id: row for row in (
        await db.scalars(select(Project).where(Project.user_id == user_id))).all()}
    selected = shorts if project_kind == "short_video" else dramas
    if project_id is not None and project_id not in selected:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project_id is not None:
        dramas = {project_id: dramas[project_id]} if project_kind == "drama" else {}
        shorts = {project_id: shorts[project_id]} if project_kind == "short_video" else {}
    statement = select(DramaAsset, DramaProject).join(DramaProject, DramaProject.id == DramaAsset.project_id).where(scope)
    statement = statement.where(DramaProject.id.in_(dramas))
    statement = statement.options(selectinload(DramaProject.script))
    items = []
    if not unassigned:
        for asset, project in (await db.execute(statement)).all():
            primary = (asset.type or "").lower()
            if primary not in {"character", "scene", "prop", "voice", "image", "video", "audio"}:
                continue
            media = media_kind(primary, asset.asset_type or "", asset.url or "")
            suffix = "/canvas" if resolve_drama_workflow(project) == "canvas" else ""
            row = MediaLibraryItem(
                key=f"drama:{asset.id}", id=asset.id, source_kind="drama", source_id=asset.id,
                type=primary, asset_type=asset.asset_type, media_kind=media, name=asset.name,
                cover=asset.cover, url=asset.url, params=asset.params, updated_at=asset.updated_at,
                project_id=project.id, project_kind="drama", project_title=project.title,
                project_url=f"/drama/projects/{project.id}{suffix}",
            )
            row._lineage = ("asset", asset.id)
            items.append(row)
    video_rows, video_task_ids = await video_items(db, user_id, team_id,
        {} if unassigned else dramas, {} if unassigned else shorts, include_unassigned=project_id is None)
    items.extend(video_rows)
    if team_id is None:
        runs = (await db.execute(select(ToolRun).where(ToolRun.user_id == user_id,
            ToolRun.kind.in_(["image", "video", "audio"]), ToolRun.urls.is_not(None)))).scalars().all()
        # Read explicit persisted task links, never infer ownership by a shared media URL.
        links = {run_id: task for run_id, task in (await db.execute(select(ToolRun.id, TaskRun)
            .join(TaskRun, _tool_link()).where(ToolRun.id.in_([run.id for run in runs]))
            .order_by(TaskRun.id))).all()} if runs else {}
        for run in runs:
            # Partial delivery survives failed/cancelled task status.
            task = links.get(run.id)
            fields = task_project(task, dramas, shorts, user_id, team_id) if task else {}
            if fields is None or (unassigned and fields) or (project_id is not None and not fields):
                continue
            if run.kind == "video" and task is not None and task.id in video_task_ids:
                continue
            rows = tool_items(run)
            for row in rows:
                row._reference_task_id = task.id if task is not None else None
                for key, value in fields.items():
                    setattr(row, key, value)
            items.extend(rows)
    items = deduplicate_videos(items)
    total_all = len(items)
    search = q.strip().casefold()
    items = [
        item for item in items
        if (media_filter is None or item.media_kind == media_filter)
        and (kind == "all" or (item.media_kind == kind if kind in {"image", "video", "audio"} else item.type == kind))
        and (generation_status == "all" or has_generated_media(item) == (generation_status == "generated"))
        and (not search or search in " ".join((
            item.name or "", item.project_title or "", item.type, str(item.project_id or ""),
        )).casefold())
    ]
    items.sort(key=lambda item: ((item.updated_at or datetime(1970, 1, 1, tzinfo=UTC)).timestamp(), item.key), reverse=True)
    total = len(items)
    page = min(page, max(1, (total + page_size - 1) // page_size))
    selected = items[(page - 1) * page_size:page * page_size]
    await hydrate_library_references(db, selected, user_id=user_id, team_id=team_id)
    return MediaLibraryPage(items=selected,
        meta=MediaLibraryMeta(total=total, total_all=total_all, page=page, page_size=page_size))
