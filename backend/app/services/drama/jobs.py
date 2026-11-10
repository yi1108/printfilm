"""Drama long-running jobs executed in-process by the task platform."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.drama.fragment_dialogue import summarize_locked_fragment
from app.database import AsyncSessionLocal
from app.models import User
from app.models_tasks import TaskRun
from app.models_drama import (
    DramaAsset,
    DramaEpisode,
    DramaEpisodeFragment,
    DramaFragmentAssetRef,
    DramaProject,
)
from app.services.billing import record_line, record_llm_chat_line
from app.services.drama.billing_util import record_seed_assets_llm_usage
from app.services.drama.seed import seed_assets_from_episode_body
from app.services.teams.script_updates import bump_episode_versions, locked_script, set_episode_job_state
from app.services.drama.agents import (
    auto_missing_episode_numbers,
    count_completed_episodes,
    ensure_episode_outline,
    format_summary_text,
    merge_episode_bodies,
    pick_auto_project_title,
    resolve_episode_target,
    run_episode_body_from_brief,
    run_episode_brief_from_body,
    run_episode_full_from_creative,
    run_episode_script_batch,
    run_episode_script_from_draft,
    run_episode_summary_from_creative,
    run_script_summary,
)
from app.services.drama.asset_video import generate_asset_video
from app.services.drama.generation import (
    apply_fragment_video_assets,
    build_failed_generation_params,
    deserialize_fragment_video_prepared,
    generate_asset_image,
    prepare_fragment_video_for_submit,
    serialize_fragment_video_prepared,
    submit_prepared_fragment_video,
)
from app.services.drama.visual_prompt import resolve_visual_prompt_for_asset

logger = logging.getLogger(__name__)

# 分集视频取消标记（episode_id）
_video_cancelled_episodes: set[int] = set()
ACTIVE_VIDEO_GEN_STATUSES = frozenset({"queued", "running", "generating"})


def _is_episode_video_cancelled(episode_id: int) -> bool:
    return int(episode_id) in _video_cancelled_episodes


def _mark_episode_video_cancelled(episode_id: int) -> None:
    _video_cancelled_episodes.add(int(episode_id))


def _clear_episode_video_cancelled(episode_id: int) -> None:
    _video_cancelled_episodes.discard(int(episode_id))


def clear_episode_video_cancelled(episode_id: int) -> None:
    """新入队分镜视频前清除进程内取消标记，避免误把新任务立刻作废。"""
    _clear_episode_video_cancelled(episode_id)


async def _reset_fragment_video_generation(
    db,
    *,
    episode_id: int | None = None,
    user_id: int | None = None,
) -> int:
    q = select(DramaEpisodeFragment)
    if episode_id is not None:
        q = q.where(DramaEpisodeFragment.episode_id == int(episode_id))
    if user_id is not None:
        # 按项目归属收敛：禁止跨用户重置分镜
        q = (
            q.join(DramaEpisode, DramaEpisodeFragment.episode_id == DramaEpisode.id)
            .join(DramaProject, DramaEpisode.project_id == DramaProject.id)
            .where(DramaProject.user_id == int(user_id), DramaProject.team_id.is_(None))
        )
    frags = (await db.execute(q)).scalars().all()
    changed = 0
    for frag in frags:
        params = dict(frag.params or {})
        gen = params.get("generation") if isinstance(params, dict) else None
        status = str(gen.get("status") or "") if isinstance(gen, dict) else ""
        if status not in ACTIVE_VIDEO_GEN_STATUSES:
            continue
        params["generation"] = {"status": "cancelled", "error": "任务已取消"}
        frag.params = params
        changed += 1
    if changed:
        await db.commit()
    return changed


async def cancel_episode_video_jobs(episode_id: int) -> dict[str, Any]:
    """取消单集视频任务：标记取消并重置分镜生成状态。"""
    _mark_episode_video_cancelled(episode_id)
    async with AsyncSessionLocal() as db:
        fragments = await _reset_fragment_video_generation(db, episode_id=episode_id)
    logger.info(
        "取消分集视频 episode_id=%s fragments=%s",
        episode_id,
        fragments,
    )
    return {
        "ok": True,
        "episode_id": episode_id,
        "inprocess": 0,
        "purged": 0,
        "revoked": 0,
        "fragments": fragments,
    }


async def cancel_all_episode_video_jobs(user_id: int) -> dict[str, Any]:
    """取消指定用户的全部漫剧分镜视频任务，严禁波及其他用户。"""
    episode_ids: set[int] = set()
    async with AsyncSessionLocal() as db:
        frags = (
            (
                await db.execute(
                    select(DramaEpisodeFragment)
                    .join(DramaEpisode, DramaEpisodeFragment.episode_id == DramaEpisode.id)
                    .join(DramaProject, DramaEpisode.project_id == DramaProject.id)
                    .where(DramaProject.user_id == int(user_id), DramaProject.team_id.is_(None))
                )
            )
            .scalars()
            .all()
        )
        for frag in frags:
            params = frag.params or {}
            gen = params.get("generation") if isinstance(params, dict) else None
            status = str(gen.get("status") or "") if isinstance(gen, dict) else ""
            if status in ACTIVE_VIDEO_GEN_STATUSES:
                episode_ids.add(int(frag.episode_id))
    for ep_id in list(episode_ids):
        _mark_episode_video_cancelled(ep_id)

    async with AsyncSessionLocal() as db:
        fragments = await _reset_fragment_video_generation(db, user_id=user_id)
    logger.info(
        "取消用户全部视频任务 user_id=%s fragments=%s episodes=%s",
        user_id,
        fragments,
        len(episode_ids),
    )
    return {
        "ok": True,
        "purged": 0,
        "revoked": 0,
        "fragments": fragments,
        "episodes": len(episode_ids),
    }


async def _enqueue_drama_task(
    db: AsyncSession,
    user: User,
    *,
    task_type: str,
    project_id: int,
    dedupe_suffix: str,
    payload: dict[str, Any],
    asset_id: int | None = None,
    episode_id: int | None = None,
    fragment_id: int | None = None,
    commit: bool = True,
) -> int:
    """通过统一任务平台入队漫剧任务，返回 task_run_id。"""
    from app.schemas_tasks import TaskCreateRequest, TaskTargetBind
    from app.services.tasks.service import create_task

    task = await create_task(
        db,
        user,
        TaskCreateRequest(
            domain="drama",
            task_type=task_type,
            dedupe_key=f"drama:{task_type}:{dedupe_suffix}",
            drama_project_id=project_id,
            asset_id=asset_id,
            episode_id=episode_id,
            fragment_id=fragment_id,
            payload=payload,
            targets=[TaskTargetBind(target_type="drama_project", target_id=project_id)],
        ),
        commit=commit,
    )
    return int(task.id)


async def dispatch_script_summary_job(db: AsyncSession, user: User, project_id: int) -> int:
    """入队剧本摘要任务。"""
    task_id = await _enqueue_drama_task(
        db,
        user,
        task_type="script_summary",
        project_id=project_id,
        dedupe_suffix=str(project_id),
        payload={"project_id": project_id},
    )
    logger.info("dispatch 剧本摘要 → task_id=%s project_id=%s", task_id, project_id)
    return task_id


async def run_script_summary_job(project_id: int) -> dict[str, Any]:
    # Worker：生成剧本摘要并写库
    async with AsyncSessionLocal() as db:
        project = await db.get(
            DramaProject,
            project_id,
            options=[selectinload(DramaProject.script)],
        )
        if not project or not project.script:
            logger.warning("剧本摘要失败：缺少剧本 project_id=%s", project_id)
            return {"ok": False, "error": "missing_script"}
        script = project.script
        creative = (script.source or "").strip()
        episode_count = (project.params or {}).get("episode_count")
        image_style_id = (project.params or {}).get("image_style_id")
        try:
            summary = await run_script_summary(
                creative,
                episode_count=int(episode_count) if episode_count else None,
                image_style_id=str(image_style_id) if image_style_id else None,
            )
        except Exception as exc:  # noqa: BLE001
            params = dict(script.params or {})
            params["summary_status"] = "failed"
            params["summary_error"] = str(exc)[:500]
            params.pop("summary_generating_at", None)
            script.params = params
            await db.commit()
            logger.exception("剧本摘要失败 project_id=%s err=%s", project_id, exc)
            return {"ok": False, "error": str(exc)[:500]}

        script.summary = summary
        params = dict(script.params or {})
        params["summary_text"] = format_summary_text(summary)
        params["summary_status"] = "completed"
        params["summary_error"] = None
        params.pop("summary_generating_at", None)
        params["episode_content_status"] = params.get("episode_content_status") or "pending"
        script.params = params
        one_line = str(summary.get("oneLineStory") or "").strip()
        if one_line:
            project.description = one_line[:500]
        auto_title = pick_auto_project_title(
            summary, creative=creative, current_title=project.title or ""
        )
        if auto_title:
            project.title = auto_title
            script.name = auto_title
        user = await db.get(User, project.user_id)
        if user:
            await record_line(
                db,
                user_id=user.id,
                project_id=None,
                drama_project_id=project.id,
                billing_key="llm_chat",
                model=get_settings().model_llm,
                estimated=True,
                domain="drama",
            )
        await db.commit()
        logger.info(
            "剧本摘要完成 project_id=%s episode_count=%s series_title=%s one_line=%s",
            project_id,
            summary.get("episodeCount"),
            auto_title or project.title,
            (one_line[:40] + "…") if len(one_line) > 40 else one_line,
        )

    # 顺序：整剧摘要 → 抽资产 → 入队分集剧本（分镜等分集完成后再跑）
    assets_result: dict[str, Any]
    try:
        assets_result = await seed_assets_for_project(project_id)
    except Exception:  # noqa: BLE001
        logger.exception("摘要后自动抽资产异常 project_id=%s", project_id)
        assets_result = {"ok": False, "error": "seed_assets_failed"}

    episodes_task_id: int | None = None
    try:
        async with AsyncSessionLocal() as db:
            project = await db.get(
                DramaProject,
                project_id,
                options=[selectinload(DramaProject.script)],
            )
            if not project or not project.script:
                return {
                    "ok": True,
                    "project_id": project_id,
                    "assets": assets_result,
                    "error": "missing_project_after_summary",
                }
            user = await db.get(User, project.user_id)
            if not user:
                return {
                    "ok": True,
                    "project_id": project_id,
                    "assets": assets_result,
                    "error": "missing_user",
                }
            params = dict(project.script.params or {})
            if str(params.get("episode_content_status") or "") != "generating":
                params["episode_content_status"] = "generating"
                params.pop("episode_content_error", None)
                total = 1
                if isinstance(project.script.summary, dict):
                    total = int(project.script.summary.get("episodeCount") or 1)
                params["episode_count"] = total
                params["episode_content_progress"] = {"done": 0, "total": total}
                project.script.params = params
            episodes_task_id = await dispatch_episode_scripts_job(
                db, user, project_id, force=False
            )
            await db.commit()
            logger.info(
                "摘要后已入队分集剧本 project_id=%s task_id=%s",
                project_id,
                episodes_task_id,
            )
    except Exception:  # noqa: BLE001
        logger.exception("摘要后入队分集剧本失败 project_id=%s", project_id)

    return {
        "ok": True,
        "project_id": project_id,
        "assets": assets_result,
        "episode_script_task_id": episodes_task_id,
        "kind": "text",
        "text_content": format_summary_text(summary),
    }


# ---------- episode scripts ----------


async def dispatch_episode_scripts_job(
    db: AsyncSession,
    user: User,
    project_id: int,
    force: bool = False,
    episode_number: int | None = None,
    draft: str | None = None,
    generate_mode: str | None = None,
) -> int:
    """入队分集剧本任务；可指定单集优化或创意→摘要/正文。"""
    project = await db.get(DramaProject, project_id, options=[selectinload(DramaProject.script)])
    total = 1
    if episode_number:
        total = 1
    elif project and project.script and isinstance(project.script.summary, dict):
        total = int(project.script.summary.get("episodeCount") or 1)
    ep_key = str(int(episode_number)) if episode_number else "all"
    mode_key = (generate_mode or "optimize").strip() or "optimize"
    task_id = await _enqueue_drama_task(
        db,
        user,
        task_type="episode_script",
        project_id=project_id,
        dedupe_suffix=f"{project_id}:force:{int(force)}:ep:{ep_key}:mode:{mode_key}",
        payload={
            "project_id": project_id,
            "force": force,
            "total": total,
            "episode_number": int(episode_number) if episode_number else None,
            "draft": (draft or "").strip() or None,
            "generate_mode": mode_key if episode_number else None,
        },
    )
    logger.info(
        "dispatch 分集剧本 → task_id=%s project_id=%s episode_number=%s mode=%s",
        task_id,
        project_id,
        episode_number,
        mode_key,
    )
    return task_id


async def run_episode_scripts_job(
    project_id: int,
    force: bool = False,
    task_id: int | None = None,
    episode_number: int | None = None,
    draft: str | None = None,
    generate_mode: str | None = None,
) -> dict[str, Any]:
    # Worker：大纲 + 循环逐集直到完成；也可只优化指定集
    logger.info(
        "开始生成分集剧本 project_id=%s force=%s task_id=%s episode_number=%s mode=%s",
        project_id,
        force,
        task_id,
        episode_number,
        generate_mode,
    )
    if episode_number:
        return await _run_single_episode_script_job(
            project_id,
            int(episode_number),
            draft=(draft or "").strip(),
            task_id=task_id,
            generate_mode=(generate_mode or "optimize").strip() or "optimize",
        )

    async def _sync_task_progress(done: int, total: int, *, phase: str, message: str) -> None:
        if not task_id:
            return
        from app.services.tasks.service import append_task_event

        async with AsyncSessionLocal() as tdb:
            task_row = await tdb.get(TaskRun, int(task_id))
            if not task_row or task_row.status not in {"leased", "running", "pending"}:
                return
            if total <= 0:
                pct = 0
            elif done >= total:
                pct = 100
            else:
                pct = min(99, max(1, int(round(100 * done / total))))
            task_row.progress_percent = pct
            task_row.current_step_key = "episode_script"
            task_row.current_step_status = phase
            await append_task_event(
                tdb,
                int(task_id),
                event_type="task.progress",
                status=task_row.status,
                phase=phase,
                message=message,
                payload={"done": done, "total": total, "progress_percent": pct},
            )
            await tdb.commit()

    async with AsyncSessionLocal() as db:
        project = await db.get(
            DramaProject,
            project_id,
            options=[selectinload(DramaProject.script)],
        )
        if not project or not project.script or not project.script.summary:
            logger.warning("分集剧本失败：缺少摘要 project_id=%s", project_id)
            return {"ok": False, "error": "missing_summary"}

        script = await locked_script(db, project_id) if project.team_id is not None else project.script
        summary = script.summary if isinstance(script.summary, dict) else {}
        existing: list = []
        content = script.episode_content
        if isinstance(content, dict) and isinstance(content.get("episodes"), list):
            existing = list(content["episodes"])
        elif isinstance(content, list):
            existing = list(content)

        total = resolve_episode_target(summary, project.params, script.params)
        if summary.get("episodeCount") != total:
            summary = {**summary, "episodeCount": total}
            script.summary = summary

        creative = (script.source or "").strip()
        try:
            if force and existing:
                params0 = dict(script.params or {})
                status0 = str(params0.get("episode_content_status") or "")
                # generating=本轮已开跑（含进程重启续跑），勿再因 force 清空已生成正文
                if status0 != "generating":
                    existing = [
                        {
                            "episodeNumber": int(item.get("episodeNumber") or 0),
                            "title": str(item.get("title") or f"第 {item.get('episodeNumber')} 集"),
                            "body": "",
                        }
                        for item in existing
                        if isinstance(item, dict) and int(item.get("episodeNumber") or 0) >= 1
                    ]
                    script.episode_content = {"episodes": existing}
                    params0["episode_content_status"] = "generating"
                    params0["episode_content_error"] = None
                    script.params = params0
                    await db.flush()
                    logger.info("已清空分集正文准备重写 project_id=%s total=%s", project_id, total)
                else:
                    logger.info(
                        "force 续跑跳过清空 project_id=%s done=%s/%s",
                        project_id,
                        count_completed_episodes(existing, total),
                        total,
                    )

            existing, outline_used_llm = await ensure_episode_outline(creative, summary, existing, total)
            script.episode_content = {"episodes": existing}
            if project.team_id is not None:
                bump_episode_versions(script, [int(row.get("episodeNumber") or 0) for row in existing])
            params_outline = dict(script.params or {})
            params_outline["episode_content_status"] = "generating"
            script.params = params_outline
            await db.flush()
            if outline_used_llm:
                user = await db.get(User, project.user_id)
                if user:
                    await record_llm_chat_line(
                        db,
                        user_id=user.id,
                        domain="drama",
                        drama_project_id=project.id,
                    )
            logger.info("分集大纲就绪 project_id=%s titles=%s", project_id, len(existing))
            await _sync_task_progress(
                count_completed_episodes(existing, total),
                total,
                phase="generating",
                message=f"分集大纲就绪，开始生成 {count_completed_episodes(existing, total)}/{total}",
            )

            guard = 0
            while True:
                missing = auto_missing_episode_numbers(existing, total)
                if not missing:
                    break
                generated = count_completed_episodes(existing, total)
                logger.info(
                    "生成下一集 project_id=%s progress=%s/%s missing=%s",
                    project_id,
                    generated,
                    total,
                    missing[:5],
                )
                batch = await run_episode_script_batch(
                    summary,
                    existing,
                    batch_size=1,
                    total=total,
                    creative=creative,
                )
                existing = merge_episode_bodies(existing, batch)
                script.episode_content = {"episodes": existing}
                if project.team_id is not None:
                    bump_episode_versions(script, [int(row.get("episodeNumber") or 0) for row in batch])
                params = dict(script.params or {})
                params["episode_content_status"] = "generating"
                params["episode_count"] = total
                params["episode_content_progress"] = {
                    "done": count_completed_episodes(existing, total),
                    "total": total,
                }
                script.params = params
                await db.commit()
                user = await db.get(User, project.user_id)
                if user:
                    await record_line(
                        db,
                        user_id=user.id,
                        project_id=None,
                        drama_project_id=project.id,
                        billing_key="llm_chat",
                        model=get_settings().model_llm,
                        estimated=True,
                        domain="drama",
                    )
                    await db.commit()
                await db.refresh(script)
                content = script.episode_content
                if isinstance(content, dict) and isinstance(content.get("episodes"), list):
                    existing = list(content["episodes"])
                done_now = count_completed_episodes(existing, total)
                logger.info(
                    "分集进度更新 project_id=%s progress=%s/%s",
                    project_id,
                    done_now,
                    total,
                )
                await _sync_task_progress(
                    done_now,
                    total,
                    phase="generating",
                    message=f"分集剧本进度 {done_now}/{total}",
                )
                # 本批刚写完的集：立刻补抽资产并入队 AI 分镜（不必等全集）
                finished_numbers = sorted(
                    {
                        int(item.get("episodeNumber") or 0)
                        for item in batch
                        if isinstance(item, dict) and int(item.get("episodeNumber") or 0) >= 1
                    }
                )
                for ep_no in finished_numbers:
                    try:
                        await kickoff_fragment_plans(
                            project_id,
                            episode_numbers=[ep_no],
                            reseed_assets=True,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "单集剧本后自动分镜异常 project_id=%s episode=%s",
                            project_id,
                            ep_no,
                        )
                guard += 1
                if guard > max(total * 2, 24):
                    raise RuntimeError(
                        f"分集生成未完成（{count_completed_episodes(existing, total)}/{total}）"
                    )
                if not batch:
                    raise RuntimeError("分集生成无进度")

            params = dict(script.params or {})
            params["episode_content_status"] = "completed"
            params["episode_content_error"] = None
            params["episode_count"] = total
            params["episode_content_progress"] = {"done": total, "total": total}
            script.params = params
            await db.commit()
            await _sync_task_progress(total, total, phase="succeeded", message=f"分集剧本全部完成 {total}/{total}")
            logger.info("分集剧本全部完成 project_id=%s total=%s", project_id, total)
            # 收尾：补抽遗漏资产，并为尚未入队分镜的集兜底入队
            try:
                pipeline = await kickoff_fragment_plans(
                    project_id,
                    episode_numbers=None,
                    reseed_assets=True,
                )
            except Exception:  # noqa: BLE001
                logger.exception("全集收尾自动分镜异常 project_id=%s", project_id)
                pipeline = {"ok": False, "error": "kickoff_failed"}
            return {
                "ok": True,
                "project_id": project_id,
                "total": total,
                "post_pipeline": pipeline,
                "kind": "text",
                "episodes": existing,
            }
        except Exception as exc:  # noqa: BLE001
            params = dict(script.params or {})
            params["episode_content_status"] = "failed"
            params["episode_content_error"] = str(exc)[:500]
            script.params = params
            await db.commit()
            logger.exception("分集剧本失败 project_id=%s err=%s", project_id, exc)
            return {"ok": False, "error": str(exc)[:500]}


async def _run_single_episode_script_job(
    project_id: int,
    episode_number: int,
    draft: str,
    task_id: int | None = None,
    generate_mode: str = "optimize",
) -> dict[str, Any]:
    """单集：草稿优化 / 创意→摘要 / 创意+摘要→正文 / 一键整集。"""
    mode = (generate_mode or "optimize").strip() or "optimize"
    logger.info(
        "开始单集剧本 project_id=%s episode_number=%s mode=%s draft_len=%s",
        project_id,
        episode_number,
        mode,
        len(draft or ""),
    )

    async with AsyncSessionLocal() as db:
        project = await db.get(
            DramaProject,
            project_id,
            options=[selectinload(DramaProject.script)],
        )
        if not project or not project.script or not project.script.summary:
            logger.warning("单集剧本失败：缺少摘要 project_id=%s", project_id)
            return {"ok": False, "error": "missing_summary"}

        team_id = project.team_id
        script = await locked_script(db, project_id) if team_id is not None else project.script
        summary = script.summary if isinstance(script.summary, dict) else {}
        existing: list = []
        content = script.episode_content
        if isinstance(content, dict) and isinstance(content.get("episodes"), list):
            existing = list(content["episodes"])
        elif isinstance(content, list):
            existing = list(content)

        params = dict(script.params or {})
        params["episode_optimize_status"] = "generating"
        params["episode_optimize_number"] = int(episode_number)
        params["episode_optimize_mode"] = mode
        params.pop("episode_optimize_error", None)
        script.params = params
        if project.team_id is not None:
            set_episode_job_state(script, episode_number, "generating", mode=mode)
        await db.commit()

        project_source = (script.source or "").strip()
        current = next(
            (
                item
                for item in existing
                if isinstance(item, dict) and int(item.get("episodeNumber") or 0) == int(episode_number)
            ),
            None,
        )
        ep_creative = str((current or {}).get("creative") or "").strip()
        ep_summary = str((current or {}).get("summary") or "").strip()
        ep_title = str((current or {}).get("title") or "").strip() or f"第 {episode_number} 集"
        origin = str((current or {}).get("origin") or "")

        # 已有定妆角色名，约束单集 LLM 称呼
        char_name_rows = (
            await db.execute(
                select(DramaAsset.name).where(
                    DramaAsset.project_id == project.id,
                    DramaAsset.type == "character",
                )
            )
        ).scalars().all()
        character_asset_names = [str(n).strip() for n in char_name_rows if str(n or "").strip()]

        try:
            if mode == "summary":
                if len(ep_creative) < 20:
                    raise ValueError("请先填写本集原始创意（至少 20 字）")
                batch = await run_episode_summary_from_creative(
                    summary,
                    existing,
                    int(episode_number),
                    ep_creative,
                    project_source=project_source,
                    title=ep_title,
                    character_asset_names=character_asset_names,
                )
            elif mode == "body":
                batch = await run_episode_body_from_brief(
                    summary,
                    existing,
                    int(episode_number),
                    creative=ep_creative,
                    summary=ep_summary,
                    project_source=project_source,
                    title=ep_title,
                    character_asset_names=character_asset_names,
                )
            elif mode == "full":
                if len(ep_summary) < 40 and len(ep_creative) < 20:
                    raise ValueError("请先填写本集梗概（至少 40 字）或创作备注（至少 20 字）")
                batch = await run_episode_full_from_creative(
                    summary,
                    existing,
                    int(episode_number),
                    ep_creative,
                    project_source=project_source,
                    title=ep_title,
                    character_asset_names=character_asset_names,
                    summary=ep_summary,
                )
            elif mode == "brief":
                ep_body = str((current or {}).get("body") or (current or {}).get("content") or "").strip()
                if len(ep_body) < 80:
                    raise ValueError("请先有本集剧本内容，再补齐创意与摘要")
                batch = await run_episode_brief_from_body(
                    summary,
                    existing,
                    int(episode_number),
                    ep_body,
                    project_source=project_source,
                    title=ep_title,
                    character_asset_names=character_asset_names,
                )
            else:
                if not draft or len(draft) < 20:
                    raise ValueError("请先输入本集剧本草稿，再让 AI 优化")
                batch = await run_episode_script_from_draft(
                    summary,
                    existing,
                    int(episode_number),
                    draft,
                    creative=project_source,
                    character_asset_names=character_asset_names,
                )
            if origin == "manual":
                for item in batch:
                    item["origin"] = "manual"
            # summary 模式不要用空 body 覆盖已有正文
            if mode == "summary" and current:
                for item in batch:
                    item["body"] = str(current.get("body") or "")
            # 写回前刷新，避免覆盖用户在其他集的编辑
            if project.team_id is not None:
                script = await locked_script(db, project_id)
            else:
                await db.refresh(script)
            fresh_content = script.episode_content
            if isinstance(fresh_content, dict) and isinstance(fresh_content.get("episodes"), list):
                existing = list(fresh_content["episodes"])
            elif isinstance(fresh_content, list):
                existing = list(fresh_content)
            existing = merge_episode_bodies(existing, batch, prefer_incoming=True)
            container = dict(fresh_content) if isinstance(fresh_content, dict) else {}
            container["episodes"] = existing
            script.episode_content = container
            if team_id is not None:
                bump_episode_versions(script, [int(episode_number)])
            # 先提交单集正文，释放共享 JSON 行锁，再处理后续资源。
            if project.team_id is not None:
                await db.commit()
                # 增量抽取仅新增资产；项目行锁避免不同集重复创建同名资产。
                await db.execute(select(DramaProject.id).where(DramaProject.id == project_id).with_for_update())

            assets_created = 0
            assets_reused = 0
            if mode in {"body", "full", "optimize"}:
                try:
                    seed_result = await seed_assets_from_episode_body(
                        db, project, int(episode_number)
                    )
                    assets_created = int(seed_result.created_count)
                    assets_reused = int(seed_result.reused_count)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "单集正文后增量 seed 失败 project_id=%s episode=%s",
                        project_id,
                        episode_number,
                    )

            if project.team_id is not None:
                await db.flush()
                script = await locked_script(db, project_id)
            params = dict(script.params or {})
            params["episode_optimize_status"] = "completed"
            params["episode_optimize_number"] = int(episode_number)
            params["episode_optimize_mode"] = mode
            params["episode_optimize_assets_created"] = assets_created
            params["episode_optimize_assets_reused"] = assets_reused
            params.pop("episode_optimize_error", None)
            if str(params.get("episode_content_status") or "") != "generating":
                params["episode_content_status"] = "completed"
            script.params = params
            if project.team_id is not None:
                set_episode_job_state(script, episode_number, "completed", mode=mode, assets_created=assets_created, assets_reused=assets_reused)
            await db.commit()
            user = await db.get(User, project.user_id)
            if user:
                await record_line(
                    db,
                    user_id=user.id,
                    project_id=None,
                    drama_project_id=project.id,
                    billing_key="llm_chat",
                    model=get_settings().model_llm,
                    estimated=True,
                    domain="drama",
                )
                await db.commit()
            if task_id:
                from app.services.tasks.service import append_task_event

                task_row = await db.get(TaskRun, int(task_id))
                if task_row and task_row.status in {"leased", "running", "pending"}:
                    task_row.progress_percent = 100
                    task_row.current_step_key = "episode_script"
                    task_row.current_step_status = "succeeded"
                    await append_task_event(
                        db,
                        int(task_id),
                        event_type="task.progress",
                        status=task_row.status,
                        phase="succeeded",
                        message=f"第 {episode_number} 集已生成（{mode}）",
                        payload={
                            "episode_number": episode_number,
                            "generate_mode": mode,
                            "progress_percent": 100,
                            "assets_created_count": assets_created,
                            "assets_reused_count": assets_reused,
                        },
                    )
                    await db.commit()
            logger.info(
                "单集剧本完成 project_id=%s episode_number=%s mode=%s assets_created=%s",
                project_id,
                episode_number,
                mode,
                assets_created,
            )
            # 正文类模式：立刻抽资产（全量补齐）并入队本集 LLM 分镜
            pipeline: dict[str, Any] | None = None
            if mode in {"body", "full", "optimize"}:
                try:
                    # 团队单集任务只新增本集资产，不运行全剧刷新以免越过其他资产租约。
                    pipeline = await kickoff_fragment_plans(
                        project_id,
                        episode_numbers=[int(episode_number)],
                        reseed_assets=project.team_id is None,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "单集剧本后自动抽资产/分镜异常 project_id=%s episode=%s",
                        project_id,
                        episode_number,
                    )
                    pipeline = {"ok": False, "error": "kickoff_failed"}
            return {
                "ok": True,
                "project_id": project_id,
                "episode_number": episode_number,
                "generate_mode": mode,
                "assets_created_count": assets_created,
                "assets_reused_count": assets_reused,
                "post_pipeline": pipeline,
                "kind": "text",
                "episodes": batch,
            }
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            if team_id is not None:
                script = await locked_script(db, project_id)
            else:
                await db.refresh(script)
            params = dict(script.params or {})
            params["episode_optimize_status"] = "failed"
            params["episode_optimize_number"] = int(episode_number)
            params["episode_optimize_mode"] = mode
            params["episode_optimize_error"] = str(exc)[:500]
            params["episode_optimize_assets_created"] = 0
            params["episode_optimize_assets_reused"] = 0
            script.params = params
            if team_id is not None:
                set_episode_job_state(script, episode_number, "failed", mode=mode, error=str(exc)[:500])
            await db.commit()
            logger.exception(
                "单集剧本失败 project_id=%s episode_number=%s mode=%s err=%s",
                project_id,
                episode_number,
                mode,
                exc,
            )
            return {"ok": False, "error": str(exc)[:500]}


# ---------- episode fragment plan (LLM) ----------


async def run_episode_fragment_plan_job(
    episode_id: int,
    *,
    fallback_rules: bool = True,
    subtitle_enabled: bool | None = None,
    force: bool = False,
) -> dict[str, Any]:
    # Worker：LLM 规划本集分镜并落库；失败可选回退规则切分
    from app.services.drama.build_fragments import build_fragments_from_episode_body
    from app.services.drama.fragment_plan import plan_fragments_with_llm
    from app.services.drama.llm import DramaLlmUnavailableError
    from app.services.drama.seed import (
        _episode_bodies,
        _fragment_is_protected,
        replace_episode_fragments_with_drafts,
        resolve_episode_script_body,
    )

    logger.info("开始单集 LLM 分镜 episode_id=%s", episode_id)
    async with AsyncSessionLocal() as db:
        episode = await db.get(
            DramaEpisode,
            episode_id,
            options=[
                selectinload(DramaEpisode.fragments).selectinload(
                    DramaEpisodeFragment.asset_references
                ),
                selectinload(DramaEpisode.project).selectinload(DramaProject.script),
            ],
        )
        if not episode or not episode.project:
            logger.warning("单集分镜失败：缺少分集 episode_id=%s", episode_id)
            return {"ok": False, "error": "missing_episode"}

        project = episode.project
        script = project.script
        body = resolve_episode_script_body(script.episode_content if script else None, episode)
        if not (body or "").strip():
            params = dict(episode.params or {})
            params["fragment_plan_status"] = "failed"
            params["fragment_plan_error"] = "本集剧本正文为空，无法分镜"
            episode.params = params
            await db.commit()
            return {"ok": False, "error": "empty_body"}

        assets_result = await db.execute(
            select(DramaAsset).where(DramaAsset.project_id == project.id)
        )
        assets = list(assets_result.scalars().all())

        # 本剧更早分集已介绍角色（跨集去重）
        from app.services.drama.build_fragments import collect_series_introduced_names

        siblings_result = await db.execute(
            select(DramaEpisode)
            .where(DramaEpisode.project_id == project.id)
            .options(selectinload(DramaEpisode.fragments))
        )
        siblings = list(siblings_result.scalars().all())
        ep_params = episode.params if isinstance(episode.params, dict) else {}
        raw_subtitles = (
            subtitle_enabled
            if subtitle_enabled is not None
            else (
                False
                if ep_params.get("subtitleMode") == "post"
                else True if ep_params.get("subtitleMode") == "model" else ep_params.get("subtitleEnabled", False)
            )
        )
        if isinstance(raw_subtitles, str):
            normalized = raw_subtitles.strip().lower()
            include_subtitles = normalized not in {"0", "false", "no", "off", ""}
        elif isinstance(raw_subtitles, (int, float)):
            include_subtitles = raw_subtitles != 0
        else:
            include_subtitles = raw_subtitles is not False
        from app.services.drama.build_seedance_generate_body import (
            resolve_episode_character_intro,
        )

        include_character_intro = resolve_episode_character_intro(ep_params)
        ep_no = int(ep_params.get("episodeNumber") or 0) or None
        from app.services.agent.compose import parse_skill_ids

        skill_ids = (
            parse_skill_ids(ep_params.get("fragment_plan_skill_ids"))
            if "fragment_plan_skill_ids" in ep_params
            else None
        )
        already_introduced = collect_series_introduced_names(
            siblings,
            before_episode_number=ep_no,
            exclude_episode_id=episode.id,
        )

        # force：覆盖本集全部分镜；否则锁定已有视频/手改分镜并续拆
        from app.services.drama.build_fragments import extract_introduced_names_from_content

        protected_frags: list[DramaEpisodeFragment] = []
        locked_summaries: list[str] = []
        if not force:
            protected_frags = sorted(
                [f for f in (episode.fragments or []) if _fragment_is_protected(f)],
                key=lambda f: int(f.sort_order or 0),
            )
            for frag in protected_frags:
                for name in extract_introduced_names_from_content(frag.content or ""):
                    already_introduced.add(name)
                # 生产元信息不能当作剧情，画面/对白标签后的正文必须保留。
                narr = summarize_locked_fragment(frag.content or "", assets)
                locked_summaries.append(narr or f"分镜#{frag.sort_order}")

        mode_used = "llm"
        summary = script.summary if script and isinstance(script.summary, dict) else {}
        from app.services.drama.character_intro_llm import prepare_character_intro_overrides

        all_bodies = _episode_bodies(script.episode_content if script else None)
        if body and body not in all_bodies:
            all_bodies.append(body)
        character_assets = [a for a in assets if getattr(a, "type", "") == "character"]
        intro_overrides = (
            await prepare_character_intro_overrides(
                character_assets,
                summary=summary,
                episode_bodies=all_bodies,
                story_type=str(summary.get("storyType") or "") or None,
            )
            if include_character_intro
            else {}
        )
        continuation = bool(locked_summaries) and not force
        try:
            drafts = await plan_fragments_with_llm(
                episode_name=episode.name or "",
                episode_body=body,
                assets=assets,
                episode_number=ep_no,
                project_title=project.title or "",
                story_type=str(summary.get("storyType") or "") or None,
                one_line_story=str(summary.get("oneLineStory") or "") or None,
                synopsis=str(summary.get("synopsis") or "") or None,
                core_hook=str(summary.get("coreHook") or "") or None,
                already_introduced=already_introduced,
                summary=summary,
                episode_bodies=all_bodies,
                intro_overrides=intro_overrides,
                locked_summaries=locked_summaries or None,
                db=db,
                user_id=project.user_id,
                skill_ids=skill_ids,
                include_subtitles=include_subtitles,
                include_character_intro=include_character_intro,
            )
        except (DramaLlmUnavailableError, RuntimeError, Exception) as exc:  # noqa: BLE001
            logger.exception("LLM 分镜失败 episode_id=%s err=%s", episode_id, exc)
            if not fallback_rules:
                params = dict(episode.params or {})
                params["fragment_plan_status"] = "failed"
                params["fragment_plan_error"] = str(exc)[:500]
                episode.params = params
                await db.commit()
                return {"ok": False, "error": str(exc)[:500]}
            drafts = build_fragments_from_episode_body(
                body,
                assets,
                already_introduced=already_introduced,
                summary=summary,
                episode_bodies=all_bodies,
                intro_overrides=intro_overrides,
                include_subtitles=include_subtitles,
                include_character_intro=include_character_intro,
            )
            mode_used = "rules_fallback"
            continuation = False

        await replace_episode_fragments_with_drafts(
            db,
            episode,
            body,
            assets,
            drafts,
            preserve_protected=not force,
            continuation=continuation,
        )
        # 重新加载 params（replace 会写 fingerprint）
        params = dict(episode.params or {})
        params["fragment_plan_status"] = "completed"
        params["fragment_plan_mode"] = mode_used
        params.pop("fragment_plan_error", None)
        params["fragment_plan_count"] = len(protected_frags) + len(drafts)
        params["fragment_plan_preserved"] = len(protected_frags)
        episode.params = params
        user = await db.get(User, project.user_id)
        if user and mode_used == "llm":
            await record_line(
                db,
                user_id=user.id,
                project_id=None,
                drama_project_id=project.id,
                billing_key="llm_chat",
                model=get_settings().model_llm,
                estimated=True,
                domain="drama",
            )
        await db.commit()
        logger.info(
            "单集分镜完成 episode_id=%s mode=%s new=%s preserved=%s continuation=%s",
            episode_id,
            mode_used,
            len(drafts),
            len(protected_frags),
            continuation,
        )
        return {
            "ok": True,
            "mode": mode_used,
            "count": len(protected_frags) + len(drafts),
            "preserved": len(protected_frags),
            "kind": "text",
            "fragments": drafts,
        }


# ---------- episode video (task platform) ----------

# 任务平台（NIO）：Worker 短生命周期 — prepare → submit → 注册 awaiting_poll，由 Selector 轮询。
async def submit_fragment_video_task(task: TaskRun) -> dict[str, Any]:
    from app.services.tasks.generation_metadata import prepared_generation_params
    from app.services.tasks.generation_references import public_references
    from app.services.tasks.service import append_task_event, get_task_for_runtime, set_task_step_state

    payload = task.payload if isinstance(task.payload, dict) else {}
    nio_phase = str(payload.get("nio_phase") or "prepare")
    fragment_ids = payload.get("fragment_ids") or []
    fragment_id = int(task.fragment_id or (fragment_ids[0] if fragment_ids else 0))
    episode_id = int(task.episode_id or payload.get("episode_id") or 0)
    user_id = int(task.requested_by)
    if fragment_id <= 0 or episode_id <= 0:
        raise ValueError("任务缺少 episode_id / fragment_id")

    async with AsyncSessionLocal() as db:
        task_row = await get_task_for_runtime(db, task.id)
        if not task_row:
            return {"ok": False, "error": "missing_task"}
        ep = await db.get(
            DramaEpisode,
            episode_id,
            options=[selectinload(DramaEpisode.project).selectinload(DramaProject.script)],
        )
        if not ep or not ep.project:
            raise ValueError("分集或项目不存在")
        project = ep.project
        user = await db.get(User, user_id)
        if not user:
            raise ValueError("用户不存在")
        frag = await db.get(
            DramaEpisodeFragment,
            fragment_id,
            options=[
                selectinload(DramaEpisodeFragment.asset_references).selectinload(
                    DramaFragmentAssetRef.asset
                )
            ],
        )
        if not frag or frag.episode_id != episode_id:
            raise ValueError("分镜不存在")

        if _is_episode_video_cancelled(episode_id):
            params = dict(frag.params or {})
            params.pop("generation_attempts", None)
            params["generation"] = {"status": "cancelled", "error": "任务已取消"}
            frag.params = params
            await db.commit()
            return {"ok": False, "cancelled": True}

        gen = frag.params.get("generation") if isinstance(frag.params, dict) else None
        # 仅统计「同一次任务」内 prepare 被重新拉起的次数（中断重入等），
        # 用户再次点生成 / 任务重试会清零 generation_attempts。
        persisted_attempts = int((frag.params or {}).get("generation_attempts") or 0)
        prev_attempts = persisted_attempts
        if isinstance(gen, dict):
            # queued 态不应继承上次失败的 attempts 展示值
            if str(gen.get("status") or "") in {"queued", "idle", "cancelled", "done"}:
                prev_attempts = persisted_attempts
            else:
                prev_attempts = max(prev_attempts, int(gen.get("attempts") or 0))
        max_attempts = max(1, int(get_settings().drama_fragment_max_attempts or 3))
        attempts = prev_attempts + 1 if nio_phase == "prepare" else int(payload.get("generation_attempts") or prev_attempts + 1)
        if nio_phase == "prepare" and attempts > max_attempts:
            params = dict(frag.params or {})
            # raise 用纯超限文案；展示拼接交给 build_failed_generation_params / _fail_task
            limit_msg = f"分镜内部自动重试超过上限（{max_attempts} 次）"
            params["generation"] = build_failed_generation_params(
                gen if isinstance(gen, dict) else None,
                limit_msg,
                attempts=prev_attempts,
                attempt_limit=max_attempts,
            )
            frag.params = params
            await db.commit()
            raise RuntimeError(limit_msg)

        if nio_phase == "prepare":
            params = dict(frag.params or {})
            params["generation_attempts"] = attempts
            params["generation"] = {
                "status": "running",
                "phase": "assets",
                "attempts": attempts,
                "attempt_limit": max_attempts,
            }
            frag.params = params
            task_row.progress_percent = max(int(task_row.progress_percent or 0), 10)
            task_row.current_step_status = "preparing"
            await db.commit()

            prepared = await prepare_fragment_video_for_submit(
                db,
                user,
                project,
                frag,
                model_id=(payload.get("model_id") or None),
            )
            now = datetime.now(UTC)
            next_payload = dict(payload)
            next_payload["nio_phase"] = "submit"
            next_payload["generation_attempts"] = attempts
            next_payload["attempt_limit"] = max_attempts
            next_payload["prepared"] = serialize_fragment_video_prepared(prepared)
            next_payload["generation_params"] = prepared_generation_params(next_payload["prepared"])
            next_payload["generation_references"] = public_references(next_payload["prepared"])
            task_row.status = "pending"
            task_row.progress_percent = 25
            task_row.current_step_status = "prepared"
            task_row.payload = next_payload
            task_row.next_action_at = now
            task_row.lease_token = None
            task_row.lease_until = None
            step = task_row.steps[0] if task_row.steps else None
            set_task_step_state(task_row, step, status="prepared", now=now)
            await append_task_event(
                db,
                task_row.id,
                event_type="task.prepared",
                status=task_row.status,
                phase=task_row.current_step_key,
                message="参考资源就绪，重新入队提交",
            )
            await db.commit()
            return {"deferred": True, "nio_phase": "submit"}

        # nio_phase == submit：仅 HTTP 注册上游，立即释放 Worker
        prepared_raw = payload.get("prepared")
        if not isinstance(prepared_raw, dict):
            prepared = await prepare_fragment_video_for_submit(
                db,
                user,
                project,
                frag,
                model_id=(payload.get("model_id") or None),
            )
        else:
            prepared = deserialize_fragment_video_prepared(prepared_raw)

        params = dict(frag.params or {})
        params["generation"] = {
            "status": "running",
            "phase": "submit",
            "attempts": attempts,
            "attempt_limit": max_attempts,
        }
        frag.params = params
        task_row.progress_percent = max(int(task_row.progress_percent or 0), 30)
        task_row.current_step_status = "submitting"
        serialized = serialize_fragment_video_prepared(prepared)
        generation_params = prepared_generation_params(serialized)
        generation_references = public_references(serialized)
        task_row.payload = {**payload, "generation_params": generation_params,
                            "generation_references": generation_references}
        await db.commit()

        provider_task_id = await submit_prepared_fragment_video(prepared, project_id=project.id)
        poll_interval = max(1.0, float(get_settings().ark_video_poll_interval or 8.0))
        now = datetime.now(UTC)
        # 提交成功后立刻写成 running/polling，避免前端长期停在「排队」
        params = dict(frag.params or {})
        params["generation"] = {
            "status": "running",
            "phase": "polling",
            "attempts": attempts,
            "attempt_limit": max_attempts,
            "message": "上游生成中",
            "provider_task_id": provider_task_id,
        }
        frag.params = params
        task_row.status = "awaiting_poll"
        task_row.provider_task_id = provider_task_id
        task_row.progress_percent = 40
        task_row.current_step_status = "polling"
        task_row.next_action_at = now + timedelta(seconds=poll_interval)
        task_row.lease_token = None
        task_row.lease_until = None
        next_payload = dict(payload)
        next_payload.pop("prepared", None)
        next_payload["generation_params"] = generation_params
        next_payload["generation_references"] = generation_references
        next_payload["nio_phase"] = "poll"
        next_payload["generation_attempts"] = attempts
        next_payload["attempt_limit"] = max_attempts
        task_row.payload = next_payload
        step = task_row.steps[0] if task_row.steps else None
        set_task_step_state(task_row, step, status="polling", now=now)
        await append_task_event(
            db,
            task_row.id,
            event_type="task.registered",
            status=task_row.status,
            phase=task_row.current_step_key,
            message="已注册上游，Selector 非阻塞轮询",
            payload={"provider_task_id": provider_task_id},
        )
        await db.commit()
        return {"awaiting_poll": True, "provider_task_id": provider_task_id}


# 分镜视频收尾认领窗口：期内其它 poller 不得再入下载；需覆盖整段下载+OSS（常达数分钟）。
_FRAGMENT_FINALIZE_CLAIM_TTL = timedelta(minutes=10)


# 统一解析 TaskRun.next_action_at 的时区，便于与 now 比较。
def _aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# 分镜是否已落成片（崩溃恢复时可跳过重复下载）。
def _fragment_video_already_applied(frag: DramaEpisodeFragment | None) -> bool:
    if frag is None or not (frag.video or "").strip():
        return False
    params = frag.params if isinstance(frag.params, dict) else {}
    gen = params.get("generation") if isinstance(params.get("generation"), dict) else {}
    return str(gen.get("status") or "").strip().lower() == "done"


# 成片已 done 但任务仍 awaiting_poll：立刻补 complete（避免 UI 长期「生成中」）
async def reconcile_applied_fragment_video_tasks(
    db: AsyncSession,
    tasks: list[TaskRun],
) -> int:
    fixed = 0
    for task in tasks:
        if getattr(task, "task_type", None) != "fragment_video":
            continue
        if str(getattr(task, "status", "") or "") != "awaiting_poll":
            continue
        fid = getattr(task, "fragment_id", None)
        if fid is None:
            continue
        frag = await db.get(DramaEpisodeFragment, int(fid))
        if not _fragment_video_already_applied(frag):
            continue
        payload = task.payload if isinstance(task.payload, dict) else {}
        ok = await _recover_complete_fragment_video(
            db,
            int(task.id),
            fragment_id=int(fid),
            batch_key=task.batch_key,
            batch_index=int(payload.get("batch_index", 0)),
        )
        if ok:
            fixed += 1
    if fixed:
        logger.info("已补完成成片已落盘的分镜任务 count=%s", fixed)
    return fixed


# 行锁后补完成分镜视频任务；已非 awaiting_poll 则跳过，避免并发双 complete。
async def _recover_complete_fragment_video(
    db: AsyncSession,
    task_id: int,
    *,
    fragment_id: int,
    batch_key: str | None,
    batch_index: int,
    recovered: bool = True,
) -> bool:
    from app.services.billing.settlement import _lock_task
    from app.services.tasks.executor import _complete_task
    from app.services.tasks.service import activate_next_sequential_task

    locked = await _lock_task(db, int(task_id))
    if not locked or locked.status != "awaiting_poll":
        return False
    # 异步会话下 steps 懒加载会 MissingGreenlet，补完成前显式加载
    await db.refresh(locked, attribute_names=["steps"])
    # 先 complete（commit 后锁释放），再激活后续；避免 activate 提前 commit 导致并发双 complete
    locked.progress_percent = 100
    fragment = await db.get(DramaEpisodeFragment, int(fragment_id))
    result_payload: dict[str, Any] = {
        "ok": True, "fragment_id": int(fragment_id), "kind": "video",
        "urls": [fragment.video] if fragment and fragment.video else [],
    }
    if fragment:
        # Freeze metadata with this output; later fragment edits cannot rewrite task history.
        params = fragment.params if isinstance(fragment.params, dict) else {}
        generation = params.get("generation") if isinstance(params.get("generation"), dict) else {}
        if generation.get("video") == fragment.video:
            result_payload["media_info"] = {
                field: generation[key] for field, key in (
                    ("duration_sec", "video_duration_sec"), ("width", "video_width"), ("height", "video_height"))
                if isinstance(generation.get(key), (int, float)) and generation[key] > 0
            }
    if recovered:
        result_payload["recovered"] = True
    await _complete_task(db, locked, result_payload)
    await activate_next_sequential_task(db, batch_key, batch_index)
    payload = locked.payload if isinstance(locked.payload, dict) else {}
    if payload.get("sequential") and locked.drama_project_id:
        from app.services.tasks.service import rebalance_project_fragment_video_queue

        await rebalance_project_fragment_video_queue(
            db,
            int(locked.drama_project_id),
            sequential=True,
            user_id=int(locked.requested_by),
        )
    return True


async def _settle_cancelled_after_finalized(db: AsyncSession, task_id: int) -> bool:
    """取消在 finalizing 窗口内生效、但成片已下载落盘：按实际用量结算，终态保持 cancelled。

    若不收敛，usage_events 会永久 settled=False、冻结额被 _mark_cancelled 全额退回，
    形成钱货两失。settle_task 对 frozen 任务按 events 多退少补，对已结算任务幂等。
    不激活后续顺序任务（用户取消应阻断队列）。
    """
    from app.services.billing.settlement import _lock_task, settle_task
    from app.services.tasks.service import append_task_event, clear_finalizing_window

    locked = await _lock_task(db, task_id)
    if not locked:
        return False
    locked.payload = clear_finalizing_window(locked.payload)
    locked.status = "cancelled"
    locked.cancel_requested = True
    locked.current_step_status = "done"
    locked.progress_percent = 100
    locked.finished_at = datetime.now(UTC)
    locked.next_action_at = None
    locked.lease_token = None
    locked.lease_until = None
    # frozen：按已落账用量退差额；已 settled（竞态中先被结算）：幂等对齐
    await settle_task(db, task_id)
    await append_task_event(
        db,
        task_id,
        event_type="task.cancelled",
        status="cancelled",
        phase="fragment_video",
        message="取消在成片收尾窗口内生效，成片已交付，按实际用量结算",
    )
    await db.commit()
    return True


# 任务平台：轮询 awaiting_poll 的分镜视频任务。
async def poll_fragment_video_task(task_id: int) -> None:
    from app.services.ark import get_ark
    from app.services.billing.context import billing_scope, set_current_team_id
    from app.services.billing.settlement import _lock_task
    from app.services.tasks.executor import _fail_task
    from app.services.tasks.service import get_task_for_runtime

    async with billing_scope(task_id):
        async with AsyncSessionLocal() as db:
            task = await get_task_for_runtime(db, task_id)
            if not task or task.status != "awaiting_poll" or not task.provider_task_id:
                return
            set_current_team_id(task.team_id)
            from app.services.media_models.runtime import current_snapshot
            current_snapshot.set(task.billing_snapshot)
            payload = task.payload if isinstance(task.payload, dict) else {}
            fragment_ids = payload.get("fragment_ids") or []
            fragment_id = int(task.fragment_id or (fragment_ids[0] if fragment_ids else 0))
            episode_id = int(task.episode_id or payload.get("episode_id") or 0)
            user_id = int(task.requested_by)
            attempts = int(payload.get("generation_attempts") or 1)
            attempt_limit = int(payload.get("attempt_limit") or get_settings().drama_fragment_max_attempts or 3)
            poll_interval = max(1.0, float(get_settings().ark_video_poll_interval or 8.0))
            now = datetime.now(UTC)

            frag_probe = await db.get(DramaEpisodeFragment, fragment_id) if fragment_id > 0 else None
            if fragment_id <= 0 or frag_probe is None:
                await _fail_task(db, task, RuntimeError("分镜已变更，请重新生成"))
                return

            # 成片已落盘：优先补完成，不被 finalizing 认领窗口挡住
            if _fragment_video_already_applied(frag_probe):
                await _recover_complete_fragment_video(
                    db,
                    int(task.id),
                    fragment_id=fragment_id,
                    batch_key=task.batch_key,
                    batch_index=int(payload.get("batch_index", 0)),
                )
                return

            # 收尾认领窗口未到期：跳过，避免并发下载双记费
            if (task.current_step_status or "") == "finalizing":
                na = _aware_utc(task.next_action_at)
                if na is not None and na > now:
                    return

            if task.cancel_requested or _is_episode_video_cancelled(episode_id):
                await _fail_task(db, task, RuntimeError("任务已取消"))
                return

            # 旧 Kie 任务号不能拿去查 TokenFree，否则会一直轮询并占着冻结余额
            if str(payload.get("video_provider") or "") == "kie":
                await _fail_task(db, task, RuntimeError("已改为 TokenFree 通道，请重新生成本镜视频"))
                return

            result = await get_ark().fetch_task_once(task.provider_task_id)
            if result.status == "running":
                task.next_action_at = now + timedelta(seconds=poll_interval)
                task.progress_percent = min(95, int(task.progress_percent or 40) + 3)
                task.current_step_status = "polling"
                await db.commit()
                return
            if result.status != "succeeded":
                frag = await db.get(DramaEpisodeFragment, fragment_id)
                if frag:
                    params = dict(frag.params or {})
                    prev_gen = params.get("generation") if isinstance(params.get("generation"), dict) else None
                    params["generation"] = build_failed_generation_params(
                        prev_gen if isinstance(prev_gen, dict) else None,
                        str(result.error or "上游生成失败"),
                        attempts=attempts,
                        attempt_limit=attempt_limit,
                    )
                    frag.params = params
                await _fail_task(db, task, RuntimeError(result.error or "上游生成失败"))
                return

            ep = await db.get(DramaEpisode, episode_id, options=[selectinload(DramaEpisode.project)])
            user = await db.get(User, user_id)
            frag = await db.get(DramaEpisodeFragment, fragment_id)
            if not ep or not ep.project or not user or not frag:
                await _fail_task(db, task, RuntimeError("分镜已变更，请重新生成"))
                return

            # 行锁认领：仅第一个收尾者进入下载；窗口内其余看到 finalizing 后退出
            locked = await _lock_task(db, int(task.id))
            if not locked or locked.status != "awaiting_poll":
                return
            if (locked.current_step_status or "") == "finalizing":
                na = _aware_utc(locked.next_action_at)
                if na is not None and na > now:
                    return
            # 等锁期间用户可能已取消：放弃下载，交由 executor 按未交付全额退款
            if locked.cancel_requested or _is_episode_video_cancelled(episode_id):
                await _fail_task(db, locked, RuntimeError("任务已取消"))
                return
            # 认领前后成片已在：行锁后只补完成（避免 apply 后异常释放认领再二次下载）
            if _fragment_video_already_applied(frag):
                await _recover_complete_fragment_video(
                    db,
                    int(locked.id),
                    fragment_id=fragment_id,
                    batch_key=locked.batch_key,
                    batch_index=int(payload.get("batch_index", 0)),
                )
                return
            # 置 finalizing 并写窗口截止：_mark_cancelled 在窗口内不做全额退款，
            # 防止下载/落账与取消并发造成 usage 悬空、钱货两失
            finalizing_until = now + _FRAGMENT_FINALIZE_CLAIM_TTL
            final_payload = dict(locked.payload if isinstance(locked.payload, dict) else {})
            final_payload["finalizing_until"] = finalizing_until.isoformat()
            locked.payload = final_payload
            locked.current_step_status = "finalizing"
            locked.progress_percent = max(int(locked.progress_percent or 0), 90)
            locked.next_action_at = finalizing_until
            await db.commit()

            try:
                local_video, local_last_frame = await get_ark().save_video_assets_from_result(
                    result,
                    project_id=ep.project.id,
                    shot_no=fragment_id,
                )
                payload = task.payload if isinstance(task.payload, dict) else {}
                await apply_fragment_video_assets(
                    db,
                    user,
                    ep.project,
                    frag,
                    local_video=local_video,
                    local_last_frame=local_last_frame,
                    attempts=attempts,
                    attempt_limit=attempt_limit,
                    task_result=result,
                    provider_task_id=task.provider_task_id,
                    model_id=str(payload.get("model_id") or "") or None,
                )
                # apply 已 commit：行锁复查。下载期间用户可能已取消（status=cancel_requested），
                # 此时不能走常规 complete，也不能放任 frozen 全额退款，按实际用量结算为 cancelled。
                async with AsyncSessionLocal() as recheck_db:
                    rechecked = await _lock_task(recheck_db, int(task.id))
                    was_cancelled = bool(
                        rechecked
                        and (
                            rechecked.cancel_requested
                            or rechecked.status in ("cancel_requested", "cancelled")
                        )
                    )
                if was_cancelled:
                    async with AsyncSessionLocal() as cancel_db:
                        await _settle_cancelled_after_finalized(cancel_db, int(task.id))
                    return
                # 未取消：立刻把 next_action 拉回现在，complete 失败时也能马上被 Selector 捞到
                async with AsyncSessionLocal() as nudge_db:
                    nudged = await nudge_db.get(TaskRun, int(task_id))
                    if nudged and nudged.status == "awaiting_poll":
                        nudged.next_action_at = datetime.now(UTC)
                        await nudge_db.commit()
                # 与恢复路径同一套行锁 complete，避免 apply 后并发双 complete
                await _recover_complete_fragment_video(
                    db,
                    int(task_id),
                    fragment_id=fragment_id,
                    batch_key=task.batch_key,
                    batch_index=int(payload.get("batch_index", 0)),
                    recovered=False,
                )
            except BaseException:
                # 含 CancelledError：poller wait_for 超时会取消协程，必须释放认领，否则 next_action 卡数小时
                from app.services.tasks.service import clear_finalizing_window

                async with AsyncSessionLocal() as release_db:
                    stalled = await _lock_task(release_db, int(task_id))
                    if (
                        stalled
                        and stalled.status == "awaiting_poll"
                        and (stalled.current_step_status or "") == "finalizing"
                    ):
                        frag_done = await release_db.get(DramaEpisodeFragment, fragment_id)
                        finalized = _fragment_video_already_applied(frag_done)
                        if finalized and stalled.cancel_requested:
                            # 成片已落盘且用户在窗口内取消：按实结算（与成功路径同一收敛）
                            await _settle_cancelled_after_finalized(release_db, int(task.id))
                        elif finalized:
                            # 成片已落盘：只补 complete，勿退回 polling 以免误伤
                            stalled.payload = clear_finalizing_window(stalled.payload)
                            stalled.next_action_at = datetime.now(UTC)
                            await release_db.commit()
                        else:
                            # 未交付：退回 polling 并清窗口标记，取消可立即走全额退款
                            stalled.payload = clear_finalizing_window(stalled.payload)
                            stalled.current_step_status = "polling"
                            stalled.next_action_at = datetime.now(UTC) + timedelta(seconds=poll_interval)
                            await release_db.commit()
                raise


# ---------- asset image ----------


async def dispatch_asset_image_job(
    db: AsyncSession,
    user: User,
    project_id: int,
    user_id: int,
    prompt: str,
    asset_id: int | None = None,
    name: str | None = None,
    kind: str = "character",
    *,
    image_style_id: str | None = None,
    model_id: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
) -> int:
    """入队资产生图任务。"""
    task_id = await _enqueue_drama_task(
        db,
        user,
        task_type="asset_image",
        project_id=project_id,
        dedupe_suffix=f"{project_id}:asset:{asset_id or 0}",
        asset_id=asset_id,
        payload={
            "project_id": project_id,
            "user_id": user_id,
            "prompt": prompt,
            "asset_id": asset_id,
            "name": name,
            "kind": kind,
            "image_style_id": image_style_id,
            "model_id": model_id,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        },
        commit=False,
    )
    logger.info("dispatch 资产生图 → task_id=%s project_id=%s asset_id=%s", task_id, project_id, asset_id)
    return task_id


async def run_asset_image_job(
    project_id: int,
    user_id: int,
    prompt: str,
    asset_id: int | None = None,
    name: str | None = None,
    kind: str = "character",
    *,
    image_style_id: str | None = None,
    model_id: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
) -> dict[str, Any]:
    logger.info(
        "开始资产生图 project_id=%s asset_id=%s kind=%s name=%s style=%s model=%s",
        project_id,
        asset_id,
        kind,
        name,
        image_style_id,
        model_id,
    )
    async with AsyncSessionLocal() as db:
        project = (
            await db.execute(
                select(DramaProject)
                .where(DramaProject.id == project_id)
                .options(selectinload(DramaProject.script))
            )
        ).scalar_one_or_none()
        user = await db.get(User, user_id)
        if not project or not user:
            return {"ok": False, "error": "missing"}
        asset = None
        if asset_id:
            asset = await db.get(DramaAsset, asset_id)
            if not asset or asset.project_id != project_id:
                return {"ok": False, "error": "asset_not_found"}
            params = dict(asset.params or {})
            gen = dict(params.get("generation") or {})
            gen["status"] = "generating"
            gen["message"] = "生图中"
            params["generation"] = gen
            asset.params = params
            await db.commit()
        try:
            resolved_prompt = prompt
            if asset:
                resolved_prompt = await resolve_visual_prompt_for_asset(asset, project, prompt, db=db)
                params = dict(asset.params or {})
                params["visualPrompt"] = resolved_prompt
                if not str(params.get("visualImage") or "").strip():
                    params["visualImage"] = resolved_prompt
                asset.params = params
                await db.commit()
                await db.refresh(asset)
                logger.info(
                    "资产生图提示词已解析 project_id=%s asset_id=%s len=%s",
                    project_id,
                    asset_id,
                    len(resolved_prompt),
                )
            # refresh/查询会开启读事务；等待上游生图和并发槽位前归还连接。
            # expire_on_commit=False 保留已加载数据，生成结果随后另开事务写回。
            await db.commit()
            asset = await generate_asset_image(
                db,
                user,
                project,
                resolved_prompt,
                asset=asset,
                name=name,
                kind=kind,
                image_style_id=image_style_id,
                model_id=model_id,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
            )
            params = dict(asset.params or {})
            gen = dict(params.get("generation") or {})
            gen["status"] = "done"
            params["generation"] = gen
            asset.params = params
            await db.commit()
            logger.info(
                "资产生图完成 project_id=%s asset_id=%s url=%s",
                project_id,
                asset.id,
                (asset.url or asset.cover or "")[:80],
            )
            url = asset.url or asset.cover
            from app.services.tasks.generation_references import public_references
            metadata = (asset.params or {}).get("media_metadata")
            return {"ok": True, "asset_id": asset.id, "kind": "image", "urls": [url] if url else [],
                    **({"references": public_references(metadata["references"])}
                       if isinstance(metadata, dict) and "references" in metadata else {})}
        except Exception as exc:  # noqa: BLE001
            from app.services.exc_format import format_exception_message

            err_text = format_exception_message(exc, fallback="生图失败", limit=500)
            # flush 失败后 Session 不可继续查询；回滚未提交交付，再记录原始异常。
            await db.rollback()
            if asset_id:
                asset = await db.get(DramaAsset, asset_id)
                if asset:
                    params = dict(asset.params or {})
                    params["generation"] = {"status": "failed", "error": err_text[:400]}
                    asset.params = params
                    await db.commit()
            logger.exception(
                "资产生图失败 project_id=%s asset_id=%s err=%s",
                project_id,
                asset_id,
                err_text,
            )
            return {"ok": False, "error": err_text}


# ---------- asset video ----------


async def dispatch_asset_video_job(
    db: AsyncSession,
    user: User,
    project_id: int,
    user_id: int,
    prompt: str,
    asset_id: int,
    *,
    model_id: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    duration_sec: int | None = None,
    image_style_id: str | None = None,
    reference_asset_ids: list[int] | None = None,
) -> int:
    """入队资产生视频任务。已有在途任务时沿用原任务，避免下载重试期间再生成一条。"""
    inflight = (
        await db.execute(
            select(TaskRun.id)
            .where(
                TaskRun.task_type == "asset_video",
                TaskRun.asset_id == asset_id,
                TaskRun.status.in_(("pending", "leased", "running")),
                TaskRun.cancel_requested.is_(False),
            )
            .order_by(TaskRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if inflight:
        logger.info(
            "画布视频仍在生成或下载，沿用任务 task_id=%s asset_id=%s",
            inflight,
            asset_id,
        )
        return int(inflight)
    task_id = await _enqueue_drama_task(
        db,
        user,
        task_type="asset_video",
        project_id=project_id,
        dedupe_suffix=f"{project_id}:asset:{asset_id}",
        asset_id=asset_id,
        payload={
            "project_id": project_id,
            "user_id": user_id,
            "prompt": prompt,
            "asset_id": asset_id,
            "model_id": model_id,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration_sec": duration_sec,
            "image_style_id": image_style_id,
            "reference_asset_ids": reference_asset_ids or [],
        },
        commit=False,
    )
    logger.info("dispatch 资产生视频 → task_id=%s asset_id=%s", task_id, asset_id)
    return task_id


async def run_asset_video_job(
    project_id: int,
    user_id: int,
    prompt: str,
    asset_id: int,
    *,
    model_id: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    duration_sec: int | None = None,
    image_style_id: str | None = None,
    reference_asset_ids: list[int] | None = None,
    provider_task_id: str | None = None,
    on_provider_task: Any | None = None,
) -> dict[str, Any]:
    logger.info(
        "开始资产生视频 project_id=%s asset_id=%s model=%s duration=%s",
        project_id,
        asset_id,
        model_id,
        duration_sec,
    )
    async with AsyncSessionLocal() as db:
        project = (
            await db.execute(
                select(DramaProject)
                .where(DramaProject.id == project_id)
                .options(selectinload(DramaProject.script))
            )
        ).scalar_one_or_none()
        user = await db.get(User, user_id)
        asset = await db.get(DramaAsset, asset_id)
        if not project or not user:
            return {"ok": False, "error": "missing"}
        if not asset or asset.project_id != project_id:
            return {"ok": False, "error": "asset_not_found"}
        try:
            params = dict(asset.params or {})
            params["visualPrompt"] = (prompt or "").strip()
            asset.params = params
            await db.commit()
            await db.refresh(asset)
            asset = await generate_asset_video(
                db,
                user,
                project,
                asset,
                prompt,
                model_id=model_id,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_sec=duration_sec,
                image_style_id=image_style_id,
                reference_asset_ids=reference_asset_ids,
                provider_task_id=provider_task_id,
                on_provider_task=on_provider_task,
            )
            logger.info(
                "资产生视频完成 project_id=%s asset_id=%s url=%s",
                project_id,
                asset.id,
                (asset.url or "")[:80],
            )
            from app.services.tasks.generation_references import public_references
            metadata = (asset.params or {}).get("media_metadata")
            return {"ok": True, "asset_id": asset.id, "kind": "video", "urls": [asset.url] if asset.url else [],
                    "preview_url": asset.cover or None,
                    **({"references": public_references(metadata["references"])}
                       if isinstance(metadata, dict) and "references" in metadata else {})}
        except Exception as exc:  # noqa: BLE001
            from app.services.drama.asset_video import DOWNLOAD_RETRY_MESSAGE
            from app.services.exc_format import format_exception_message
            from app.services.storage import RetryableMediaDownloadError

            # 用量或交付 flush 可能已失败，必须先恢复事务再读取资产和保存状态。
            await db.rollback()
            if isinstance(exc, RetryableMediaDownloadError) and exc.provider_task_id:
                asset = await db.get(DramaAsset, asset_id)
                if asset:
                    await db.refresh(asset)
                    params = dict(asset.params or {})
                    gen = params.get("generation") if isinstance(params.get("generation"), dict) else {}
                    params["generation"] = {
                        **gen,
                        "status": "generating",
                        "message": DOWNLOAD_RETRY_MESSAGE,
                    }
                    if (prompt or "").strip():
                        params["visualPrompt"] = prompt.strip()
                    asset.params = params
                    await db.commit()
                logger.warning(
                    "画布视频下载中断，改为重试下载 project_id=%s asset_id=%s provider_task_id=%s err=%s",
                    project_id,
                    asset_id,
                    exc.provider_task_id,
                    exc,
                )
                return {
                    "ok": True,
                    "retry_download": True,
                    "provider_task_id": exc.provider_task_id,
                    "counts_attempt": bool(exc.counts_attempt),
                    "error": str(exc)[:400],
                }

            err_text = format_exception_message(exc, fallback="生视频失败", limit=500)
            asset = await db.get(DramaAsset, asset_id)
            if asset:
                params = dict(asset.params or {})
                params["generation"] = {"status": "failed", "error": err_text[:400]}
                if (prompt or "").strip():
                    params["visualPrompt"] = prompt.strip()
                asset.params = params
                await db.commit()
            logger.exception(
                "资产生视频失败 project_id=%s asset_id=%s err=%s",
                project_id,
                asset_id,
                err_text,
            )
            return {"ok": False, "error": err_text}


# ---------- 剧本完成后：抽资产 + 入队 LLM 分镜 ----------


def _episode_has_protected_fragments(episode: DramaEpisode) -> bool:
    """已有视频或手改分镜则视为受保护，自动分镜跳过。"""
    for frag in episode.fragments or []:
        if (frag.video or "").strip():
            return True
        params = frag.params if isinstance(frag.params, dict) else {}
        if params.get("user_edited"):
            return True
    return False


async def dispatch_episode_fragment_plan(
    db: AsyncSession,
    user: User,
    episode: DramaEpisode,
    *,
    force: bool = True,
    fallback_rules: bool = True,
    commit: bool = True,
) -> int | None:
    """标记分集分镜中并入队 LLM 分镜任务；已在 generating 且非 force 时跳过。"""
    params = dict(episode.params or {}) if isinstance(episode.params, dict) else {}
    existing = str(params.get("fragment_plan_status") or "")
    if existing == "generating" and not force:
        logger.info("自动分镜跳过：已在进行中 episode_id=%s", episode.id)
        return None

    params["fragment_plan_status"] = "generating"
    params.pop("fragment_plan_error", None)
    params["fragment_plan_mode"] = "llm"
    params["fragment_plan_auto"] = True
    episode.params = params
    await db.flush()

    task_id = await _enqueue_drama_task(
        db,
        user,
        task_type="fragment_plan",
        project_id=int(episode.project_id),
        episode_id=int(episode.id),
        dedupe_suffix=f"episode:{int(episode.id)}:force:{int(bool(force))}:auto",
        payload={
            "project_id": int(episode.project_id),
            "episode_id": int(episode.id),
            "fallback_rules": bool(fallback_rules),
            "force": bool(force),
            "auto": True,
        },
        commit=commit,
    )
    logger.info(
        "自动入队 LLM 分镜 episode_id=%s force=%s task_id=%s",
        episode.id,
        force,
        task_id,
    )
    return task_id


async def seed_assets_for_project(project_id: int) -> dict[str, Any]:
    """从整剧摘要/已有分集正文抽取资产库（角色/场景/道具）。"""
    from app.services.drama.seed import seed_assets_from_script

    logger.info("自动抽取漫剧资产 project_id=%s", project_id)
    async with AsyncSessionLocal() as db:
        project = await db.get(
            DramaProject,
            project_id,
            options=[selectinload(DramaProject.script)],
        )
        if not project or not project.script:
            return {"ok": False, "error": "missing_project_or_script"}
        user = await db.get(User, project.user_id)
        if not user:
            return {"ok": False, "error": "missing_user"}

        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "generating"
        params["assets_seed_generating_at"] = datetime.now(UTC).isoformat()
        params.pop("assets_seed_error", None)
        project.params = params
        await db.commit()

        try:
            project = await db.get(
                DramaProject,
                project_id,
                options=[selectinload(DramaProject.script)],
            )
            if not project:
                return {"ok": False, "error": "project_not_found"}
            seed_result = await seed_assets_from_script(db, project)
            params = dict(project.params or {}) if isinstance(project.params, dict) else {}
            params["assets_seed_status"] = "done"
            params.pop("assets_seed_error", None)
            params.pop("assets_seed_generating_at", None)
            params["assets_seed_created"] = seed_result.created_count
            params["assets_seed_refreshed"] = seed_result.prompts_refreshed
            params["assets_seed_props_updated"] = seed_result.props_updated
            if seed_result.llm_errors:
                params["assets_seed_llm_errors"] = seed_result.llm_errors[:20]
            else:
                params.pop("assets_seed_llm_errors", None)
            project.params = params
            await record_seed_assets_llm_usage(db, user, project.id, seed_result)
            await db.commit()
            logger.info(
                "自动抽资产完成 project_id=%s created=%s",
                project_id,
                seed_result.created_count,
            )
            return {
                "ok": True,
                "created_count": seed_result.created_count,
                "prompts_refreshed": seed_result.prompts_refreshed,
                "props_updated": seed_result.props_updated,
            }
        except Exception as exc:  # noqa: BLE001
            project = await db.get(DramaProject, project_id)
            if project:
                params = dict(project.params or {}) if isinstance(project.params, dict) else {}
                params["assets_seed_status"] = "failed"
                params["assets_seed_error"] = str(exc)[:500]
                params.pop("assets_seed_generating_at", None)
                project.params = params
                await db.commit()
            logger.exception("自动抽资产失败 project_id=%s", project_id)
            return {"ok": False, "error": str(exc)[:500]}


def _episode_body_by_number(script: Any) -> dict[int, str]:
    """剧本 episode_content → {集号: 正文}。"""
    from app.services.drama.seed import _normalize_episode_list

    out: dict[int, str] = {}
    content = getattr(script, "episode_content", None) if script is not None else None
    for item in _normalize_episode_list(content):
        if not isinstance(item, dict):
            continue
        ep_no = int(item.get("episodeNumber") or 0)
        if ep_no < 1:
            continue
        body = str(item.get("body") or item.get("content") or "").strip()
        if body:
            out[ep_no] = body
    return out


def _episode_plan_insufficient(episode: DramaEpisode, body: str) -> bool:
    """已完成但镜数明显不够（如长正文只 1 镜）→ 需要强制重跑 AI/规则分镜。"""
    from app.services.drama.fragment_plan import llm_fragment_coverage_insufficient

    frags = list(episode.fragments or [])
    drafts = [
        {
            "content": f.content or "",
            "duration_sec": int(f.duration_sec or 0),
        }
        for f in frags
    ]
    return llm_fragment_coverage_insufficient(body, drafts)


async def kickoff_fragment_plans(
    project_id: int,
    *,
    episode_numbers: list[int] | None = None,
    reseed_assets: bool = True,
) -> dict[str, Any]:
    """
    分集剧本就绪后：可选补抽场景/道具 → 建分集行 → 入队 LLM 分镜。
    流水线顺序应为：整剧摘要 → 抽资产 → 分集剧本 → 本函数。
    已完成但镜数过少（如仅 1 镜）的集会强制重跑；进行中的不 seed 覆盖。
    """
    from app.services.drama.seed import seed_single_episode_from_script

    logger.info(
        "分集后自动分镜 project_id=%s episode_numbers=%s reseed=%s",
        project_id,
        episode_numbers,
        reseed_assets,
    )
    assets_created = 0
    if reseed_assets:
        assets_result = await seed_assets_for_project(project_id)
        assets_created = int(assets_result.get("created_count") or 0)

    async with AsyncSessionLocal() as db:
        project = await db.get(
            DramaProject,
            project_id,
            options=[selectinload(DramaProject.script)],
        )
        if not project or not project.script:
            return {"ok": False, "error": "missing_project_or_script"}

        user = await db.get(User, project.user_id)
        if not user:
            return {"ok": False, "error": "missing_user"}

        body_by_number = _episode_body_by_number(project.script)
        target_numbers = [int(n) for n in (episode_numbers or []) if int(n) >= 1]
        if not target_numbers:
            target_numbers = sorted(body_by_number.keys())

        episodes_result = await db.execute(
            select(DramaEpisode)
            .where(DramaEpisode.project_id == project_id)
            .options(selectinload(DramaEpisode.fragments))
            .order_by(DramaEpisode.id.asc())
        )
        episodes = list(episodes_result.scalars().all())
        by_number: dict[int, DramaEpisode] = {}
        for ep in episodes:
            ep_params = ep.params if isinstance(ep.params, dict) else {}
            ep_no = int(ep_params.get("episodeNumber") or 0)
            if ep_no >= 1 and ep_no not in by_number:
                by_number[ep_no] = ep

        # 仅给「需要分镜」的集建行；已 generating/合格 completed 绝不规则 seed 覆盖
        need_queue: list[DramaEpisode] = []
        skipped: list[int] = []
        for ep_no in target_numbers:
            body = body_by_number.get(ep_no) or ""
            if not body:
                continue
            episode = by_number.get(ep_no)
            if episode is None:
                try:
                    episode = await seed_single_episode_from_script(db, project, ep_no)
                    by_number[ep_no] = episode
                except ValueError as exc:
                    logger.warning(
                        "自动建分集跳过 project_id=%s ep=%s err=%s",
                        project_id,
                        ep_no,
                        exc,
                    )
                    continue
            if _episode_has_protected_fragments(episode):
                skipped.append(int(episode.id))
                continue
            ep_params = episode.params if isinstance(episode.params, dict) else {}
            plan_st = str(ep_params.get("fragment_plan_status") or "")
            if plan_st == "generating":
                skipped.append(int(episode.id))
                continue
            if plan_st == "completed" and not _episode_plan_insufficient(episode, body):
                skipped.append(int(episode.id))
                continue
            if plan_st == "completed" and _episode_plan_insufficient(episode, body):
                logger.warning(
                    "分镜镜数不足将重跑 project_id=%s episode_id=%s ep=%s frags=%s",
                    project_id,
                    episode.id,
                    ep_no,
                    len(episode.fragments or []),
                )
            need_queue.append(episode)

        # 顺带修复本剧其它「已完成但仅 1 镜」的异常集（不必等全集收尾）
        queued_ids = {int(ep.id) for ep in need_queue}
        for ep_no, episode in by_number.items():
            if project.team_id is not None and episode_numbers and ep_no not in target_numbers:
                continue
            if int(episode.id) in queued_ids:
                continue
            if _episode_has_protected_fragments(episode):
                continue
            ep_params = episode.params if isinstance(episode.params, dict) else {}
            if str(ep_params.get("fragment_plan_status") or "") != "completed":
                continue
            body = body_by_number.get(ep_no) or ""
            if body and _episode_plan_insufficient(episode, body):
                logger.warning(
                    "顺带重跑镜数不足分集 project_id=%s episode_id=%s ep=%s frags=%s",
                    project_id,
                    episode.id,
                    ep_no,
                    len(episode.fragments or []),
                )
                need_queue.append(episode)
                queued_ids.add(int(episode.id))

        queued: list[int] = []
        for episode in need_queue:
            ep_params = dict(episode.params or {}) if isinstance(episode.params, dict) else {}
            ep_params["fragment_plan_status"] = "generating"
            ep_params.pop("fragment_plan_error", None)
            ep_params["fragment_plan_mode"] = "llm"
            ep_params["fragment_plan_auto"] = True
            episode.params = ep_params
        await db.commit()

        for episode in need_queue:
            try:
                task_id = await dispatch_episode_fragment_plan(
                    db,
                    user,
                    episode,
                    force=True,
                    fallback_rules=True,
                    commit=False,
                )
                if task_id:
                    queued.append(int(episode.id))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "自动入队分镜失败 project_id=%s episode_id=%s",
                    project_id,
                    episode.id,
                )
                ep_params = dict(episode.params or {}) if isinstance(episode.params, dict) else {}
                ep_params["fragment_plan_status"] = "failed"
                ep_params["fragment_plan_error"] = "自动分镜入队失败"
                episode.params = ep_params
        await db.commit()
        logger.info(
            "分集后自动分镜完成 project_id=%s assets_created=%s queued=%s skipped=%s",
            project_id,
            assets_created,
            queued,
            skipped,
        )
        return {
            "ok": True,
            "assets_created": assets_created,
            "queued_episode_ids": queued,
            "skipped_episode_ids": skipped,
        }


async def kickoff_assets_and_fragment_plans(
    project_id: int,
    *,
    episode_numbers: list[int] | None = None,
) -> dict[str, Any]:
    """兼容旧名：分集后补抽资产并入队分镜。"""
    return await kickoff_fragment_plans(
        project_id,
        episode_numbers=episode_numbers,
        reseed_assets=True,
    )


# ---------- seed assets from script ----------


async def run_seed_assets_job(
    project_id: int,
    *,
    refresh_prompts: bool = False,
    reextract_props: bool = False,
) -> dict[str, Any]:
    """从剧本抽取/刷新资产（含 LLM 提示词刷新）。"""
    from app.services.drama.seed import seed_assets_from_script

    logger.info(
        "开始抽取漫剧资产 project_id=%s refresh=%s reextract=%s",
        project_id,
        refresh_prompts,
        reextract_props,
    )
    async with AsyncSessionLocal() as db:
        project = await db.get(
            DramaProject,
            project_id,
            options=[selectinload(DramaProject.script)],
        )
        if not project:
            return {"ok": False, "error": "project_not_found"}
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        try:
            result = await seed_assets_from_script(
                db,
                project,
                refresh_prompts=refresh_prompts,
                reextract_props=reextract_props,
            )
            params["assets_seed_status"] = "done"
            params.pop("assets_seed_error", None)
            params.pop("assets_seed_generating_at", None)
            params["assets_seed_created"] = result.created_count
            params["assets_seed_refreshed"] = result.prompts_refreshed
            params["assets_seed_props_updated"] = result.props_updated
            if result.llm_errors:
                params["assets_seed_llm_errors"] = result.llm_errors[:20]
            else:
                params.pop("assets_seed_llm_errors", None)
            project.params = params
            user = await db.get(User, project.user_id)
            if user:
                await record_seed_assets_llm_usage(db, user, project.id, result)
            await db.commit()
            return {
                "ok": True,
                "created_count": result.created_count,
                "prompts_refreshed": result.prompts_refreshed,
                "props_updated": result.props_updated,
                "llm_errors": result.llm_errors,
            }
        except Exception as exc:  # noqa: BLE001
            params["assets_seed_status"] = "failed"
            params["assets_seed_error"] = str(exc)[:500]
            params.pop("assets_seed_generating_at", None)
            project.params = params
            await db.commit()
            logger.exception("抽取漫剧资产失败 project_id=%s", project_id)
            return {"ok": False, "error": str(exc)[:500]}


async def dispatch_seed_assets_job(
    db: AsyncSession,
    user: User,
    project_id: int,
    *,
    refresh_prompts: bool = False,
    reextract_props: bool = False,
) -> int:
    """入队抽取漫剧资产任务。"""
    task_id = await _enqueue_drama_task(
        db,
        user,
        task_type="seed_assets",
        project_id=project_id,
        dedupe_suffix=str(project_id),
        payload={
            "project_id": project_id,
            "refresh_prompts": refresh_prompts,
            "reextract_props": reextract_props,
        },
    )
    logger.info("dispatch 抽取资产 → task_id=%s project_id=%s", task_id, project_id)
    return task_id
