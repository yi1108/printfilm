"""为助手工具加载项目摘要，并提供数据库画布端口。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models_drama import DramaEpisode, DramaEpisodeFragment, DramaProject
from app.models_tasks import TaskRun
from app.printfilm_studio.canvas.service import get_or_create, list_assets, save
from app.services.drama.workflow import resolve_drama_workflow


def _clip(value: object, limit: int = 180) -> str:
    """截断长文本，避免分镜正文撑满模型上下文。"""
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit]}…"


async def load_project_view(db: AsyncSession, project: DramaProject, user: User) -> dict[str, Any]:
    """汇总助手可读的项目、分集、资产和最近任务。"""
    # Legacy workflow detection reads script.source. Load it explicitly rather
    # than triggering synchronous lazy I/O inside the async Agent worker.
    if "script" in inspect(project).unloaded:
        await db.refresh(project, attribute_names=["script"])
    episodes = list((await db.scalars(select(DramaEpisode).where(DramaEpisode.project_id == project.id).order_by(DramaEpisode.id).limit(8))).all())
    episode_ids = [episode.id for episode in episodes]
    fragments = list((await db.scalars(select(DramaEpisodeFragment).where(DramaEpisodeFragment.episode_id.in_(episode_ids)).order_by(DramaEpisodeFragment.sort_order, DramaEpisodeFragment.id))).all()) if episode_ids else []
    grouped: dict[int, list[dict[str, Any]]] = {}
    for fragment in fragments:
        bucket = grouped.setdefault(fragment.episode_id, [])
        if len(bucket) >= 12:
            continue
        bucket.append({"id": fragment.id, "sort_order": fragment.sort_order, "content": _clip(fragment.content)})
    assets = await list_assets(db, project)
    tasks = list((await db.scalars(select(TaskRun).where(TaskRun.drama_project_id == project.id, TaskRun.requested_by == user.id).order_by(TaskRun.id.desc()).limit(10))).all())
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description or "",
        "workflow": resolve_drama_workflow(project),
        "episodes": [{"id": episode.id, "name": episode.name, "fragments": grouped.get(episode.id, [])} for episode in episodes],
        "assets": [{"id": asset.id, "name": asset.name, "type": asset.type, "asset_type": asset.asset_type, 'url': asset.url} for asset in assets[:100]],
        "tasks": [{"id": task.id, "status": task.status, "task_type": task.task_type, "error": _clip(task.error_message, 120)} for task in tasks],
    }


class DatabaseCanvas:
    """用现有画布服务保存助手补丁，版本号以当前行为准。"""

    def __init__(self, db: AsyncSession, project: DramaProject, user: User, *, edit_session_id: str | None = None, edit_lock_token: str | None = None, edit_lock_version: int | None = None) -> None:
        self.db = db
        self.project = project
        self.user = user
        self.version = 1
        self.existing_ids = set()
        self.edit_session_id = edit_session_id
        self.edit_lock_token = edit_lock_token
        self.edit_lock_version = edit_lock_version

    async def load(self) -> tuple[dict[str, Any], int]:
        """读取或创建画布文档。"""
        row = await get_or_create(self.db, self.project, self.user)
        self.version = row.document_version
        self.existing_ids = {node['id'] for node in (row.document or {}).get('nodes', [])}
        return dict(row.document or {}), self.version

    async def save(self, document: dict[str, Any]) -> int:
        """按已读版本保存，并记住新版本。"""
        from .node_defaults import apply_node_defaults
        apply_node_defaults(document, self.existing_ids, self.db.info)
        row = await save(self.db, self.project, self.user, document, self.version)
        self.version = row.document_version
        self.existing_ids = {node['id'] for node in document.get('nodes', [])}
        return self.version
