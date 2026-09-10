"""Drama agent endpoints: summary, episode script, route, chat."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas_drama import (
    DramaChatRequest,
    DramaEpisodeScriptRequest,
    DramaRouteRequest,
    DramaScriptOut,
    DramaScriptSummaryRequest,
)
from app.services.billing import run_billed_ephemeral
from app.services.drama.access import get_owned_drama_project
from app.services.drama.agents import (
    count_completed_episodes,
    resolve_episode_target,
)
from app.services.billing.http import http_exception_for_value_error
from app.services.drama.jobs import dispatch_episode_scripts_job, dispatch_script_summary_job
from app.services.drama.llm import DramaLlmUnavailableError, drama_chat_text

router = APIRouter()
logger = logging.getLogger("app.drama.agents")

# summary_generating_at 超过该时长仍无结果，允许重新入队
SUMMARY_GENERATING_STALE_MINUTES = 25


def _summary_generating_is_stale(params: dict) -> bool:
    # 判断 generating 是否已超时（避免 Celery 失败/丢任务后前端永久转圈）
    started_raw = params.get("summary_generating_at")
    if not started_raw:
        return True
    try:
        started = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started > timedelta(minutes=SUMMARY_GENERATING_STALE_MINUTES)


@router.post("/agents/script_summary")
async def script_summary(
    body: DramaScriptSummaryRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # 入队摘要任务，立即返回；前端轮询 script.params.summary_status
    project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
    if not project.script:
        raise HTTPException(status_code=400, detail="缺少剧本")
    creative = (body.creative or project.script.source or "").strip()
    if len(creative) < 20:
        raise HTTPException(status_code=400, detail="创意文案至少 20 字")

    project.script.source = creative
    params = dict(project.script.params or {})
    if body.episode_count:
        params["episode_count"] = int(body.episode_count)
        proj_params = dict(project.params or {})
        proj_params["episode_count"] = int(body.episode_count)
        project.params = proj_params
    if body.image_style_id:
        params["image_style_id"] = str(body.image_style_id)
        proj_params = dict(project.params or {})
        proj_params["image_style_id"] = str(body.image_style_id)
        project.params = proj_params
    existing_status = str(params.get("summary_status") or "")
    if existing_status == "generating" and not _summary_generating_is_stale(params):
        logger.info(
            "剧本摘要已在生成中，跳过重复入队 project_id=%s user_id=%s",
            project.id,
            user.id,
        )
        await db.commit()
        return {
            "ok": True,
            "queued": True,
            "status": "generating",
            "task_id": None,
            "script": DramaScriptOut.model_validate(project.script).model_dump(),
        }
    if existing_status == "generating":
        logger.warning(
            "剧本摘要 generating 超时，允许重新入队 project_id=%s user_id=%s started=%s",
            project.id,
            user.id,
            params.get("summary_generating_at"),
        )
    params["summary_status"] = "generating"
    params["summary_generating_at"] = datetime.now(timezone.utc).isoformat()
    params.pop("summary_error", None)
    project.script.params = params

    try:
        task_id = await dispatch_script_summary_job(db, user, project.id)
    except ValueError as exc:
        await db.rollback()
        raise http_exception_for_value_error(exc) from exc
    logger.info(
        "已入队剧本摘要 project_id=%s user_id=%s task_id=%s creative_len=%s",
        project.id,
        user.id,
        task_id,
        len(creative),
    )
    return {
        "ok": True,
        "queued": True,
        "status": "generating",
        "task_id": task_id,
        "script": DramaScriptOut.model_validate(project.script).model_dump(),
    }


@router.post("/agents/episode_script")
async def episode_script(
    body: DramaEpisodeScriptRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    # 入队完整分集生成；前端轮询 episode_content_status / progress
    project = await get_owned_drama_project(db, body.project_id, user, with_script=True)
    if not project.script or not project.script.summary:
        raise HTTPException(status_code=400, detail="请先生成剧本摘要")

    summary = project.script.summary if isinstance(project.script.summary, dict) else {}
    total = resolve_episode_target(summary, project.params, project.script.params)
    if summary.get("episodeCount") != total:
        summary = {**summary, "episodeCount": total}
        project.script.summary = summary

    params = dict(project.script.params or {})
    if str(params.get("episode_content_status") or "") == "generating" and not body.force:
        content = project.script.episode_content
        existing: list = []
        if isinstance(content, dict) and isinstance(content.get("episodes"), list):
            existing = list(content["episodes"])
        elif isinstance(content, list):
            existing = list(content)
        generated = count_completed_episodes(existing, total)
        logger.info(
            "分集剧本已在生成中，跳过重复入队 project_id=%s progress=%s/%s",
            project.id,
            generated,
            total,
        )
        await db.commit()
        return {
            "ok": True,
            "queued": True,
            "status": "generating",
            "task_id": None,
            "episodes": [],
            "total_generated": generated,
            "total_target": total,
            "done": False,
            "script": DramaScriptOut.model_validate(project.script).model_dump(),
        }

    params["episode_content_status"] = "generating"
    params["episode_count"] = total
    params.pop("episode_content_error", None)
    if body.force:
        content = project.script.episode_content
        existing: list = []
        if isinstance(content, dict) and isinstance(content.get("episodes"), list):
            existing = list(content["episodes"])
        elif isinstance(content, list):
            existing = list(content)
        if existing:
            project.script.episode_content = {
                "episodes": [
                    {
                        "episodeNumber": int(item.get("episodeNumber") or 0),
                        "title": str(item.get("title") or f"第 {item.get('episodeNumber')} 集"),
                        "body": "",
                    }
                    for item in existing
                    if isinstance(item, dict) and int(item.get("episodeNumber") or 0) >= 1
                ]
            }
        params["episode_content_progress"] = {"done": 0, "total": total}
    project.script.params = params

    try:
        task_id = await dispatch_episode_scripts_job(db, user, project.id, force=bool(body.force))
    except ValueError as exc:
        await db.rollback()
        raise http_exception_for_value_error(exc) from exc
    content = project.script.episode_content
    existing = []
    if isinstance(content, dict) and isinstance(content.get("episodes"), list):
        existing = list(content["episodes"])
    elif isinstance(content, list):
        existing = list(content)
    generated = count_completed_episodes(existing, total)
    logger.info(
        "已入队分集剧本 project_id=%s user_id=%s task_id=%s force=%s target=%s done=%s",
        project.id,
        user.id,
        task_id,
        bool(body.force),
        total,
        generated,
    )
    return {
        "ok": True,
        "queued": True,
        "status": "generating",
        "task_id": task_id,
        "episodes": [],
        "total_generated": generated,
        "total_target": total,
        "done": False,
        "script": DramaScriptOut.model_validate(project.script).model_dump(),
    }


@router.post("/agents/route")
async def route_agent(body: DramaRouteRequest, user: User = Depends(get_current_user)) -> dict:
    _ = user
    msg = (body.message or "").strip().lower()
    if any(k in msg for k in ("剧本", "短剧", "漫剧", "分集", "大纲", "编剧")):
        return {"agent": "drama_script", "action": "create_project"}
    if any(k in msg for k in ("画布", "节点", "自由创作")):
        return {"agent": "canvas", "action": "open_canvas"}
    return {"agent": "chat", "action": "chat"}


@router.post("/ai/chat")
async def ai_chat(
    body: DramaChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    logger.info("漫剧聊天 user_id=%s project_id=%s", user.id, body.project_id)

    async def _do_chat() -> str:
        from app.services.billing import record_line

        try:
            reply = await drama_chat_text(
                "你是 PRINTFILM 漫剧创作助手，帮助用户构思短剧创意、人物与分集结构。用简洁中文回答。",
                body.message,
            )
        except DramaLlmUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        await record_line(
            db,
            user_id=user.id,
            billing_key="llm_chat",
            model=get_settings().model_llm,
            estimated=True,
            drama_project_id=body.project_id,
            domain="drama",
        )
        return reply

    try:
        task, reply = await run_billed_ephemeral(
            db,
            user,
            domain="drama",
            task_type="agent_chat",
            executor=_do_chat,
            payload={"message_len": len(body.message or "")},
            drama_project_id=body.project_id,
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    return {"reply": reply, "task_id": task.id}
