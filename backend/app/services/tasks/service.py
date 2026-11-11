"""CRUD helpers for the unified task platform."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload, selectinload

from app.models import Project, Shot, User
from app.models_drama import DramaAsset, DramaEpisode, DramaEpisodeFragment, DramaProject, DramaScript
from app.models_tasks import TaskEvent, TaskRun, TaskStep, TaskTarget
from app.schemas_tasks import TaskCreateRequest, TaskEventCreate, TaskStepCreate
from app.services.tasks.handlers import get_task_handler
from app.services.tasks.queues import task_queue
from app.services.tasks.execution_policy import is_direct_llm_task, llm_task_condition
from app.services.drama.voice_generation_policy import ensure_voice_generation_task_enabled

logger = logging.getLogger("app.tasks.service")

TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled"}
ACTIVE_TASK_STATUSES = {
    "pending",
    "leased",
    "running",
    "awaiting_poll",
    "awaiting_review",
    "cancel_requested",
}

# Created by each HTTP handler and passed explicitly; never cached across requests.
TaskAccessContext = dict[tuple[int, int], tuple[Any, Any]]


async def _task_team_access(
    db: AsyncSession, team_id: int, user_id: int, *,
    context: TaskAccessContext | None = None, roles: set[str] | None = None,
):
    from fastapi import HTTPException
    from app.services.teams.access import get_team, member_role

    identity = (int(team_id), int(user_id))
    access = context.get(identity) if context is not None else None
    if access is None:
        access = await get_team(db, team_id, user_id)
        if context is not None:
            context[identity] = access
    if roles is not None and member_role(*access) not in roles:
        raise HTTPException(status_code=403, detail="没有团队操作权限")
    return access


def task_detail_options() -> tuple:
    return (
        selectinload(TaskRun.steps),
        selectinload(TaskRun.targets),
        selectinload(TaskRun.events),
    )


# payload 中标记 poller 成片收尾窗口截止时间的键
FINALIZING_UNTIL_KEY = "finalizing_until"


def task_finalizing_window_open(task: TaskRun, *, now: datetime | None = None) -> bool:
    """任务是否处于 poller 的 finalizing 收尾窗口（成片正在下载落盘并记用量）。

    窗口内收到取消不得直接全额退款：成片可能恰好在落盘，先退款会造成
    usage_events 悬空（settled=0）且钱货两失。应收敛取消动作，
    由持有收尾流程的协程完成后按实际用量结算（settle_task 多退少补）。
    """
    payload = getattr(task, "payload", None)
    if not isinstance(payload, dict):
        return False
    raw = payload.get(FINALIZING_UNTIL_KEY)
    if not raw:
        return False
    try:
        until = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return until > (now or datetime.now(UTC))


def clear_finalizing_window(payload: Any) -> dict:
    """返回移除 finalizing 窗口标记后的 payload 副本（无标记时原样拷贝）。"""
    data = dict(payload) if isinstance(payload, dict) else {}
    data.pop(FINALIZING_UNTIL_KEY, None)
    return data


def build_task_event(task_id: int, event: TaskEventCreate) -> TaskEvent:
    return TaskEvent(
        task_id=task_id,
        event_type=event.event_type,
        status=event.status,
        phase=event.phase,
        message=event.message,
        payload=event.payload,
    )


def build_task_step(task_id: int, step: TaskStepCreate) -> TaskStep:
    """Create one persisted task step."""
    return TaskStep(
        task_id=task_id,
        step_key=step.step_key,
        step_type=step.step_type,
        provider_name=step.provider_name,
        input_payload=step.input_payload,
    )


async def create_task(
    db: AsyncSession,
    user: User,
    body: TaskCreateRequest,
    *,
    commit: bool = True,
) -> TaskRun:
    """创建任务；文字 LLM 提交后立即执行，媒体任务留给调度器。"""
    ensure_voice_generation_task_enabled(body.domain, body.task_type)
    if body.payload is not None:
        body.payload = {key: value for key, value in body.payload.items() if not key.startswith("_team_")}
    if body.drama_project_id is not None:
        from app.services.tasks.team_scope import prepare_background_task
        user = await prepare_background_task(db, int(body.drama_project_id), user)
    await _validate_task_scope(db, user, body)
    handler = get_task_handler(body.domain, body.task_type)
    if handler is None:
        raise ValueError("当前任务类型尚未接入任务平台")
    from app.services.billing.settlement import ensure_balance_for_task

    balance_probe = TaskRun(
        domain=body.domain,
        task_type=body.task_type,
        requested_by=user.id,
        team_id=body.team_id,
        payload=body.payload,
        project_id=body.project_id,
        drama_project_id=body.drama_project_id,
        episode_id=body.episode_id,
        fragment_id=body.fragment_id,
        asset_id=body.asset_id,
        shot_id=body.shot_id,
    )
    from app.services.media_models.planning import prepare_task_media
    await prepare_task_media(db, balance_probe)
    if body.domain == "studio" and body.drama_project_id is not None:
        balance_probe.billing_payer_user_id = user.id
    estimate_fen = await ensure_balance_for_task(db, user, balance_probe)
    planned_steps = handler.plan_steps(body)
    first_step = planned_steps[0] if planned_steps else None
    now = datetime.now(UTC)
    next_action = None if body.defer_activation else (body.scheduled_at or now)
    task = TaskRun(
        domain=body.domain,
        task_type=body.task_type,
        queue_type=task_queue(body.task_type, body.payload),
        status="pending",
        priority=body.priority,
        requested_by=user.id,
        client_request_id=body.client_request_id,
        dedupe_key=body.dedupe_key,
        batch_key=body.batch_key,
        provider_task_id=body.provider_task_id,
        cancelable=body.cancelable,
        current_step_key=first_step.step_key if first_step else None,
        current_step_status="pending" if first_step else None,
        scheduled_at=body.scheduled_at or now,
        next_action_at=next_action,
        payload=body.payload,
        result_payload=body.result_payload,
        project_id=body.project_id,
        drama_project_id=body.drama_project_id,
        script_id=body.script_id,
        episode_id=body.episode_id,
        fragment_id=body.fragment_id,
        asset_id=body.asset_id,
        shot_id=body.shot_id,
        billing_estimate_fen=int(estimate_fen or 0),
        team_id=body.team_id,
        billing_enabled_snapshot=balance_probe.billing_enabled_snapshot,
        billing_period=balance_probe.billing_period,
        billing_payer_user_id=balance_probe.billing_payer_user_id,
        billing_status=balance_probe.billing_status or "none",
        billing_snapshot=balance_probe.billing_snapshot,
    )
    db.add(task)
    await db.flush()
    schedule = body.scheduled_at
    if schedule is not None and schedule.tzinfo is None:
        schedule = schedule.replace(tzinfo=UTC)
    direct = is_direct_llm_task(body.domain, body.task_type, body.payload)
    if direct and not body.defer_activation and (schedule is None or schedule <= now):
        task.status = "running"
        task.started_at = now
        task.next_action_at = None
        task.lease_token = uuid.uuid4().hex
        task.lease_until = now + timedelta(minutes=10)
    if task.team_id is not None:
        from app.services.teams.edit_locks import claim_task_locks
        await claim_task_locks(db, task, user.id)
    for step in planned_steps:
        db.add(build_task_step(task.id, step))
    for item in body.targets:
        db.add(
            TaskTarget(
                task_id=task.id,
                target_type=item.target_type,
                target_id=item.target_id,
                sort_order=item.sort_order,
                metadata_json=item.metadata_json,
            )
        )
    db.add(
        build_task_event(
            task.id,
            TaskEventCreate(
                event_type="task.created",
                status=task.status,
                phase=task.current_step_key,
                message=f"创建任务 {task.task_type}",
                payload={"domain": task.domain, "execution_mode": "direct" if direct else "queued"},
            ),
        )
    )
    if direct and task.status == "running":
        from app.services.tasks.direct import defer_until_commit
        defer_until_commit(db, task.id, task.lease_token)
    if not commit:
        return task
    await db.commit()
    return await get_task_for_user(db, user, task.id)


# 串行 batch 中上一镜完成后激活下一镜任务。
async def activate_next_sequential_task(db: AsyncSession, batch_key: str | None, completed_index: int) -> bool:
    if not batch_key:
        return False
    from app.config import get_settings
    from app.services.drama.access import count_user_inflight_fragment_video_tasks

    next_index = int(completed_index) + 1
    stmt = (
        select(TaskRun)
        .where(
            TaskRun.batch_key == batch_key,
            TaskRun.status == "pending",
            TaskRun.next_action_at.is_(None),
            TaskRun.cancel_requested.is_(False),
        )
        .order_by(TaskRun.id.asc())
        .with_for_update(skip_locked=True)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    for task in rows:
        if task.next_action_at is not None or task.cancel_requested:
            continue
        payload = task.payload if isinstance(task.payload, dict) else {}
        if int(payload.get("batch_index", -1)) != next_index:
            continue
        limit = max(1, int(get_settings().drama_user_video_job_limit or 12))
        inflight = await count_user_inflight_fragment_video_tasks(db, int(task.requested_by))
        if inflight >= limit:
            return False
        task.next_action_at = datetime.now(UTC)
        await append_task_event(
            db,
            task.id,
            event_type="task.activated",
            status=task.status,
            phase=task.current_step_key,
            message=f"前置分镜已完成，激活 batch 第 {next_index + 1} 镜",
        )
        await db.commit()
        return True
    return False


# 串行 batch 中某一镜失败后，终止后续仍 pending 的兄弟任务。
async def fail_remaining_sequential_batch(
    db: AsyncSession,
    batch_key: str | None,
    failed_index: int,
    reason: str,
) -> int:
    if not batch_key:
        return 0
    from app.models_drama import DramaEpisodeFragment

    stmt = select(TaskRun).where(
        TaskRun.batch_key == batch_key,
        TaskRun.status == "pending",
    )
    rows = list((await db.execute(stmt)).scalars().all())
    changed = 0
    now = datetime.now(UTC)
    for task in rows:
        payload = task.payload if isinstance(task.payload, dict) else {}
        if int(payload.get("batch_index", -1)) <= int(failed_index):
            continue
        task.status = "cancelled"
        task.error_code = "sequential_blocked"
        task.error_message = reason[:500]
        task.finished_at = now
        task.next_action_at = None
        if task.fragment_id:
            frag = await db.get(DramaEpisodeFragment, int(task.fragment_id))
            if frag:
                params = dict(frag.params or {})
                params["generation"] = {
                    "status": "failed",
                    "error": reason[:500],
                }
                frag.params = params
        await append_task_event(
            db,
            task.id,
            event_type="task.cancelled",
            status=task.status,
            phase=task.current_step_key,
            message=reason[:500],
        )
        if str(task.billing_status or "") in {"frozen", "reserved"}:
            from app.services.billing.settlement import settle_task

            try:
                await settle_task(db, int(task.id))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "settle_task after sequential cancel failed task_id=%s",
                    task.id,
                )
        changed += 1
    if changed:
        await db.commit()
    return changed


# 进行中的分镜生成状态（重新生成会保留旧 video，不能当「已完成」误取消）
_ACTIVE_FRAGMENT_VIDEO_GEN = frozenset({"queued", "running", "generating"})
# 分镜删除后需立即作废的在途态（含 awaiting_poll，避免上游成功后报「上下文丢失」）
_STALE_FRAGMENT_VIDEO_STATUSES = frozenset(
    {"pending", "leased", "running", "awaiting_poll", "cancel_requested"}
)
_STALE_FRAGMENT_REASON = "分镜已变更，请重新生成"


# 从任务列与 payload 解析关联分镜 id。
def task_fragment_ids(task: TaskRun) -> list[int]:
    ids: list[int] = []
    if task.fragment_id:
        try:
            ids.append(int(task.fragment_id))
        except (TypeError, ValueError):
            pass
    payload = task.payload if isinstance(task.payload, dict) else {}
    raw_ids = payload.get("fragment_ids") or []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            try:
                fid = int(item)
            except (TypeError, ValueError):
                continue
            if fid > 0 and fid not in ids:
                ids.append(fid)
    return ids


# 判断分镜视频任务是否应作废；返回取消原因，None 表示保留。
def stale_pending_fragment_video_reason(frags: list[Any], task: Any | None = None) -> str | None:
    """分镜已删 → 作废；全有成片且无进行中 generation、且非替换成片 → 跳过重复；否则保留。"""
    from app.services.drama.generation import fragment_generation_status

    if not frags:
        return _STALE_FRAGMENT_REASON
    payload = getattr(task, "payload", None) if task is not None else None
    # 重新生成会保留旧 video，调度器不能当成重复任务取消
    if isinstance(payload, dict) and payload.get("replace_existing_video"):
        return None
    if not all((getattr(frag, "video", None) or "").strip() for frag in frags):
        return None
    for frag in frags:
        status = str(fragment_generation_status(frag).get("status") or "").lower()
        if status in _ACTIVE_FRAGMENT_VIDEO_GEN:
            return None
    return "分镜已生成完成，跳过重复任务"


# 将任务标记为因分镜变更而取消（立即终态，不走 cancel_requested）。
async def _mark_task_cancelled_stale(db: AsyncSession, task: TaskRun, reason: str, now: datetime) -> None:
    task.status = "cancelled"
    task.cancel_requested = True
    task.error_code = "stale_fragment_ref"
    task.error_message = reason[:500]
    task.finished_at = now
    task.next_action_at = None
    task.lease_token = None
    task.lease_until = None
    await append_task_event(
        db,
        task.id,
        event_type="task.cancelled",
        status=task.status,
        phase=task.current_step_key,
        message=reason[:500],
    )
    # 作废终态必须结算预扣，否则 frozen 余额悬挂（如 #3328）
    if str(task.billing_status or "") in {"frozen", "reserved"}:
        from app.services.billing.settlement import settle_task

        try:
            await settle_task(db, int(task.id))
        except Exception:  # noqa: BLE001
            logger.exception("settle_task after stale cancel failed task_id=%s", task.id)


# 分镜删除/重切时作废仍引用旧 id 的在途 fragment_video（含轮询中），勿重试旧任务。
async def cancel_fragment_video_tasks_for_fragments(
    db: AsyncSession,
    fragment_ids: list[int],
    *,
    reason: str = _STALE_FRAGMENT_REASON,
) -> int:
    ids = [int(x) for x in fragment_ids if int(x) > 0]
    if not ids:
        return 0
    id_set = set(ids)
    stmt = select(TaskRun).where(
        TaskRun.domain == "drama",
        TaskRun.task_type == "fragment_video",
        TaskRun.status.in_(tuple(_STALE_FRAGMENT_VIDEO_STATUSES)),
    )
    rows = list((await db.execute(stmt)).scalars().all())
    changed = 0
    now = datetime.now(UTC)
    for task in rows:
        refs = task_fragment_ids(task)
        if not refs or not id_set.intersection(refs):
            continue
        await _mark_task_cancelled_stale(db, task, reason, now)
        changed += 1
    if changed:
        logger.info(
            "cancelled stale fragment_video tasks count=%s fragment_ids=%s",
            changed,
            ids[:20],
        )
    return changed


# 取消 payload 中分镜已删除或已有成片（且非重新生成）的在途任务，避免假排队与上下文丢失。
# 同时释放「finalizing 认领窗口异常过长」的卡死任务（历史 6h TTL / poller 取消后未释放）。
async def reconcile_stale_pending_tasks(db: AsyncSession) -> int:
    # 认领剩余 >12 分钟视为异常（正常收尾 TTL 为 10 分钟）
    finalize_stale_remaining = timedelta(minutes=12)

    stmt = select(TaskRun).where(
        TaskRun.status.in_(tuple(_STALE_FRAGMENT_VIDEO_STATUSES)),
        TaskRun.domain == "drama",
        TaskRun.task_type == "fragment_video",
    )
    rows = list((await db.execute(stmt)).scalars().all())
    changed = 0
    now = datetime.now(UTC)
    for task in rows:
        # finalizing 认领剩余过长：释放回 polling，让 Selector 立刻再查上游/重试落盘
        if (
            task.status == "awaiting_poll"
            and (task.current_step_status or "") == "finalizing"
            and task.next_action_at is not None
        ):
            na = task.next_action_at
            if na.tzinfo is None:
                na = na.replace(tzinfo=UTC)
            if na - now > finalize_stale_remaining:
                task.current_step_status = "polling"
                task.next_action_at = now
                await append_task_event(
                    db,
                    task.id,
                    event_type="task.poll_resumed",
                    status=task.status,
                    phase=task.current_step_key,
                    message="释放异常过长的收尾认领，恢复上游轮询",
                )
                changed += 1
                continue

        frag_ids = task_fragment_ids(task)
        if not frag_ids:
            # fragment_id 已被 detach、payload 也无 id → 无法回写，直接作废
            if task.status in {"awaiting_poll", "running", "leased"}:
                await _mark_task_cancelled_stale(db, task, _STALE_FRAGMENT_REASON, now)
                changed += 1
            continue

        frags: list[DramaEpisodeFragment] = []
        for frag_id in frag_ids:
            frag = await db.get(DramaEpisodeFragment, frag_id)
            if frag is not None:
                frags.append(frag)

        reason = stale_pending_fragment_video_reason(frags, task)
        if not reason:
            continue

        await _mark_task_cancelled_stale(db, task, reason, now)
        changed += 1

    if changed:
        await db.commit()
        logger.info("reconciled stale fragment_video task runs count=%s", changed)
    return changed


# 连续点各镜「生成」会各建一个 sequential batch，且 batch_index 都是 0。
# 这种分镜视频不能按 batch 首镜激活，必须按分集镜序走 rebalance。
def sequential_fragment_video_needs_episode_rebalance(
    task_type: str | None,
    payload: dict | None,
) -> bool:
    if str(task_type or "") != "fragment_video":
        return False
    data = payload if isinstance(payload, dict) else {}
    return bool(data.get("sequential"))


# 开启衔接时，每集只允许镜序最前的未完成任务占槽（在跑优先于排队）。
def pick_sequential_episode_head(
    ep_tasks: list[TaskRun],
    sort_by_frag: dict[int, int],
) -> TaskRun | None:
    ordered = sorted(
        [task for task in ep_tasks if task.fragment_id is not None],
        key=lambda task: (
            sort_by_frag.get(int(task.fragment_id or 0), 10**9),
            int(getattr(task, "id", 0) or 0),
        ),
    )
    for task in ordered:
        if task.status in {"leased", "running", "awaiting_poll"}:
            return task
        if task.status == "pending":
            return task
    return None


# 上一镜没有成片或尾帧时，后镜不能当队首（失败任务已离开队列）。
def sequential_task_blocked_by_previous_fragment(
    task: TaskRun,
    episode_frags: list[DramaEpisodeFragment],
) -> bool:
    if task.fragment_id is None or not episode_frags:
        return False
    ordered = sorted(
        [frag for frag in episode_frags if frag.id is not None],
        key=lambda frag: (int(frag.sort_order or 0), int(frag.id or 0)),
    )
    idx = next(
        (i for i, frag in enumerate(ordered) if int(frag.id) == int(task.fragment_id)),
        None,
    )
    if idx is None or idx <= 0:
        return False
    prev = ordered[idx - 1]
    if (prev.video or "").strip():
        return False
    from app.services.drama.generation import read_fragment_last_frame_url

    return not bool(read_fragment_last_frame_url(prev))


# 从任务列或 payload 取出漫剧项目 id，供衔接重排按项目收口。
def _sequential_fragment_video_project_id(task: TaskRun, payload: dict) -> int | None:
    raw = getattr(task, "drama_project_id", None)
    if raw is None:
        raw = payload.get("project_id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# 修复串行 batch 中 next_action_at 为空导致永远排队的任务；并行 batch 按用户并发上限逐步激活。
# 分镜视频开启尾帧衔接时，不把各点击的 batch_index=0 当成独立首镜。
async def reconcile_sequential_batches(db: AsyncSession) -> int:
    from app.config import get_settings
    from app.services.drama.access import count_user_inflight_fragment_video_tasks

    stmt = (
        select(TaskRun.batch_key)
        .where(
            TaskRun.batch_key.is_not(None),
            TaskRun.status == "pending",
            TaskRun.next_action_at.is_(None),
        )
        .distinct()
    )
    batch_keys = [str(key) for key in (await db.execute(stmt)).scalars().all() if key]
    changed = 0
    limit = max(1, int(get_settings().drama_user_video_job_limit or 12))
    # 同一 tick 内跨 batch 共享用户空位，避免重复超发
    user_slots: dict[int, int] = {}
    # 开启衔接的分镜视频：按项目收集后统一重排，避免连续点击并发开跑
    frag_video_projects: dict[int, int] = {}
    for batch_key in batch_keys:
        tasks = list(
            (
                await db.execute(
                    select(TaskRun).where(TaskRun.batch_key == batch_key).order_by(TaskRun.id.asc())
                )
            ).scalars().all()
        )
        if not tasks:
            continue
        sample = tasks[0].payload if isinstance(tasks[0].payload, dict) else {}
        if not sample.get("sequential"):
            # 并行：按用户 Seedance 在途上限激活排队中的 pending，避免超限提交后失败
            user_id = int(tasks[0].requested_by)
            if user_id not in user_slots:
                inflight = await count_user_inflight_fragment_video_tasks(db, user_id)
                user_slots[user_id] = max(0, limit - inflight)
            slots = user_slots[user_id]
            if slots <= 0:
                continue
            deferred = [
                task
                for task in tasks
                if task.status == "pending" and task.next_action_at is None
            ]
            activated = 0
            for task in deferred[:slots]:
                task.next_action_at = datetime.now(UTC)
                await append_task_event(
                    db,
                    task.id,
                    event_type="task.activated",
                    status=task.status,
                    phase=task.current_step_key,
                    message=f"并发空位可用，激活排队任务（上限 {limit}）",
                )
                changed += 1
                activated += 1
            user_slots[user_id] = max(0, slots - activated)
            continue

        by_index: dict[int, TaskRun] = {}
        for task in tasks:
            payload = task.payload if isinstance(task.payload, dict) else {}
            by_index[int(payload.get("batch_index", -1))] = task

        uses_episode_rebalance = sequential_fragment_video_needs_episode_rebalance(
            tasks[0].task_type,
            sample,
        )
        pid = _sequential_fragment_video_project_id(tasks[0], sample)
        if uses_episode_rebalance and pid:
            frag_video_projects[pid] = int(tasks[0].requested_by)
        elif uses_episode_rebalance:
            logger.warning(
                "sequential fragment_video missing project_id batch_key=%s task_id=%s",
                batch_key,
                tasks[0].id,
            )

        failed_indices = [
            int((t.payload or {}).get("batch_index", -1))
            for t in tasks
            if t.status == "failed" and isinstance(t.payload, dict)
        ]
        if failed_indices:
            changed += await fail_remaining_sequential_batch(
                db,
                batch_key,
                min(failed_indices),
                "上一镜失败，串行批次已终止",
            )
            continue

        if uses_episode_rebalance:
            # 分镜仅按真实镜序及前置尾帧重排，不能同时由 batch 分支重复点亮。
            continue

        succeeded_indices = [
            int((t.payload or {}).get("batch_index", -1))
            for t in tasks
            if t.status == "succeeded" and isinstance(t.payload, dict)
        ]
        if succeeded_indices:
            changed += int(await activate_next_sequential_task(db, batch_key, max(succeeded_indices)))
            continue

        first = by_index.get(0)
        if first and first.status == "pending" and first.next_action_at is None:
            user_id = int(first.requested_by)
            if user_id not in user_slots:
                inflight = await count_user_inflight_fragment_video_tasks(db, user_id)
                user_slots[user_id] = max(0, limit - inflight)
            if user_slots[user_id] <= 0:
                continue
            first.next_action_at = datetime.now(UTC)
            user_slots[user_id] -= 1
            await append_task_event(
                db,
                first.id,
                event_type="task.activated",
                status=first.status,
                phase=first.current_step_key,
                message="串行批次首镜激活",
            )
            changed += 1
    for pid, uid in frag_video_projects.items():
        stats = await rebalance_project_fragment_video_queue(
            db,
            pid,
            sequential=True,
            user_id=uid,
        )
        changed += int(stats.get("activated") or 0) + int(stats.get("deferred") or 0)
    if changed:
        await db.commit()
    return changed


# 镜间衔接开关切换后：只重排仍 pending 的分镜视频任务（已在跑的不动）。
async def rebalance_project_fragment_video_queue(
    db: AsyncSession,
    project_id: int,
    *,
    sequential: bool,
    user_id: int | None = None,
) -> dict[str, int]:
    from app.config import get_settings
    from app.services.drama.access import count_user_inflight_fragment_video_tasks

    stmt = select(TaskRun).where(
        TaskRun.drama_project_id == int(project_id),
        TaskRun.domain == "drama",
        TaskRun.task_type == "fragment_video",
        TaskRun.status.in_(("pending", "leased", "running", "awaiting_poll")),
    )
    tasks = list((await db.execute(stmt)).scalars().all())
    if not tasks:
        return {"pending": 0, "activated": 0, "deferred": 0}

    pending = [task for task in tasks if task.status == "pending" and not task.cancel_requested]
    active = [
        task
        for task in tasks
        if task.status in {"leased", "running", "awaiting_poll"} and not task.cancel_requested
    ]

    # 先统一改写 pending 的串行标记，供后续调度器按新模式激活
    for task in pending:
        payload = dict(task.payload or {}) if isinstance(task.payload, dict) else {}
        if bool(payload.get("sequential")) == bool(sequential):
            continue
        payload["sequential"] = bool(sequential)
        task.payload = payload

    activated = 0
    deferred = 0
    now = datetime.now(UTC)
    limit = max(1, int(get_settings().drama_user_video_job_limit or 12))
    owner_id = int(user_id or (pending[0].requested_by if pending else tasks[0].requested_by))

    if not sequential:
        # 关闭衔接：尽量把仍排队的 pending 激活到并发空位
        inflight = await count_user_inflight_fragment_video_tasks(db, owner_id)
        slots = max(0, limit - inflight)
        deferred_pending = [task for task in pending if task.next_action_at is None]
        for task in deferred_pending:
            if slots <= 0:
                deferred += 1
                continue
            task.next_action_at = now
            slots -= 1
            activated += 1
            await append_task_event(
                db,
                task.id,
                event_type="task.activated",
                status=task.status,
                phase=task.current_step_key,
                message="已关闭镜间衔接，恢复并发生成",
            )
        if activated or deferred or pending:
            await db.commit()
        return {"pending": len(pending), "activated": activated, "deferred": deferred}

    # 开启衔接：按分集镜序，只允许“当前最前未完成镜”占槽；其余 pending 收回激活
    frag_ids = {
        int(task.fragment_id)
        for task in pending + active
        if task.fragment_id is not None
    }
    sort_by_frag: dict[int, int] = {}
    episode_by_frag: dict[int, int] = {}
    if frag_ids:
        frag_rows = list(
            (
                await db.execute(
                    select(DramaEpisodeFragment).where(DramaEpisodeFragment.id.in_(sorted(frag_ids)))
                )
            ).scalars().all()
        )
        for frag in frag_rows:
            sort_by_frag[int(frag.id)] = int(frag.sort_order or 0)
            episode_by_frag[int(frag.id)] = int(frag.episode_id)

    by_episode: dict[int, list[TaskRun]] = {}
    for task in pending + active:
        if task.fragment_id is None:
            continue
        ep_id = episode_by_frag.get(int(task.fragment_id)) or int(task.episode_id or 0)
        by_episode.setdefault(ep_id, []).append(task)

    # 补齐同集全部分镜：上一镜失败后任务已不在队列，仍需挡住后镜
    siblings_by_ep: dict[int, list[DramaEpisodeFragment]] = {}
    episode_ids = [eid for eid in by_episode.keys() if eid]
    if episode_ids:
        sibling_rows = list(
            (
                await db.execute(
                    select(DramaEpisodeFragment).where(
                        DramaEpisodeFragment.episode_id.in_(sorted(episode_ids))
                    )
                )
            ).scalars().all()
        )
        for frag in sibling_rows:
            siblings_by_ep.setdefault(int(frag.episode_id), []).append(frag)
            sort_by_frag[int(frag.id)] = int(frag.sort_order or 0)

    heads_to_activate: list[TaskRun] = []
    for ep_id, ep_tasks in by_episode.items():
        head = pick_sequential_episode_head(ep_tasks, sort_by_frag)
        if (
            head is not None
            and head.status == "pending"
            and sequential_task_blocked_by_previous_fragment(
                head, siblings_by_ep.get(ep_id, [])
            )
        ):
            head = None
        for task in ep_tasks:
            if task.status != "pending":
                continue
            is_head = head is not None and int(task.id) == int(head.id) and head.status == "pending"
            if is_head:
                heads_to_activate.append(task)
                continue
            if task.next_action_at is not None:
                task.next_action_at = None
                deferred += 1
                await append_task_event(
                    db,
                    task.id,
                    event_type="task.deferred",
                    status=task.status,
                    phase=task.current_step_key,
                    message="已开启镜间衔接，后镜改回排队等待上一镜",
                )
            else:
                deferred += 1

    # 先 flush 收回后镜空位，再按并发上限激活各集当前首镜
    await db.flush()
    inflight = await count_user_inflight_fragment_video_tasks(db, owner_id)
    slots = max(0, limit - inflight)
    for task in heads_to_activate:
        if task.next_action_at is not None:
            continue
        if slots <= 0:
            deferred += 1
            continue
        task.next_action_at = now
        slots -= 1
        activated += 1
        await append_task_event(
            db,
            task.id,
            event_type="task.activated",
            status=task.status,
            phase=task.current_step_key,
            message="已开启镜间衔接，按镜序激活当前首镜",
        )

    await db.commit()
    logger.info(
        "rebalanced fragment_video queue project_id=%s sequential=%s pending=%s activated=%s deferred=%s",
        project_id,
        sequential,
        len(pending),
        activated,
        deferred,
    )
    return {"pending": len(pending), "activated": activated, "deferred": deferred}


# 统计用户当前占用 Worker 槽位的任务数（NIO：awaiting_poll 注册项不占槽）。
async def count_user_active_runtime_tasks(db: AsyncSession, user_id: int, *, queue_type: str | None = None) -> int:
    stmt = select(func.count()).select_from(TaskRun).where(
        TaskRun.requested_by == int(user_id),
        ~llm_task_condition(TaskRun),
        TaskRun.status.in_(("leased", "running", "awaiting_poll") if queue_type == "video" else ("leased", "running")),
    )
    if queue_type:
        stmt = stmt.where(TaskRun.queue_type == queue_type)
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _validate_task_scope(db: AsyncSession, user: User, body: TaskCreateRequest) -> None:
    """Resolve every reference to its persisted project; never trust client team IDs."""
    if body.domain == 'studio' and body.drama_project_id is not None:
        # Studio's grant is limited to this canvas and cannot create drama tasks.
        from app.printfilm_studio.sharing import project_for
        if body.task_type not in {'tool_image', 'tool_video', 'tool_audio'} or any(
            value is not None for value in (body.project_id, body.shot_id, body.script_id, body.episode_id, body.fragment_id, body.asset_id)
        ):
            raise ValueError('画布权限不允许操作其他项目内容')
        if body.team_id is not None:
            raise ValueError('画布生成使用发起人的个人余额')
        await project_for(db, body.drama_project_id, user, lock=True)
        for asset_id in (body.payload or {}).get('reference_asset_ids') or []:
            asset = await db.get(DramaAsset, int(asset_id))
            if not asset or asset.project_id != body.drama_project_id:
                raise ValueError('引用资产不属于当前画布')
        body.team_id = None
        return
    if body.project_id is not None:
        project = await db.get(Project, body.project_id)
        if not project or int(project.user_id) != int(user.id):
            raise ValueError("科普项目不存在或无权限")
    if body.shot_id is not None:
        shot = await db.get(Shot, body.shot_id)
        project = await db.get(Project, int(shot.project_id)) if shot else None
        if not project or int(project.user_id) != int(user.id):
            raise ValueError("镜头不存在或无权限")
        if body.project_id is not None and int(shot.project_id) != int(body.project_id):
            raise ValueError("镜头与项目不匹配")
    project_ids: set[int] = set()
    if body.drama_project_id is not None:
        project_ids.add(int(body.drama_project_id))
    for model, ident, label in ((DramaScript, body.script_id, "剧本"), (DramaEpisode, body.episode_id, "分集"), (DramaAsset, body.asset_id, "资产")):
        if ident is None:
            continue
        entity = await db.get(model, ident)
        if entity is None:
            raise ValueError(f"{label}不存在")
        project_ids.add(int(entity.project_id))
    if body.fragment_id is not None:
        fragment = await db.get(DramaEpisodeFragment, body.fragment_id)
        episode = await db.get(DramaEpisode, int(fragment.episode_id)) if fragment else None
        if episode is None:
            raise ValueError("分镜不存在")
        if body.episode_id is not None and int(episode.id) != int(body.episode_id):
            raise ValueError("分镜与分集不匹配")
        project_ids.add(int(episode.project_id))
        body.episode_id = int(episode.id)
    payload = body.payload if isinstance(body.payload, dict) else {}
    for raw_id in payload.get("fragment_ids") or []:
        fragment = await db.get(DramaEpisodeFragment, int(raw_id))
        episode = await db.get(DramaEpisode, int(fragment.episode_id)) if fragment else None
        if episode is None or (body.episode_id is not None and episode.id != body.episode_id):
            raise ValueError("分镜与分集不匹配")
        project_ids.add(int(episode.project_id))
    for raw_id in payload.get("reference_asset_ids") or []:
        asset = await db.get(DramaAsset, int(raw_id))
        if asset is None:
            raise ValueError("引用资产不存在")
        project_ids.add(int(asset.project_id))
    if len(project_ids) > 1:
        raise ValueError("任务资源与漫剧项目不匹配")
    if body.team_id is not None:
        raise ValueError("独立团队已停用，生成费用使用发起人的个人余额")
    actual_team_id = None
    if project_ids:
        pid = project_ids.pop()
        project = await db.get(DramaProject, pid)
        if project is None:
            raise ValueError("漫剧项目不存在或无权限")
        actual_team_id = project.team_id
        if int(project.user_id) != int(user.id):
            raise ValueError("漫剧项目不存在或无权限")
        # Hold project ownership through task insertion. A concurrent personal transfer
        # must either observe this active task or finish before our scope is accepted.
        # 只读取最新归属字段，避免刷新 ORM 对象使调用方已加载的剧本关系失效。
        locked_project = (await db.execute(
            select(DramaProject.id, DramaProject.user_id, DramaProject.team_id)
            .where(DramaProject.id == pid)
            .with_for_update()
        )).one_or_none()
        if locked_project is None or locked_project.team_id != actual_team_id:
            raise ValueError("项目归属已变化，请刷新页面后重试")
        if int(locked_project.user_id) != int(user.id):
            raise ValueError("漫剧项目不存在或无权限")
        body.drama_project_id = pid
    if body.team_id is not None and body.team_id != actual_team_id:
        raise ValueError("任务与团队不匹配")
    if actual_team_id is not None and body.domain != "drama":
        raise ValueError("当前功能不支持团队空间")
    body.team_id = None


async def get_task_for_user(
    db: AsyncSession, user: User, task_id: int, *,
    access_context: TaskAccessContext | None = None,
) -> TaskRun:
    stmt = (
        select(TaskRun)
        .options(*task_detail_options())
        .where(TaskRun.id == task_id)
    )
    task = (await db.execute(stmt)).scalar_one_or_none()
    if not task:
        raise LookupError("任务不存在")
    if task.team_id is not None:
        await _task_team_access(db, int(task.team_id), int(user.id), context=access_context)
    elif int(task.requested_by) != int(user.id):
        raise LookupError("任务不存在")
    return task


async def list_tasks_for_user(
    db: AsyncSession,
    user: User,
    *,
    page: int,
    page_size: int,
    domain: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    queue_type: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    team_id: int | None = None,
    access_context: TaskAccessContext | None = None,
) -> tuple[list[TaskRun], int]:
    if team_id is not None:
        await _task_team_access(db, team_id, int(user.id), context=access_context)
        filters = [TaskRun.team_id == team_id]
    else:
        filters = [TaskRun.requested_by == user.id, TaskRun.team_id.is_(None)]
    if domain:
        filters.append(TaskRun.domain == domain)
    if status:
        filters.append(TaskRun.status == status)
    if task_type:
        filters.append(TaskRun.task_type == task_type)
    if queue_type:
        filters.append(TaskRun.queue_type == queue_type)
    if project_id:
        filters.append(TaskRun.project_id == project_id)
    if drama_project_id:
        filters.append(TaskRun.drama_project_id == drama_project_id)

    base_stmt: Select = select(TaskRun).where(*filters)
    count_stmt = select(func.count()).select_from(TaskRun).where(*filters)
    if target_type and target_id:
        base_stmt = base_stmt.join(TaskTarget).where(
            TaskTarget.target_type == target_type,
            TaskTarget.target_id == target_id,
        )
        count_stmt = count_stmt.join(TaskTarget).where(
            TaskTarget.target_type == target_type,
            TaskTarget.target_id == target_id,
        )

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    stmt = (
        base_stmt.options(*task_detail_options())
        .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(stmt)).scalars().unique().all())
    return rows, total


async def count_active_tasks_for_user(
    db: AsyncSession,
    user: User,
    *,
    domain: str | None = None,
    task_type: str | None = None,
) -> int:
    """Count active task runs for one user."""
    filters = [TaskRun.requested_by == user.id, TaskRun.status.in_(tuple(ACTIVE_TASK_STATUSES))]
    if domain:
        filters.append(TaskRun.domain == domain)
    if task_type:
        filters.append(TaskRun.task_type == task_type)
    stmt = select(func.count()).select_from(TaskRun).where(*filters)
    return int((await db.execute(stmt)).scalar_one() or 0)


async def cancel_task_for_user(
    db: AsyncSession, user: User, task_id: int, *,
    access_context: TaskAccessContext | None = None,
) -> TaskRun:
    context = access_context if access_context is not None else {}
    task = await get_task_for_user(db, user, task_id, access_context=context)
    if task.team_id is not None and int(task.requested_by) != int(user.id):
        await _task_team_access(db, int(task.team_id), int(user.id), context=context, roles={"owner", "admin"})
    if not task.cancelable:
        raise ValueError("任务不支持取消")
    if task.status in TERMINAL_TASK_STATUSES:
        raise ValueError("任务已结束，不能取消")
    task.cancel_requested = True
    task.status = "cancel_requested"
    task.next_action_at = datetime.now(UTC)
    db.add(
        build_task_event(
            task.id,
            TaskEventCreate(
                event_type="task.cancel_requested",
                status=task.status,
                phase=task.current_step_key,
                message="已提交取消请求",
            ),
        )
    )
    await db.commit()
    if is_direct_llm_task(task.domain, task.task_type, task.payload):
        from app.services.tasks.scheduler import cancel_running_task
        await cancel_running_task(task.id)
    return await get_task_for_user(db, user, task.id, access_context=context)


# 共用用户隔离、活动态筛选和详情加载，保证单项目与列表查询语义一致。
def _active_owner_tasks_statement(user_id: int, *scope_filters, include_teams: bool = False) -> Select:
    ownership = (TaskRun.requested_by == user_id) & TaskRun.team_id.is_(None)
    if include_teams:
        from app.models_teams import TeamMember
        memberships = select(TeamMember.team_id).where(TeamMember.user_id == user_id, TeamMember.active.is_(True))
        ownership = or_(ownership, TaskRun.team_id.in_(memberships))
    return (
        select(TaskRun)
        .options(*task_detail_options())
        .where(
            ownership,
            TaskRun.status.in_(tuple(ACTIVE_TASK_STATUSES)),
            or_(*scope_filters),
        )
        .order_by(TaskRun.created_at.desc())
    )


async def list_active_tasks_for_owner(
    db: AsyncSession,
    user_id: int,
    *,
    project_id: int | None = None,
    drama_project_id: int | None = None,
) -> list[TaskRun]:
    """读取用户在指定项目范围内的活动任务，按创建时间倒序返回。"""
    scope_filters = []
    if project_id is not None:
        scope_filters.append(TaskRun.project_id == project_id)
    if drama_project_id is not None:
        scope_filters.append(TaskRun.drama_project_id == drama_project_id)
    if not scope_filters:
        return []
    stmt = _active_owner_tasks_statement(user_id, *scope_filters, include_teams=drama_project_id is not None)
    return list((await db.execute(stmt)).scalars().unique().all())


async def list_active_tasks_for_projects(
    db: AsyncSession,
    user_id: int,
    project_ids: list[int],
) -> dict[int, list[TaskRun]]:
    """一次读取一页科普项目的活动任务，分组后仍保持各项目的新任务优先。"""
    # 去重后的映射也为暂无活动任务的项目保留空列表；空页不访问数据库。
    grouped: dict[int, list[TaskRun]] = {int(project_id): [] for project_id in project_ids}
    if not grouped:
        return grouped
    stmt = _active_owner_tasks_statement(user_id, TaskRun.project_id.in_(list(grouped)))
    tasks = (await db.execute(stmt)).scalars().unique().all()
    for task in tasks:
        grouped[task.project_id].append(task)
    return grouped


async def cancel_tasks_for_scope(
    db: AsyncSession,
    user_id: int,
    *,
    domain: str | None = None,
    task_type: str | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    episode_id: int | None = None,
) -> list[TaskRun]:
    ownership_filter = (TaskRun.requested_by == user_id) & TaskRun.team_id.is_(None)
    if drama_project_id is not None:
        project = await db.get(DramaProject, drama_project_id)
        if project is not None and project.team_id is not None:
            from app.services.teams.access import get_team
            await get_team(db, int(project.team_id), user_id, roles={"owner", "admin"})
            ownership_filter = TaskRun.team_id == project.team_id
    filters = [ownership_filter, TaskRun.status.in_(tuple(ACTIVE_TASK_STATUSES)), TaskRun.cancel_requested.is_(False)]
    if project_id is not None:
        filters.append(TaskRun.project_id == project_id)
    if domain is not None:
        filters.append(TaskRun.domain == domain)
    if task_type is not None:
        filters.append(TaskRun.task_type == task_type)
    if drama_project_id is not None:
        filters.append(TaskRun.drama_project_id == drama_project_id)
    if episode_id is not None:
        filters.append(TaskRun.episode_id == episode_id)
    stmt = select(TaskRun).options(*task_detail_options()).where(*filters)
    tasks = list((await db.execute(stmt)).scalars().unique().all())
    for task in tasks:
        task.cancel_requested = True
        task.status = "cancel_requested"
        task.next_action_at = datetime.now(UTC)
        db.add(
            build_task_event(
                task.id,
                TaskEventCreate(
                    event_type="task.cancel_requested",
                    status=task.status,
                    phase=task.current_step_key,
                    message="由业务范围取消接口触发",
                ),
            )
        )
    if tasks:
        await db.commit()
    return tasks


async def get_task_for_runtime(db: AsyncSession, task_id: int) -> TaskRun | None:
    """执行器仅加载步骤与目标，避免重复读取整段上游/激活事件历史。"""
    stmt = (
        select(TaskRun)
        .options(selectinload(TaskRun.steps), selectinload(TaskRun.targets))
        .where(TaskRun.id == task_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_task_admin(db: AsyncSession, task_id: int) -> TaskRun:
    """管理员读取任务执行数据；完整历史由独立的有界事件查询提供。"""
    stmt = (
        select(TaskRun)
        .options(selectinload(TaskRun.steps), selectinload(TaskRun.targets), raiseload(TaskRun.events))
        .where(TaskRun.id == task_id)
    )
    task = (await db.execute(stmt)).scalar_one_or_none()
    if not task:
        raise LookupError("任务不存在")
    return task


async def list_tasks_admin(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    domain: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    user_id: int | None = None,
    q: str | None = None,
    active_only: bool = False,
) -> tuple[list[tuple[TaskRun, str | None]], int]:
    """List all task runs for admin with optional filters."""
    filters = []
    if domain:
        filters.append(TaskRun.domain == domain)
    if status:
        filters.append(TaskRun.status == status)
    elif active_only:
        filters.append(TaskRun.status.in_(tuple(ACTIVE_TASK_STATUSES)))
    if task_type:
        filters.append(TaskRun.task_type == task_type)
    if user_id:
        filters.append(TaskRun.requested_by == user_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                TaskRun.task_type.ilike(like),
                TaskRun.dedupe_key.ilike(like),
                TaskRun.client_request_id.ilike(like),
                TaskRun.provider_task_id.ilike(like),
                User.email.ilike(like),
            )
        )

    base_stmt: Select = (
        select(TaskRun, User.email)
        .join(User, User.id == TaskRun.requested_by)
        .where(*filters)
    )
    count_stmt = select(func.count()).select_from(TaskRun).join(User, User.id == TaskRun.requested_by).where(*filters)

    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    stmt = (
        base_stmt.options(selectinload(TaskRun.steps), selectinload(TaskRun.targets), raiseload(TaskRun.events))
        .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(stmt)).unique().all())
    return rows, total


async def cancel_task_admin(db: AsyncSession, task_id: int) -> TaskRun:
    """Cancel any task as admin."""
    task = await get_task_admin(db, task_id)
    if not task.cancelable:
        raise ValueError("任务不支持取消")
    if task.status in TERMINAL_TASK_STATUSES:
        raise ValueError("任务已结束，不能取消")
    task.cancel_requested = True
    task.status = "cancel_requested"
    task.next_action_at = datetime.now(UTC)
    db.add(
        build_task_event(
            task.id,
            TaskEventCreate(
                event_type="task.cancel_requested",
                status=task.status,
                phase=task.current_step_key,
                message="管理员已提交取消请求",
            ),
        )
    )
    await db.commit()
    if is_direct_llm_task(task.domain, task.task_type, task.payload):
        from app.services.tasks.scheduler import cancel_running_task
        await cancel_running_task(task.id)
    return await get_task_admin(db, task.id)


async def get_task_stats_admin(db: AsyncSession) -> dict[str, Any]:
    """Aggregate task platform stats for admin dashboard."""
    now = datetime.now(UTC)
    status_rows = (
        await db.execute(select(TaskRun.status, func.count()).group_by(TaskRun.status))
    ).all()
    status_counts = {str(status): int(count) for status, count in status_rows}

    ready_count, deferred_count, delayed_count, oldest_ready_at = (
        await db.execute(
            select(
                func.count().filter(TaskRun.next_action_at <= now),
                func.count().filter(TaskRun.next_action_at.is_(None)),
                func.count().filter(TaskRun.next_action_at > now),
                func.min(TaskRun.next_action_at).filter(TaskRun.next_action_at <= now),
            ).where(TaskRun.status == "pending")
        )
    ).one()
    oldest_ready_wait_sec = 0
    if oldest_ready_at is not None:
        if oldest_ready_at.tzinfo is None:
            oldest_ready_at = oldest_ready_at.replace(tzinfo=UTC)
        oldest_ready_wait_sec = max(0, int((now - oldest_ready_at).total_seconds()))

    domain_rows = (
        await db.execute(
            select(TaskRun.domain, TaskRun.status, func.count()).group_by(TaskRun.domain, TaskRun.status)
        )
    ).all()
    domain_map: dict[str, dict[str, int]] = {}
    for domain, status, count in domain_rows:
        bucket = domain_map.setdefault(str(domain), {})
        bucket[str(status)] = int(count)

    domains = []
    for domain, counts in sorted(domain_map.items()):
        pending = counts.get("pending", 0)
        active = sum(counts.get(s, 0) for s in ACTIVE_TASK_STATUSES if s != "pending")
        domains.append(
            {
                "domain": domain,
                "pending": pending,
                "active": active,
                "succeeded": counts.get("succeeded", 0),
                "failed": counts.get("failed", 0),
                "cancelled": counts.get("cancelled", 0),
            }
        )

    return {
        "pending_count": status_counts.get("pending", 0),
        "pending_ready_count": int(ready_count),
        "pending_deferred_count": int(deferred_count),
        "pending_delayed_count": int(delayed_count),
        "oldest_ready_wait_sec": oldest_ready_wait_sec,
        "active_count": sum(status_counts.get(s, 0) for s in ACTIVE_TASK_STATUSES if s != "pending"),
        "leased_count": status_counts.get("leased", 0),
        "running_count": status_counts.get("running", 0),
        "awaiting_poll_count": status_counts.get("awaiting_poll", 0),
        "cancel_requested_count": status_counts.get("cancel_requested", 0),
        "succeeded_count": status_counts.get("succeeded", 0),
        "failed_count": status_counts.get("failed", 0),
        "cancelled_count": status_counts.get("cancelled", 0),
        "domains": domains,
    }


async def append_task_event(
    db: AsyncSession,
    task_id: int,
    *,
    event_type: str,
    status: str | None = None,
    phase: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append one event inside runtime operations."""
    db.add(
        build_task_event(
            task_id,
            TaskEventCreate(
                event_type=event_type,
                status=status,
                phase=phase,
                message=message,
                payload=payload,
            ),
        )
    )


def set_task_step_state(task: TaskRun, step: TaskStep | None, *, status: str, now: datetime) -> None:
    """Keep run summary fields aligned with one step."""
    task.current_step_key = step.step_key if step else None
    task.current_step_status = status if step else None
    if step:
        step.status = status
        if status == "submitting" and step.started_at is None:
            step.started_at = now
        if status in {"done", "failed", "cancelled"}:
            step.finished_at = now
