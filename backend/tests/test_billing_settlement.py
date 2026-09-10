"""任务计费 settlement 单元测试（无 DB 依赖）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import User
from app.models_tasks import TaskRun
from app.services.billing.http import http_exception_for_value_error
from app.services.billing.settlement import billing_active, freeze_for_task, settle_task


def test_billing_active_follows_global_switch(monkeypatch) -> None:
    from app.config import get_settings

    user = User(id=1)
    settings = get_settings()
    monkeypatch.setattr(settings, "billing_enabled", True)
    assert billing_active(user, settings) is True
    monkeypatch.setattr(settings, "billing_enabled", False)
    assert billing_active(user, settings) is False


def test_http_exception_maps_insufficient_balance_to_402() -> None:
    exc = http_exception_for_value_error(ValueError("余额不足：需要 ¥1.00，当前 ¥0.00，请先充值"))
    assert exc.status_code == 402
    assert "余额不足" in exc.detail


def test_http_exception_maps_other_value_error_to_400() -> None:
    exc = http_exception_for_value_error(ValueError("参数错误"))
    assert exc.status_code == 400


@pytest.mark.asyncio
async def test_freeze_for_task_idempotent_when_already_frozen() -> None:
    """多阶段任务重入时不应重复扣款。"""
    task = TaskRun(
        id=99,
        domain="drama",
        task_type="fragment_video",
        requested_by=1,
        billing_status="frozen",
        billing_estimate_fen=500,
    )
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=task)
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()

    need = await freeze_for_task(db, task)

    assert need == 500
    assert task.billing_status == "frozen"
    # 幂等早退：不应再查用户或写 ledger
    assert db.execute.await_count == 1
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_settle_task_idempotent_when_prior_unfreeze_ledger() -> None:
    """并发二次结算：已有 unfreeze 流水时禁止再次退款。"""
    task = TaskRun(
        id=3056,
        domain="drama",
        task_type="fragment_video",
        requested_by=401,
        billing_status="frozen",
        billing_estimate_fen=2650,
        billing_charged_fen=1661,
        billing_refunded_fen=989,
    )

    lock_result = MagicMock()
    lock_result.scalar_one_or_none = MagicMock(return_value=task)
    prior_result = MagicMock()
    prior_result.scalar_one_or_none = MagicMock(return_value=1)
    usage_result = MagicMock()
    usage_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[lock_result, prior_result, usage_result])
    db.flush = AsyncMock()

    out = await settle_task(db, 3056)

    assert out == {"charged": 1661, "refunded": 989}
    assert task.billing_status == "settled"
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_settle_task_noop_when_already_settled() -> None:
    task = TaskRun(
        id=1,
        billing_status="settled",
        billing_charged_fen=100,
        billing_refunded_fen=50,
    )
    lock_result = MagicMock()
    lock_result.scalar_one_or_none = MagicMock(return_value=task)
    db = MagicMock()
    db.execute = AsyncMock(return_value=lock_result)

    out = await settle_task(db, 1)
    assert out == {"charged": 100, "refunded": 50}
    assert db.execute.await_count == 1


def test_fragment_video_already_applied_requires_done_generation() -> None:
    from app.models_drama import DramaEpisodeFragment
    from app.services.drama.jobs import _fragment_video_already_applied

    empty = DramaEpisodeFragment(id=1, video="", params={})
    assert _fragment_video_already_applied(empty) is False
    assert _fragment_video_already_applied(None) is False

    done = DramaEpisodeFragment(
        id=2,
        video="https://cdn.example/v.mp4",
        params={"generation": {"status": "done"}},
    )
    assert _fragment_video_already_applied(done) is True

    pending = DramaEpisodeFragment(
        id=3,
        video="https://cdn.example/v.mp4",
        params={"generation": {"status": "running"}},
    )
    assert _fragment_video_already_applied(pending) is False


@pytest.mark.asyncio
async def test_recover_complete_skips_when_not_awaiting_poll() -> None:
    """已收敛任务不再二次 activate / complete。"""
    from app.services.drama.jobs import _recover_complete_fragment_video

    done = TaskRun(id=42, status="succeeded", batch_key="b1")
    lock_result = MagicMock()
    lock_result.scalar_one_or_none = MagicMock(return_value=done)
    db = MagicMock()
    db.execute = AsyncMock(return_value=lock_result)

    ok = await _recover_complete_fragment_video(
        db, 42, fragment_id=9, batch_key="b1", batch_index=0
    )
    assert ok is False


@pytest.mark.asyncio
async def test_record_seedance_dedupes_by_provider_task_id() -> None:
    """无 billing_scope 时仍按 provider_task_id 幂等。"""
    from app.services.drama.billing_util import record_seedance_video_usage

    existing = MagicMock()
    existing.id = 11
    by_provider = MagicMock()
    by_provider.scalar_one_or_none = MagicMock(return_value=existing)
    db = MagicMock()
    db.execute = AsyncMock(return_value=by_provider)

    out = await record_seedance_video_usage(
        db,
        user_id=401,
        billing_key="seedance2:video0",
        model="seedance",
        domain="drama",
        provider_task_id="prov-abc-1",
    )
    assert out is existing
    db.execute.assert_awaited()
