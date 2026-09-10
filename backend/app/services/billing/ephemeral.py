# -*- coding: utf-8 -*-
"""轻量 TaskRun：同步执行并计费（聊天、API、工具）。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models_tasks import TaskRun
from app.schemas_tasks import TaskCreateRequest, TaskEventCreate, TaskStepCreate
from sqlalchemy import select

from app.config import get_settings
from app.services.billing.context import billing_scope
from app.services.billing.settlement import freeze_for_task, settle_task
from app.services.billing.usage import record_line
from app.services.tasks.executor import execute_task_run
from app.services.tasks.handlers import get_task_handler
from app.services.tasks.service import append_task_event, build_task_event, build_task_step

T = TypeVar("T")


async def create_ephemeral_task_row(
    db: AsyncSession,
    user: User,
    *,
    domain: str,
    task_type: str,
    payload: dict | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    shot_id: int | None = None,
    fragment_id: int | None = None,
    asset_id: int | None = None,
    episode_id: int | None = None,
) -> TaskRun:
    """创建并立即执行的轻量任务行（不经过调度器排队）。"""
    handler = get_task_handler(domain, task_type)
    planned = handler.plan_steps(TaskCreateRequest(domain=domain, task_type=task_type)) if handler else []
    first = planned[0] if planned else None
    now = datetime.now(UTC)
    task = TaskRun(
        domain=domain,
        task_type=task_type,
        status="pending",
        priority=1,
        requested_by=user.id,
        cancelable=False,
        current_step_key=first.step_key if first else task_type,
        current_step_status="pending" if first else None,
        scheduled_at=now,
        next_action_at=now,
        payload=payload or {},
        project_id=project_id,
        drama_project_id=drama_project_id,
        shot_id=shot_id,
        fragment_id=fragment_id,
        asset_id=asset_id,
        episode_id=episode_id,
    )
    db.add(task)
    await db.flush()
    if first:
        db.add(build_task_step(task.id, first))
    db.add(
        build_task_event(
            task.id,
            TaskEventCreate(
                event_type="task.created",
                status=task.status,
                phase=task.current_step_key,
                message=f"轻量任务 {task_type}",
                payload={"ephemeral": True},
            ),
        )
    )
    await db.flush()
    return task


async def run_billed_ephemeral(
    db: AsyncSession,
    user: User,
    *,
    domain: str,
    task_type: str,
    executor: Callable[[], Awaitable[T]],
    payload: dict | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    shot_id: int | None = None,
    fragment_id: int | None = None,
    asset_id: int | None = None,
    episode_id: int | None = None,
    commit: bool = True,
) -> tuple[TaskRun, T]:
    """
    创建轻量 TaskRun → 预扣 → 在 billing_scope 内执行 → 结算。
    用于聊天、开放 API、工作室工具等同步调用。
    """
    task = await create_ephemeral_task_row(
        db,
        user,
        domain=domain,
        task_type=task_type,
        payload=payload,
        project_id=project_id,
        drama_project_id=drama_project_id,
        shot_id=shot_id,
        fragment_id=fragment_id,
        asset_id=asset_id,
        episode_id=episode_id,
    )
    try:
        await freeze_for_task(db, task)
    except ValueError:
        task.status = "failed"
        task.error_code = "insufficient_balance"
        task.error_message = "余额不足"
        # 未预扣成功，保持 none，勿标 skipped（skipped 表示全局关闭计费）
        task.billing_status = "none"
        await db.flush()
        raise

    now = datetime.now(UTC)
    task.status = "running"
    task.started_at = now
    await append_task_event(
        db,
        task.id,
        event_type="task.started",
        status=task.status,
        message="轻量任务开始",
    )
    await db.flush()

    result: T
    try:
        async with billing_scope(task.id):
            result = await executor()
        task.status = "succeeded"
        task.progress_percent = 100
        task.finished_at = datetime.now(UTC)
        task.result_payload = {"ok": True} if result is None else {"ok": True, "result": str(type(result))}
        await append_task_event(
            db,
            task.id,
            event_type="task.completed",
            status=task.status,
            message="轻量任务完成",
        )
    except Exception as exc:
        task.status = "failed"
        task.error_code = "ephemeral_failed"
        task.error_message = str(exc)[:500]
        task.finished_at = datetime.now(UTC)
        await append_task_event(
            db,
            task.id,
            event_type="task.failed",
            status=task.status,
            message=str(exc)[:200],
        )
        await settle_task(db, task.id)
        if commit:
            await db.commit()
        raise

    await settle_task(db, task.id)
    if commit:
        await db.commit()
    await db.refresh(task)
    return task, result


def _extract_provider_task_id(result: Any) -> str:
    """从 executor 返回值解析上游 task_id。"""
    if isinstance(result, dict):
        raw = result.get("task_id") or result.get("provider_task_id") or ""
        return str(raw).strip()
    return str(result).strip()


async def run_billed_ephemeral_deferred(
    db: AsyncSession,
    user: User,
    *,
    domain: str,
    task_type: str,
    executor: Callable[[], Awaitable[T]],
    payload: dict | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    shot_id: int | None = None,
    fragment_id: int | None = None,
    asset_id: int | None = None,
    episode_id: int | None = None,
    commit: bool = True,
) -> tuple[TaskRun, T]:
    """
    轻量 TaskRun：预扣 → 提交上游异步任务 → 保持 awaiting_poll，轮询终态后再结算。
    用于开放 API / 工作室生视频，避免提交成功即扣费。
    """
    task = await create_ephemeral_task_row(
        db,
        user,
        domain=domain,
        task_type=task_type,
        payload=payload,
        project_id=project_id,
        drama_project_id=drama_project_id,
        shot_id=shot_id,
        fragment_id=fragment_id,
        asset_id=asset_id,
        episode_id=episode_id,
    )
    try:
        await freeze_for_task(db, task)
    except ValueError:
        task.status = "failed"
        task.error_code = "insufficient_balance"
        task.error_message = "余额不足"
        task.billing_status = "none"
        await db.flush()
        raise

    now = datetime.now(UTC)
    task.status = "running"
    task.started_at = now
    await append_task_event(
        db,
        task.id,
        event_type="task.started",
        status=task.status,
        message="轻量视频任务开始",
    )
    await db.flush()

    result: T
    try:
        async with billing_scope(task.id):
            result = await executor()
        provider_id = _extract_provider_task_id(result)
        if not provider_id:
            raise RuntimeError("上游未返回 task_id")
        task.status = "awaiting_poll"
        task.provider_task_id = provider_id
        task.progress_percent = 30
        task.next_action_at = now
        task.result_payload = {"awaiting_poll": True, "provider_task_id": provider_id}
        await append_task_event(
            db,
            task.id,
            event_type="task.submitted",
            status=task.status,
            message="已提交上游，等待轮询",
            payload={"provider_task_id": provider_id},
        )
    except Exception as exc:
        task.status = "failed"
        task.error_code = "ephemeral_failed"
        task.error_message = str(exc)[:500]
        task.finished_at = datetime.now(UTC)
        await append_task_event(
            db,
            task.id,
            event_type="task.failed",
            status=task.status,
            message=str(exc)[:200],
        )
        await settle_task(db, task.id)
        if commit:
            await db.commit()
        raise

    if commit:
        await db.commit()
    await db.refresh(task)
    return task, result


async def settle_deferred_video_poll(
    db: AsyncSession,
    user: User,
    *,
    provider_task_id: str,
    poll_status: str,
    error: str | None = None,
    billing_task_id: int | None = None,
    usage_tokens: int = 0,
    completion_tokens: int = 0,
    raw_usage: dict | None = None,
    billing_key: str | None = None,
) -> None:
    """轮询终态后结算轻量视频任务：成功才记 seedance 用量。

    用行锁 + billing_status==frozen 门闩，避免客户端轮询与后台 poller 并发双记用量。
    """
    from app.services.billing.settlement import _lock_task

    terminal = (poll_status or "").strip().lower()
    if terminal in {"", "running", "queued"}:
        return

    task_id: int | None = None
    if billing_task_id:
        probe = await db.get(TaskRun, billing_task_id)
        if probe and int(probe.requested_by) == int(user.id):
            task_id = int(probe.id)
    if task_id is None and provider_task_id.strip():
        stmt = (
            select(TaskRun.id)
            .where(
                TaskRun.requested_by == user.id,
                TaskRun.provider_task_id == provider_task_id.strip(),
                TaskRun.billing_status == "frozen",
            )
            .order_by(TaskRun.id.desc())
            .limit(1)
        )
        task_id = (await db.execute(stmt)).scalar_one_or_none()
    if task_id is None:
        return

    # 原子门闩：仅 frozen 任务可进入结算；并发第二次拿到 settled 后直接返回
    task = await _lock_task(db, task_id)
    if not task or task.billing_status != "frozen":
        return
    if int(task.requested_by) != int(user.id):
        return

    now = datetime.now(UTC)
    if terminal == "succeeded":
        payload = task.payload if isinstance(task.payload, dict) else {}
        async with billing_scope(task.id):
            from app.services.drama.billing_util import record_seedance_video_usage, seedance_billing_key

            generate_audio = bool(payload.get("generate_audio", True))
            key = billing_key or seedance_billing_key(generate_audio=generate_audio)
            task_result = None
            if usage_tokens > 0:
                from app.services.ark import TaskResult

                task_result = TaskResult(
                    status="succeeded",
                    total_tokens=int(usage_tokens),
                    completion_tokens=int(completion_tokens or usage_tokens),
                    raw_usage=raw_usage,
                )
            await record_seedance_video_usage(
                db,
                user_id=user.id,
                billing_key=key,
                model=get_settings().model_video,
                domain=task.domain or "api",
                task_result=task_result,
                fallback_duration_sec=payload.get("duration"),
                provider_task_id=provider_task_id,
                project_id=task.project_id,
                drama_project_id=task.drama_project_id,
                shot_id=task.shot_id,
            )
        task.status = "succeeded"
        task.progress_percent = 100
        task.finished_at = now
        task.error_code = None
        task.error_message = None
        await append_task_event(
            db,
            task.id,
            event_type="task.completed",
            status=task.status,
            message="视频生成完成",
        )
    else:
        task.status = "failed"
        task.error_code = "upstream_failed"
        task.error_message = (error or "生成失败")[:500]
        task.finished_at = now
        await append_task_event(
            db,
            task.id,
            event_type="task.failed",
            status=task.status,
            message=task.error_message,
        )

    await settle_task(db, task.id)


async def run_with_registered_handler(
    db: AsyncSession,
    user: User,
    body: TaskCreateRequest,
    *,
    commit: bool = True,
) -> TaskRun:
    """创建任务并同步执行已注册 handler（跳过后台调度器）。"""
    from app.services.tasks.service import create_task

    task = await create_task(db, user, body, commit=commit)
    await execute_task_run(task.id)
    refreshed = await db.get(TaskRun, task.id)
    return refreshed or task
