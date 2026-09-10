"""Seedance 真实 usage 与估算 fallback 计费。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent
from app.services.ark import TaskResult
from app.services.drama.billing_util import record_seedance_video_usage
from tests.conftest import make_user


@pytest.mark.asyncio
async def test_record_seedance_video_usage_real_tokens(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    task_result = TaskResult(
        status="succeeded",
        total_tokens=100_000,
        completion_tokens=100_000,
        raw_usage={"total_tokens": 100_000},
    )
    await record_seedance_video_usage(
        db_session,
        user_id=user.id,
        billing_key="seedance2:video0",
        model="doubao-seedance-2-0",
        domain="drama",
        task_result=task_result,
        fallback_duration_sec=8,
        drama_project_id=1,
    )
    await db_session.commit()
    row = (await db_session.execute(select(UsageEvent).where(UsageEvent.user_id == user.id))).scalar_one()
    assert row.total_tokens == 100_000
    assert row.estimated is False
    assert row.cost_fen > 0


@pytest.mark.asyncio
async def test_record_seedance_video_usage_fallback_estimate(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await record_seedance_video_usage(
        db_session,
        user_id=user.id,
        billing_key="seedance2:video0",
        model="doubao-seedance-2-0",
        domain="kepu",
        task_result=None,
        fallback_duration_sec=5,
        project_id=9,
    )
    await db_session.commit()
    row = (await db_session.execute(select(UsageEvent).where(UsageEvent.user_id == user.id))).scalar_one()
    assert row.estimated is True
    assert row.total_tokens > 0
