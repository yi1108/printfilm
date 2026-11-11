"""团队资源租约与统一任务的写入占用，个人项目沿用既有行为。"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models_drama import DramaAsset, DramaEpisode, DramaEpisodeFragment, DramaProject
from app.models_team_locks import TeamEditLock
from app.models_tasks import TaskRun
from app.services.teams.access import get_team

# 持久任务状态来自统一任务平台，不能随发起人断线释放。
ACTIVE_STATUSES = ("pending", "leased", "running", "awaiting_poll", "awaiting_review", "cancel_requested", "finalizing")
RESOURCE_TYPES = frozenset({"structure", "script", "episode", "asset", "canvas"})
LEASE_SECONDS = 120


def token_digest(token: str) -> str:
    """数据库仅存随机凭证的摘要，接口不返回别人的原始 token。"""
    return hashlib.sha256(token.encode()).hexdigest()


def resources_conflict(left: tuple[str, int], right: tuple[str, int]) -> bool:
    """结构改写与整个项目互斥，其他资源仅同类同目标互斥。"""
    return left[0] == "structure" or right[0] == "structure" or left == right


async def episode_resource_id(db: AsyncSession, episode_id: int) -> int:
    """分集确认前后均使用稳定集号；历史缺号时以数据库 id 兜底。"""
    episode = await db.get(DramaEpisode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="分集不存在")
    return int((episode.params or {}).get("episodeNumber") or episode.id)


async def task_resource(db: AsyncSession, task: TaskRun) -> tuple[str, int]:
    """读取受理时固定的写回范围，仅服务端能写入该快照。"""
    snapshot = (task.payload or {}).get("_team_edit_resource")
    if isinstance(snapshot, (list, tuple)) and len(snapshot) == 2 and snapshot[0] in RESOURCE_TYPES:
        return str(snapshot[0]), int(snapshot[1])
    return await derived_task_resource(db, task)


async def derived_task_resource(db: AsyncSession, task: TaskRun) -> tuple[str, int]:
    """受理时只用真实 FK 与业务参数推导目标，忽略请求会话和旧快照。"""
    if task.asset_id:
        return "asset", int(task.asset_id)
    if task.episode_id:
        return "episode", await episode_resource_id(db, task.episode_id)
    if task.fragment_id:
        fragment = await db.get(DramaEpisodeFragment, task.fragment_id)
        if fragment:
            return "episode", await episode_resource_id(db, fragment.episode_id)
    number = (task.payload or {}).get("episode_number")
    if (task.task_type in {"episode_scripts", "episode_script", "episode_optimize"} or (task.task_type == "seed_assets" and (task.payload or {}).get("confirm_episode"))) and number:
        return "episode", int(number)
    if task.task_type in {"asset_image", "asset_video"}:
        return "asset", 0
    if task.task_type in {"tool_image", "tool_video", "tool_audio"}:
        # Printfilm Studio tasks write their result back to the workspace
        # canvas/asset stream and are admitted by the canvas edit lease.
        return "canvas", 0
    return "structure", 0


async def _task_conflicts(db: AsyncSession, project_id: int, resource: tuple[str, int], *, ignore_task_id: int | None = None, ignore_task_ids: set[int] | None = None) -> None:
    """任务一经受理即占用写回对象，强制接管不能覆盖在途结果。"""
    tasks = (await db.execute(select(TaskRun).where(TaskRun.drama_project_id == project_id, TaskRun.status.in_(ACTIVE_STATUSES)))).scalars().all()
    for task in tasks:
        if task.task_type in {"agent_chat", "skill_optimize"}:
            continue  # 聊天只返回文本，没有生成内容写回。
        if task.id != ignore_task_id and task.id not in (ignore_task_ids or set()) and resources_conflict(resource, await task_resource(db, task)):
            raise HTTPException(status_code=423, detail={"message": "相关内容正在生成，请等待任务结束", "task_id": task.id})


async def _project(db: AsyncSession, team_id: int, user_id: int, project_id: int) -> DramaProject:
    """使用团队→成员→项目的统一锁顺序，串行检查层级占用。"""
    await get_team(db, team_id, user_id, lock=True)
    project = (await db.execute(select(DramaProject).where(DramaProject.id == project_id, DramaProject.team_id == team_id).with_for_update())).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="团队项目不存在")
    return project


async def _check_resource(db: AsyncSession, project: DramaProject, kind: str, resource_id: int) -> None:
    """资产 id 必须属于当前项目，分集键限制为有效正整数。"""
    if kind not in RESOURCE_TYPES or resource_id < 0:
        raise HTTPException(status_code=422, detail="无效的编辑目标")
    if kind == "asset" and resource_id:
        asset = await db.get(DramaAsset, resource_id)
        if not asset or asset.project_id != project.id:
            raise HTTPException(status_code=404, detail="资产不存在")
    if kind == "episode" and resource_id < 1:
        raise HTTPException(status_code=422, detail="缺少分集编号")
    if kind in {"structure", "script", "canvas"} and resource_id != 0:
        raise HTTPException(status_code=422, detail="无效的编辑目标编号")


async def lock_view(db: AsyncSession, lock: TeamEditLock, token: str | None = None) -> dict:
    """对外提供占用者和 fencing 代次，原始凭证仅在获取时提供。"""
    user = await db.get(User, lock.user_id)
    out = {"project_id": lock.project_id, "resource_type": lock.resource_type, "resource_id": lock.resource_id, "version": lock.version, "expires_at": lock.expires_at.isoformat(), "owner_user_id": lock.user_id, "owner_name": user.nickname if user else "团队成员"}
    if token is not None:
        out["token"] = token
    return out


async def acquire_lock(db: AsyncSession, team_id: int, user_id: int, project_id: int, resource_type: str, resource_id: int, session_id: str, *, force: bool = False) -> dict:
    """获取或接管人工租约，重新发 token 时增加代次使旧凭证失效。"""
    project = await _project(db, team_id, user_id, project_id)
    await _check_resource(db, project, resource_type, resource_id)
    if force:
        await get_team(db, team_id, user_id, roles=("owner", "admin"))
    if not session_id or len(session_id) > 80:
        raise HTTPException(status_code=422, detail="无效的编辑会话")
    await _task_conflicts(db, project_id, (resource_type, resource_id))
    now = datetime.now(UTC)
    locks = list((await db.execute(select(TeamEditLock).where(TeamEditLock.project_id == project_id).with_for_update())).scalars().all())
    target = next((lock for lock in locks if (lock.resource_type, lock.resource_id) == (resource_type, resource_id)), None)
    for lock in locks:
        if lock.expires_at <= now or (lock.user_id == user_id and lock.session_id == session_id):
            continue
        if resources_conflict((resource_type, resource_id), (lock.resource_type, lock.resource_id)):
            if not force:
                info = await lock_view(db, lock)
                raise HTTPException(status_code=423, detail={"message": f"{info['owner_name']} 正在编辑此内容", **info})
            lock.expires_at = now
    token = secrets.token_urlsafe(32)
    if target is None:
        target = TeamEditLock(team_id=team_id, project_id=project_id, resource_type=resource_type, resource_id=resource_id, user_id=user_id, session_id=session_id, token_hash=token_digest(token), version=1, expires_at=now + timedelta(seconds=LEASE_SECONDS))
        db.add(target)
    else:
        target.user_id, target.session_id, target.token_hash = user_id, session_id, token_digest(token)
        target.version += 1
        target.expires_at = now + timedelta(seconds=LEASE_SECONDS)
    await db.commit()
    return await lock_view(db, target, token)


async def validate_lock(db: AsyncSession, project: DramaProject, user_id: int, resource_type: str, resource_id: int, session_id: str, token: str, version: int) -> TeamEditLock | None:
    """提交时复核当前成员、租约与代次；失锁的旧标签页无法覆盖。"""
    if project.team_id is None:
        return None
    await _project(db, project.team_id, user_id, project.id)
    lock = (await db.execute(select(TeamEditLock).where(TeamEditLock.project_id == project.id, TeamEditLock.user_id == user_id, TeamEditLock.session_id == session_id, TeamEditLock.token_hash == token_digest(token)).with_for_update())).scalar_one_or_none()
    if not lock or lock.expires_at <= datetime.now(UTC) or lock.version != version:
        raise HTTPException(status_code=409, detail={"message": "编辑权限已变化，请重新获取后刷新内容"})
    if (lock.resource_type, lock.resource_id) != (resource_type, resource_id) and lock.resource_type != "structure":
        raise HTTPException(status_code=409, detail={"message": "编辑凭证与目标内容不匹配"})
    return lock


async def renew_lock(db: AsyncSession, team_id: int, user_id: int, token: str, session_id: str, *, release: bool = False) -> dict:
    """只允许持有者续租或释放自己的会话，不凭 user_id 释放另一个标签页。"""
    await get_team(db, team_id, user_id, lock=True)
    lock = (await db.execute(select(TeamEditLock).where(TeamEditLock.team_id == team_id, TeamEditLock.user_id == user_id, TeamEditLock.session_id == session_id, TeamEditLock.token_hash == token_digest(token)).with_for_update())).scalar_one_or_none()
    if not lock or (not release and lock.expires_at <= datetime.now(UTC)):
        raise HTTPException(status_code=409, detail={"message": "编辑占用已失效，请重新获取"})
    lock.expires_at = datetime.now(UTC) + timedelta(seconds=0 if release else LEASE_SECONDS)
    await db.commit()
    return await lock_view(db, lock)


async def release_member_locks(db: AsyncSession, team_id: int, user_id: int) -> None:
    """退出团队立即使人工租约失效；系统任务由任务状态继续保护。"""
    await db.execute(update(TeamEditLock).where(TeamEditLock.team_id == team_id, TeamEditLock.user_id == user_id).values(expires_at=datetime.now(UTC)))


async def claim_task_locks(db: AsyncSession, task: TaskRun, user_id: int) -> None:
    """任务受理时固定写入范围，拒绝与其他会话的人工编辑竞争。"""
    if task.team_id is None or not task.drama_project_id:
        return
    if task.task_type in {"agent_chat", "skill_optimize"}:
        return
    project = await _project(db, task.team_id, user_id, task.drama_project_id)
    snapshot = db.info.get("team_edit_resource") if db.info.get("team_edit_project_id") == project.id else None
    actual = await derived_task_resource(db, task)
    resource = tuple(snapshot) if snapshot else actual
    parent_id = db.info.get("team_parent_task_id")
    if parent_id:
        from app.services.billing.context import get_current_task_run_id

        parent = await db.get(TaskRun, int(parent_id))
        if (get_current_task_run_id() != parent_id or not parent or parent.team_id != task.team_id
                or parent.drama_project_id != task.drama_project_id or parent.requested_by != user_id
                or parent.status not in ACTIVE_STATUSES or parent.cancel_requested):
            raise HTTPException(status_code=409, detail="父任务的系统写入权限已失效")
        resource = actual  # 系统派生永不采信残留的人工请求资源快照。
        parent_resource = await task_resource(db, parent)
        if parent_resource[0] != "structure" and parent_resource != resource:
            raise HTTPException(status_code=409, detail="后续任务超出了已受理内容的范围")
        task.payload = {**(task.payload or {}), "_team_parent_task_id": parent.id, "_team_edit_resource": list(resource)}
        return
    if resource[0] != "structure" and resource != actual:
        raise HTTPException(status_code=409, detail="任务写入范围与已授权编辑目标不匹配")
    session_id = str(db.info.get("team_edit_session_id") or "")
    token = str(db.info.get("team_edit_token") or "")
    version = int(db.info.get("team_edit_version") or 0)
    if not session_id or not token:
        raise HTTPException(status_code=428, detail="请先获取团队内容的编辑权限")
    await validate_lock(db, project, user_id, *resource, session_id, token, version)
    admitted = set(db.info.get("team_admitted_task_ids") or ())
    await _task_conflicts(db, project.id, resource, ignore_task_id=task.id, ignore_task_ids=admitted)
    if task.id:
        db.info["team_admitted_task_ids"] = admitted | {task.id}
    task.payload = {**(task.payload or {}), "_team_edit_session_id": session_id, "_team_edit_resource": list(resource)}


async def validate_task_locks(db: AsyncSession, task: TaskRun) -> None:
    """执行前确认仍属于受理时团队；任务自身即为系统占用。"""
    if task.team_id is not None and task.drama_project_id:
        project = await db.get(DramaProject, task.drama_project_id)
        if not project or project.team_id != task.team_id:
            raise ValueError("任务关联项目的团队归属已变化")


async def release_task_locks(db: AsyncSession, task_id: int) -> None:
    """系统占用由终态自动解除，无人工凭证可被误释放。"""
    return None
