"""CRUD helpers for the unified task platform."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Project, Shot, User
from app.models_drama import DramaAsset, DramaEpisode, DramaEpisodeFragment, DramaProject, DramaScript
from app.models_tasks import TaskEvent, TaskRun, TaskStep, TaskTarget
from app.schemas_tasks import TaskCreateRequest, TaskEventCreate, TaskStepCreate, TaskUpdateRequest
from app.services.tasks.handlers import get_task_handler

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


def task_detail_options() -> tuple:
    return (
        selectinload(TaskRun.steps),
        selectinload(TaskRun.targets),
        selectinload(TaskRun.events),
    )


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
    """创建任务并预写步骤。commit=False 时仅 flush，由调用方与业务状态同事务提交。"""
    await _validate_task_scope(db, user, body)
    handler = get_task_handler(body.domain, body.task_type)
    if handler is None:
        raise ValueError("当前任务类型尚未接入任务平台")
    from app.services.billing.settlement import ensure_balance_for_task

    balance_probe = TaskRun(
        domain=body.domain,
        task_type=body.task_type,
        requested_by=user.id,
        payload=body.payload,
        project_id=body.project_id,
        drama_project_id=body.drama_project_id,
        episode_id=body.episode_id,
        fragment_id=body.fragment_id,
        asset_id=body.asset_id,
        shot_id=body.shot_id,
    )
    estimate_fen = await ensure_balance_for_task(db, user, balance_probe)
    planned_steps = handler.plan_steps(body)
    first_step = planned_steps[0] if planned_steps else None
    now = datetime.now(UTC)
    next_action = None if body.defer_activation else (body.scheduled_at or now)
    task = TaskRun(
        domain=body.domain,
        task_type=body.task_type,
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
    )
    db.add(task)
    await db.flush()
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
                payload={"domain": task.domain},
            ),
        )
    )
    if not commit:
        return task
    await db.commit()
    return await get_task_for_user(db, user, task.id)


# 串行 batch 中上一镜完成后激活下一镜任务。
async def activate_next_sequential_task(db: AsyncSession, batch_key: str | None, completed_index: int) -> None:
    if not batch_key:
        return
    from app.config import get_settings
    from app.services.drama.access import count_user_inflight_fragment_video_tasks

    next_index = int(completed_index) + 1
    stmt = (
        select(TaskRun)
        .where(
            TaskRun.batch_key == batch_key,
            TaskRun.status == "pending",
        )
        .order_by(TaskRun.id.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    for task in rows:
        payload = task.payload if isinstance(task.payload, dict) else {}
        if int(payload.get("batch_index", -1)) != next_index:
            continue
        limit = max(1, int(get_settings().drama_user_video_job_limit or 12))
        inflight = await count_user_inflight_fragment_video_tasks(db, int(task.requested_by))
        if inflight >= limit:
            return
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
        return


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
        if str(task.billing_status or "") == "frozen":
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
    if str(task.billing_status or "") == "frozen":
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
async def reconcile_stale_pending_tasks(db: AsyncSession) -> int:
    stmt = select(TaskRun).where(
        TaskRun.status.in_(tuple(_STALE_FRAGMENT_VIDEO_STATUSES)),
        TaskRun.domain == "drama",
        TaskRun.task_type == "fragment_video",
    )
    rows = list((await db.execute(stmt)).scalars().all())
    changed = 0
    now = datetime.now(UTC)
    for task in rows:
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


# 修复串行 batch 中 next_action_at 为空导致永远排队的任务；并行 batch 按用户并发上限逐步激活。
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

        succeeded_indices = [
            int((t.payload or {}).get("batch_index", -1))
            for t in tasks
            if t.status == "succeeded" and isinstance(t.payload, dict)
        ]
        if succeeded_indices:
            await activate_next_sequential_task(db, batch_key, max(succeeded_indices))
            changed += 1
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

    heads_to_activate: list[TaskRun] = []
    for ep_id, ep_tasks in by_episode.items():
        ep_tasks.sort(
            key=lambda task: (
                sort_by_frag.get(int(task.fragment_id or 0), 10**9),
                int(task.id),
            )
        )
        head: TaskRun | None = None
        for task in ep_tasks:
            if task.status in {"leased", "running", "awaiting_poll"}:
                head = task
                break
            if task.status == "pending":
                head = task
                break
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
async def count_user_active_runtime_tasks(db: AsyncSession, user_id: int) -> int:
    stmt = select(func.count()).select_from(TaskRun).where(
        TaskRun.requested_by == int(user_id),
        TaskRun.status.in_(("leased", "running")),
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


# 统计已注册、等待 Selector 轮询的上游任务数。
async def count_awaiting_poll_tasks(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(TaskRun).where(TaskRun.status == "awaiting_poll")
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _validate_task_scope(db: AsyncSession, user: User, body: TaskCreateRequest) -> None:
    if body.project_id is not None:
        project = await db.get(Project, body.project_id)
        if not project or int(project.user_id) != int(user.id):
            raise ValueError("科普项目不存在或无权限")
    if body.shot_id is not None:
        shot = await db.get(Shot, body.shot_id)
        if not shot:
            raise ValueError("镜头不存在")
        project = await db.get(Project, int(shot.project_id))
        if not project or int(project.user_id) != int(user.id):
            raise ValueError("镜头不存在或无权限")
        if body.project_id is not None and int(shot.project_id) != int(body.project_id):
            raise ValueError("镜头与项目不匹配")

    drama_project_id: int | None = body.drama_project_id
    if drama_project_id is not None:
        drama_project = await db.get(DramaProject, drama_project_id)
        if not drama_project or int(drama_project.user_id) != int(user.id):
            raise ValueError("漫剧项目不存在或无权限")
    if body.script_id is not None:
        script = await db.get(DramaScript, body.script_id)
        if not script:
            raise ValueError("剧本不存在")
        drama_project = await db.get(DramaProject, int(script.project_id))
        if not drama_project or int(drama_project.user_id) != int(user.id):
            raise ValueError("剧本不存在或无权限")
        if drama_project_id is not None and int(script.project_id) != int(drama_project_id):
            raise ValueError("剧本与漫剧项目不匹配")
    if body.episode_id is not None:
        episode = await db.get(DramaEpisode, body.episode_id)
        if not episode:
            raise ValueError("分集不存在")
        drama_project = await db.get(DramaProject, int(episode.project_id))
        if not drama_project or int(drama_project.user_id) != int(user.id):
            raise ValueError("分集不存在或无权限")
        if drama_project_id is not None and int(episode.project_id) != int(drama_project_id):
            raise ValueError("分集与漫剧项目不匹配")
    if body.fragment_id is not None:
        fragment = await db.get(DramaEpisodeFragment, body.fragment_id)
        if not fragment:
            raise ValueError("分镜不存在")
        episode = await db.get(DramaEpisode, int(fragment.episode_id))
        drama_project = await db.get(DramaProject, int(episode.project_id)) if episode else None
        if not episode or not drama_project or int(drama_project.user_id) != int(user.id):
            raise ValueError("分镜不存在或无权限")
        if body.episode_id is not None and int(fragment.episode_id) != int(body.episode_id):
            raise ValueError("分镜与分集不匹配")
    if body.asset_id is not None:
        asset = await db.get(DramaAsset, body.asset_id)
        if not asset:
            raise ValueError("资产不存在")
        drama_project = await db.get(DramaProject, int(asset.project_id))
        if not drama_project or int(drama_project.user_id) != int(user.id):
            raise ValueError("资产不存在或无权限")
        if drama_project_id is not None and int(asset.project_id) != int(drama_project_id):
            raise ValueError("资产与漫剧项目不匹配")


async def get_task_for_user(db: AsyncSession, user: User, task_id: int) -> TaskRun:
    stmt = (
        select(TaskRun)
        .options(*task_detail_options())
        .where(TaskRun.id == task_id, TaskRun.requested_by == user.id)
    )
    task = (await db.execute(stmt)).scalar_one_or_none()
    if not task:
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
    target_type: str | None = None,
    target_id: int | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
) -> tuple[list[TaskRun], int]:
    filters = [TaskRun.requested_by == user.id]
    if domain:
        filters.append(TaskRun.domain == domain)
    if status:
        filters.append(TaskRun.status == status)
    if task_type:
        filters.append(TaskRun.task_type == task_type)
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


async def update_task_for_user(
    db: AsyncSession,
    user: User,
    task_id: int,
    body: TaskUpdateRequest,
) -> TaskRun:
    task = await get_task_for_user(db, user, task_id)
    now = datetime.now(UTC)
    prev_status = task.status
    prev_step_key = task.current_step_key
    prev_step_status = task.current_step_status
    if body.status is not None:
        task.status = body.status
    if body.current_step_key is not None:
        task.current_step_key = body.current_step_key
    if body.current_step_status is not None:
        task.current_step_status = body.current_step_status
    if body.provider_task_id is not None:
        task.provider_task_id = body.provider_task_id
    if body.scheduled_at is not None:
        task.scheduled_at = body.scheduled_at
    if body.next_action_at is not None:
        task.next_action_at = body.next_action_at
    if body.lease_token is not None:
        task.lease_token = body.lease_token
    if body.lease_until is not None:
        task.lease_until = body.lease_until
    if body.progress_percent is not None:
        task.progress_percent = body.progress_percent
    if body.error_code is not None:
        task.error_code = body.error_code
    if body.error_message is not None:
        task.error_message = body.error_message
    if body.payload is not None:
        task.payload = body.payload
    if body.result_payload is not None:
        task.result_payload = body.result_payload
    if prev_status != "running" and task.status == "running" and task.started_at is None:
        task.started_at = now
    if body.status in TERMINAL_TASK_STATUSES:
        task.finished_at = now
    db.add(
        build_task_event(
            task.id,
            TaskEventCreate(
                event_type="task.updated",
                status=task.status,
                phase=task.current_step_key,
                message=f"{prev_status}/{prev_step_status} -> {task.status}/{task.current_step_status}",
                payload={
                    "previous_status": prev_status,
                    "previous_step_key": prev_step_key,
                    "previous_step_status": prev_step_status,
                },
            ),
        )
    )
    await db.commit()
    return await get_task_for_user(db, user, task.id)


async def cancel_task_for_user(db: AsyncSession, user: User, task_id: int) -> TaskRun:
    task = await get_task_for_user(db, user, task_id)
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
    return await get_task_for_user(db, user, task.id)


async def retry_task_for_user(db: AsyncSession, user: User, task_id: int) -> TaskRun:
    task = await get_task_for_user(db, user, task_id)
    if task.status not in {"failed", "cancelled"}:
        raise ValueError("仅失败或已取消任务支持重试")
    # 分镜视频：旧任务绑定的分镜若已删，禁止重试，须在分集页按当前分镜重新生成
    if task.domain == "drama" and task.task_type == "fragment_video":
        frag_ids = task_fragment_ids(task)
        if not frag_ids:
            raise ValueError(_STALE_FRAGMENT_REASON)
        for frag_id in frag_ids:
            frag = await db.get(DramaEpisodeFragment, frag_id)
            if frag is None:
                raise ValueError(_STALE_FRAGMENT_REASON)
            # 用户/后台点重试：清零内部重试计数，并从 prepare 阶段重跑
            params = dict(frag.params or {})
            params.pop("generation_attempts", None)
            params["generation"] = {
                "status": "queued",
                "queued_at": datetime.now(UTC).isoformat(),
                "message": "任务重试已入队",
            }
            frag.params = params
    payload = dict(task.payload or {}) if isinstance(task.payload, dict) else {}
    # 分镜视频重试不沿用旧 nio 阶段与内部 attempt，避免被「超过上限」直接拦住
    if task.domain == "drama" and task.task_type == "fragment_video":
        for key in (
            "nio_phase",
            "generation_attempts",
            "attempt_limit",
            "prepared",
            "provider_task_id",
        ):
            payload.pop(key, None)
    body = TaskCreateRequest(
        domain=task.domain,
        task_type=task.task_type,
        priority=task.priority,
        client_request_id=task.client_request_id,
        dedupe_key=None,
        batch_key=task.batch_key,
        provider_task_id=None,
        cancelable=task.cancelable,
        scheduled_at=datetime.now(UTC),
        payload=payload or None,
        result_payload=None,
        project_id=task.project_id,
        drama_project_id=task.drama_project_id,
        script_id=task.script_id,
        episode_id=task.episode_id,
        fragment_id=task.fragment_id,
        asset_id=task.asset_id,
        shot_id=task.shot_id,
        targets=[
            {
                "target_type": item.target_type,
                "target_id": item.target_id,
                "sort_order": item.sort_order,
                "metadata_json": item.metadata_json,
            }
            for item in task.targets
        ],
    )
    create_body = TaskCreateRequest.model_validate(body.model_dump())
    return await create_task(db, user, create_body)


async def list_active_tasks_for_owner(
    db: AsyncSession,
    user_id: int,
    *,
    project_id: int | None = None,
    drama_project_id: int | None = None,
) -> list[TaskRun]:
    scope_filters = []
    if project_id is not None:
        scope_filters.append(TaskRun.project_id == project_id)
    if drama_project_id is not None:
        scope_filters.append(TaskRun.drama_project_id == drama_project_id)
    if not scope_filters:
        return []
    filters = [
        TaskRun.requested_by == user_id,
        TaskRun.status.in_(tuple(ACTIVE_TASK_STATUSES)),
        or_(*scope_filters),
    ]
    stmt = select(TaskRun).options(*task_detail_options()).where(*filters).order_by(TaskRun.created_at.desc())
    return list((await db.execute(stmt)).scalars().unique().all())


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
    filters = [
        TaskRun.requested_by == user_id,
        TaskRun.status.in_(tuple(ACTIVE_TASK_STATUSES)),
        TaskRun.cancel_requested.is_(False),
    ]
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
    """Load one task with full details for runtime loops."""
    stmt = select(TaskRun).options(*task_detail_options()).where(TaskRun.id == task_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_task_admin(db: AsyncSession, task_id: int) -> TaskRun:
    """Load one task for admin without ownership check."""
    stmt = select(TaskRun).options(*task_detail_options()).where(TaskRun.id == task_id)
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
        base_stmt.options(*task_detail_options())
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
    return await get_task_admin(db, task.id)


async def get_task_stats_admin(db: AsyncSession) -> dict[str, Any]:
    """Aggregate task platform stats for admin dashboard."""
    status_rows = (
        await db.execute(select(TaskRun.status, func.count()).group_by(TaskRun.status))
    ).all()
    status_counts = {str(status): int(count) for status, count in status_rows}

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
