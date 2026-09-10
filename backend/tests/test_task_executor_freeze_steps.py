"""Task executor regression: freeze 不得卸掉尚未读取的 steps。"""
from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_tasks import TaskStep
from app.services.billing.settlement import freeze_for_task
from app.services.tasks.executor import execute_task_run
from app.services.tasks.service import get_task_for_runtime, set_task_step_state

from tests.conftest import make_task, make_user


def test_execute_task_run_source_reads_steps_before_freeze() -> None:
    """源码顺序守卫：steps 必须在 freeze_for_task 之前读取，避免 MissingGreenlet。"""
    src = inspect.getsource(execute_task_run)
    i_steps = src.find("step = task.steps[0]")
    i_freeze = src.find("await freeze_for_task")
    assert i_steps != -1 and i_freeze != -1
    assert i_steps < i_freeze, "必须先读取 task.steps，再调用 freeze_for_task"


@pytest.mark.asyncio
async def test_freeze_expires_preloaded_steps_relationship(db_session: AsyncSession) -> None:
    """根因：_lock_task(populate_existing) 会使已 selectinload 的 steps 失效。"""
    user = await make_user(db_session, balance_fen=50_000)
    task = await make_task(db_session, user, domain="api", task_type="v1_image", status="leased")
    db_session.add(TaskStep(task_id=task.id, step_key="main", step_type="run", status="pending"))
    await db_session.commit()

    loaded = await get_task_for_runtime(db_session, int(task.id))
    assert loaded is not None
    assert len(loaded.steps) == 1
    await freeze_for_task(db_session, loaded)
    with pytest.raises(Exception) as ei:
        _ = list(loaded.steps)
    assert "MissingGreenlet" in type(ei.value).__name__ or "greenlet" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_held_step_survives_freeze_populate_existing(db_session: AsyncSession) -> None:
    """修复路径：先持有 step 再 freeze，仍可写步骤状态（不必再碰 task.steps）。"""
    user = await make_user(db_session, balance_fen=50_000)
    task = await make_task(db_session, user, domain="api", task_type="v1_image", status="leased")
    db_session.add(TaskStep(task_id=task.id, step_key="main", step_type="run", status="pending"))
    await db_session.commit()

    loaded = await get_task_for_runtime(db_session, int(task.id))
    assert loaded is not None
    step = loaded.steps[0] if loaded.steps else None
    assert step is not None

    await freeze_for_task(db_session, loaded)
    now = datetime.now(UTC)
    set_task_step_state(loaded, step, status="submitting", now=now)
    loaded.status = "running"
    await db_session.commit()

    assert step.status == "submitting"
    assert loaded.status == "running"
    assert loaded.current_step_key == "main"


@pytest.mark.asyncio
async def test_execute_task_run_survives_freeze_populate_existing(
    db_session: AsyncSession,
) -> None:
    """执行器在 freeze（会卸掉关系）后仍能把 leased 任务跑到 succeeded。

    execute_task_run 自开 AsyncSessionLocal；测试用外层事务对别的连接不可见，
    因此把 SessionLocal 钉到本用例 session。
    """
    user = await make_user(db_session, balance_fen=50_000)
    task = await make_task(
        db_session,
        user,
        domain="api",
        task_type="v1_image",
        status="leased",
    )
    db_session.add(
        TaskStep(
            task_id=task.id,
            step_key="main",
            step_type="run",
            status="pending",
        )
    )
    await db_session.commit()
    task_id = int(task.id)

    @asynccontextmanager
    async def same_session():
        yield db_session

    with patch("app.services.tasks.executor.AsyncSessionLocal", same_session):
        await execute_task_run(task_id)

    db_session.expire_all()
    done = await get_task_for_runtime(db_session, task_id)
    assert done is not None
    assert done.status == "succeeded"
    assert done.steps and done.steps[0].status == "done"


@pytest.mark.asyncio
async def test_execute_task_run_marks_failed_when_handler_returns_ok_false(
    db_session: AsyncSession,
) -> None:
    """handler 返回 {ok:False} 时 TaskRun 必须 failed，不能当成 succeeded。"""
    from app.services.tasks.handlers import TaskHandler

    user = await make_user(db_session, balance_fen=50_000)
    task = await make_task(
        db_session,
        user,
        domain="api",
        task_type="v1_image",
        status="leased",
    )
    db_session.add(
        TaskStep(
            task_id=task.id,
            step_key="main",
            step_type="run",
            status="pending",
        )
    )
    await db_session.commit()
    task_id = int(task.id)

    async def _failing_executor(_task):
        return {"ok": False, "error": "seedream_policy"}

    @asynccontextmanager
    async def same_session():
        yield db_session

    fake = TaskHandler("api", "v1_image", _failing_executor)
    with (
        patch("app.services.tasks.executor.AsyncSessionLocal", same_session),
        patch("app.services.tasks.executor.get_task_handler", return_value=fake),
    ):
        await execute_task_run(task_id)

    db_session.expire_all()
    done = await get_task_for_runtime(db_session, task_id)
    assert done is not None
    assert done.status == "failed"
    assert "seedream_policy" in (done.error_message or "")
    assert done.steps and done.steps[0].status == "failed"

