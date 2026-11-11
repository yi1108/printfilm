"""将现有漫剧写入口统一映射到实际团队资源，防止漏掉旧路由授权。"""
from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_drama import DramaAsset, DramaEpisode, DramaEpisodeFragment, DramaProject
from app.services.drama.access import get_owned_drama_project, require_drama_project_manager
from app.services.teams.access import get_team
from app.services.teams.edit_locks import _task_conflicts, episode_resource_id, validate_lock


async def workspace_team(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> int | None:
    """The retired organization scope must never grant project permissions."""
    if request.query_params.get("team_id") or request.headers.get("X-Team-Id"):
        raise HTTPException(status_code=410, detail="独立团队已停用，请通过画布项目分享邀请成员")
    return None


async def write_target(db: AsyncSession, path: str, values: dict) -> tuple[int, str, int] | None:
    """推导路径和请求字段对应的资源键，不接受客户端指定锁范围。"""
    suffix = path.removeprefix("/api/drama/")
    match = re.match(r"scripts/(\d+)/episodes/(\d+)$", suffix)
    if match:
        return int(match[1]), "episode", int(match[2])
    match = re.match(r"(projects|scripts|canvas)/(\d+)$", suffix)
    if match:
        return int(match[2]), {"projects": "structure", "scripts": "script", "canvas": "canvas"}[match[1]], 0
    match = re.match(r"assets/(\d+)(?:/.*)?$", suffix)
    if match:
        asset = await db.get(DramaAsset, int(match[1]))
        if asset:
            return asset.project_id, "asset", asset.id
        raise HTTPException(status_code=404, detail="资产不存在")
    match = re.match(r"episodes/(\d+)(?:/.*)?$", suffix)
    if match:
        episode = await db.get(DramaEpisode, int(match[1]))
        if episode:
            return episode.project_id, "episode", await episode_resource_id(db, episode.id)
        raise HTTPException(status_code=404, detail="分集不存在")
    match = re.match(r"fragments/(\d+)(?:/.*)?$", suffix)
    if match:
        fragment = await db.get(DramaEpisodeFragment, int(match[1]))
        episode = await db.get(DramaEpisode, fragment.episode_id) if fragment else None
        if episode:
            return episode.project_id, "episode", await episode_resource_id(db, episode.id)
        raise HTTPException(status_code=404, detail="分镜不存在")
    project_id = values.get("project_id")
    if not project_id:
        return None
    if suffix == "canvas":
        return int(project_id), "canvas", 0
    if suffix == "assets":
        return int(project_id), "asset", 0
    if suffix == "generation/voice":
        return int(project_id), "structure", 0
    if suffix.startswith("generation/"):
        return int(project_id), "asset", int(values.get("asset_id") or values.get("character_asset_id") or 0)
    if suffix in {"agents/episode_script", "episodes/confirm_from_script"} and values.get("episode_number"):
        return int(project_id), "episode", int(values["episode_number"])
    if suffix in {"ai/chat", "skills/optimize"}:
        return None
    return int(project_id), "structure", 0


async def enforce_drama_write(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    """团队写操作必须持有当前资源租约，个人旧接口保持兼容。"""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    # 取消走任务操作权限，不依赖等待释放的生成内容租约。
    if request.url.path.endswith(("/cancel_generate", "/cancel_video_jobs")):
        return
    values = dict(request.query_params)
    if "application/json" in request.headers.get("content-type", ""):
        try:
            body = await request.json()
            if isinstance(body, dict):
                values.update(body)
        except ValueError:
            return  # 请求模型将提供标准 JSON 校验错误。
    try:
        target = await write_target(db, request.url.path, values)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="无效的创作资源编号") from exc
    if not target:
        return
    await get_owned_drama_project(db, target[0], user)
