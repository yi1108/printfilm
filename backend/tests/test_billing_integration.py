"""TaskRun 计费链路集成测试（PostgreSQL）。"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent, WalletLedger
from app.models_tasks import TaskRun
from app.schemas_tasks import TaskCreateRequest
from app.services.billing.context import billing_scope
from app.services.billing.ephemeral import settle_deferred_video_poll
from app.services.billing.settlement import (
    ensure_balance_for_task,
    freeze_for_task,
    settle_task,
)
from app.services.billing.usage import record_line, record_llm_chat_line
from app.services.tasks.service import create_task

from tests.conftest import make_task, make_user


@pytest.mark.asyncio
async def test_freeze_settle_refunds_unused_estimate(db_session: AsyncSession) -> None:
    """预扣 → 记少量用量 → 结算应退回多余冻结。"""
    user = await make_user(db_session, balance_fen=10_000)
    task = await make_task(db_session, user, domain="drama", task_type="agent_chat")
    await db_session.commit()

    balance_before = user.balance_fen
    need = await freeze_for_task(db_session, task)
    assert need > 0
    assert user.balance_fen == balance_before - need
    assert user.frozen_fen == need
    assert task.billing_status == "frozen"

    # 第二次 freeze 幂等
    need2 = await freeze_for_task(db_session, task)
    assert need2 == need
    assert user.balance_fen == balance_before - need
    assert user.frozen_fen == need

    async with billing_scope(task.id):
        await record_line(
            db_session,
            user_id=user.id,
            billing_key="llm_chat",
            model="test-llm",
            tokens=1000,
            estimated=True,
            domain="drama",
        )
    await db_session.commit()

    result = await settle_task(db_session, task.id)
    await db_session.commit()

    assert result["charged"] > 0
    assert result["charged"] < need
    assert result["refunded"] == need - result["charged"]
    assert user.frozen_fen == 0
    assert user.balance_fen == balance_before - result["charged"]
    assert task.billing_status == "settled"

    ev = (await db_session.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))).scalar_one()
    assert ev.settled is True
    assert ev.task_run_id == task.id


@pytest.mark.asyncio
async def test_ensure_balance_rejects_insufficient_funds(db_session: AsyncSession) -> None:
    """入队前余额预检应抛 ValueError。"""
    user = await make_user(db_session, balance_fen=0)
    task = await make_task(db_session, user, domain="api", task_type="v1_image")
    await db_session.commit()

    with pytest.raises(ValueError, match="余额不足"):
        await ensure_balance_for_task(db_session, user, task)


@pytest.mark.asyncio
async def test_create_task_rejects_insufficient_balance(db_session: AsyncSession) -> None:
    """create_task 入队前同步预检余额。"""
    user = await make_user(db_session, balance_fen=0)
    await db_session.commit()

    with pytest.raises(ValueError, match="余额不足"):
        await create_task(
            db_session,
            user,
            TaskCreateRequest(domain="api", task_type="v1_image"),
            commit=False,
        )


@pytest.mark.asyncio
async def test_ensure_balance_counts_pending_unfrozen_tasks(db_session: AsyncSession) -> None:
    """已有排队任务占用估算时，后续入队应累计校验余额。"""
    from app.services.billing.estimates import estimate_task_fen

    user = await make_user(db_session, balance_fen=500)
    task1 = await make_task(
        db_session,
        user,
        domain="drama",
        task_type="asset_image",
        status="pending",
        billing_status="none",
    )
    unit = await estimate_task_fen(db_session, task1)
    task1.billing_estimate_fen = unit
    user.balance_fen = unit
    await db_session.commit()

    task2 = await make_task(
        db_session,
        user,
        domain="drama",
        task_type="asset_image",
        status="pending",
        billing_status="none",
    )
    with pytest.raises(ValueError, match="余额不足"):
        await ensure_balance_for_task(db_session, user, task2)


@pytest.mark.asyncio
async def test_create_task_stores_billing_estimate_at_enqueue(db_session: AsyncSession) -> None:
    """create_task 入队时应写入 billing_estimate_fen，供后续累计校验。"""
    user = await make_user(db_session, balance_fen=100_000)
    task = await make_task(db_session, user, domain="api", task_type="v1_image")
    await db_session.commit()

    from app.services.billing.estimates import estimate_task_fen

    probe = TaskRun(domain="api", task_type="v1_image", requested_by=user.id, payload={})
    expected = await estimate_task_fen(db_session, probe)

    created = await create_task(
        db_session,
        user,
        TaskCreateRequest(domain="api", task_type="v1_image"),
        commit=True,
    )
    assert int(created.billing_estimate_fen or 0) == expected


@pytest.mark.asyncio
async def test_ensure_balance_for_task_batch_rejects_insufficient(db_session: AsyncSession) -> None:
    from app.models_tasks import TaskRun
    from app.services.billing.estimates import estimate_task_fen
    from app.services.billing.settlement import ensure_balance_for_task_batch

    user = await make_user(db_session, balance_fen=100)
    probe = TaskRun(domain="drama", task_type="asset_image", requested_by=user.id, payload={})
    unit = await estimate_task_fen(db_session, probe)
    user.balance_fen = unit * 2
    await db_session.commit()

    await ensure_balance_for_task_batch(db_session, user, probe, 2)

    with pytest.raises(ValueError, match="批量生成"):
        await ensure_balance_for_task_batch(db_session, user, probe, 3)


@pytest.mark.asyncio
async def test_billing_disabled_skips_wallet_but_settles_usage(
    db_session: AsyncSession, monkeypatch
) -> None:
    """全局关闭计费：不扣钱包，但用量行应标记 settled。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "billing_enabled", False)

    user = await make_user(db_session, balance_fen=0)
    task = await make_task(db_session, user, domain="drama", task_type="agent_chat")
    await db_session.commit()

    frozen = await freeze_for_task(db_session, task)
    assert frozen == 0
    assert task.billing_status == "skipped"
    assert user.balance_fen == 0
    assert user.frozen_fen == 0

    async with billing_scope(task.id):
        await record_line(
            db_session,
            user_id=user.id,
            billing_key="llm_chat",
            tokens=500,
            domain="drama",
        )
    await db_session.commit()

    result = await settle_task(db_session, task.id)
    await db_session.commit()

    assert result["charged"] > 0
    assert user.balance_fen == 0
    assert task.billing_status == "settled"
    ev = (await db_session.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))).scalar_one()
    assert ev.settled is True

    # 幂等：再次结算不报错
    again = await settle_task(db_session, task.id)
    assert again["charged"] == result["charged"]


@pytest.mark.asyncio
async def test_settle_deferred_video_poll_idempotent_on_success(db_session: AsyncSession) -> None:
    """成功结算后再次调用不应重复记用量。"""
    user = await make_user(db_session, balance_fen=50_000)
    task = await make_task(
        db_session,
        user,
        domain="api",
        task_type="v1_video",
        status="awaiting_poll",
        billing_status="none",
        provider_task_id="upstream-ok-1",
    )
    await freeze_for_task(db_session, task)
    task.status = "awaiting_poll"
    await db_session.commit()

    await settle_deferred_video_poll(
        db_session,
        user,
        provider_task_id="upstream-ok-1",
        poll_status="succeeded",
        billing_task_id=task.id,
        usage_tokens=120_000,
        completion_tokens=120_000,
    )
    await db_session.commit()

    assert task.billing_status == "settled"
    assert task.status == "succeeded"
    usage_rows = (
        await db_session.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))
    ).scalars().all()
    first_count = len(usage_rows)
    assert first_count == 1
    assert usage_rows[0].total_tokens == 120_000
    assert usage_rows[0].estimated is False
    charged = int(task.billing_charged_fen or 0)
    balance_after = user.balance_fen

    # 第二次：门闩应直接返回
    await settle_deferred_video_poll(
        db_session,
        user,
        provider_task_id="upstream-ok-1",
        poll_status="succeeded",
        billing_task_id=task.id,
    )
    await db_session.commit()

    second_count = len(
        (await db_session.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))).scalars().all()
    )
    assert second_count == 1
    assert int(task.billing_charged_fen or 0) == charged
    assert user.balance_fen == balance_after


@pytest.mark.asyncio
async def test_settle_deferred_video_poll_failed_refunds_freeze(db_session: AsyncSession) -> None:
    """轻量视频轮询失败：不记 seedance 用量，预扣全额退回。"""
    user = await make_user(db_session, balance_fen=50_000)
    task = await make_task(
        db_session,
        user,
        domain="api",
        task_type="v1_video",
        status="awaiting_poll",
        billing_status="none",
        provider_task_id="upstream-task-1",
    )
    await freeze_for_task(db_session, task)
    task.status = "awaiting_poll"
    await db_session.commit()

    balance_after_freeze = user.balance_fen
    frozen_after_freeze = user.frozen_fen
    assert frozen_after_freeze > 0

    await settle_deferred_video_poll(
        db_session,
        user,
        provider_task_id="upstream-task-1",
        poll_status="failed",
        error="upstream error",
        billing_task_id=task.id,
    )
    await db_session.commit()

    assert task.status == "failed"
    assert task.billing_status == "settled"
    assert user.frozen_fen == 0
    assert user.balance_fen == balance_after_freeze + task.billing_refunded_fen
    assert task.billing_charged_fen == 0
    assert task.billing_refunded_fen == frozen_after_freeze

    usage_count = (
        await db_session.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))
    ).scalar_one_or_none()
    assert usage_count is None


@pytest.mark.asyncio
async def test_freeze_writes_wallet_ledger(db_session: AsyncSession) -> None:
    """预扣应写入 freeze 流水。"""
    user = await make_user(db_session, balance_fen=20_000)
    task = await make_task(db_session, user)
    await db_session.commit()

    await freeze_for_task(db_session, task)
    await db_session.commit()

    row = (
        await db_session.execute(
            select(WalletLedger).where(
                WalletLedger.user_id == user.id,
                WalletLedger.kind == "freeze",
                WalletLedger.ref_type == "task_run",
                WalletLedger.ref_id == str(task.id),
            )
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.delta_fen < 0


@pytest.mark.asyncio
async def test_record_llm_chat_line_skips_without_billing_scope(db_session: AsyncSession) -> None:
    """无 billing_scope 时不写 usage（由调用方聚合计费）。"""
    user = await make_user(db_session)
    await db_session.commit()

    ev = await record_llm_chat_line(
        db_session,
        user_id=user.id,
        domain="drama",
        drama_project_id=1,
    )
    assert ev is None
    count = len((await db_session.execute(select(UsageEvent))).scalars().all())
    assert count == 0


@pytest.mark.asyncio
async def test_record_llm_chat_line_writes_in_billing_scope(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    task = await make_task(db_session, user, domain="drama", task_type="asset_image")
    await db_session.commit()

    async with billing_scope(task.id):
        ev = await record_llm_chat_line(
            db_session,
            user_id=user.id,
            domain="drama",
            drama_project_id=99,
        )
    await db_session.commit()

    assert ev is not None
    assert ev.billing_key == "llm_chat"
    assert ev.task_run_id == task.id
    assert ev.drama_project_id == 99


@pytest.mark.asyncio
async def test_record_seed_assets_llm_usage_aggregates(db_session: AsyncSession) -> None:
    from app.services.drama.billing_util import record_seed_assets_llm_usage
    from app.services.drama.seed import SeedAssetsResult

    user = await make_user(db_session)
    task = await make_task(db_session, user, domain="drama", task_type="seed_assets")
    await db_session.commit()

    result = SeedAssetsResult(assets=[], llm_calls_props=1, prompts_refreshed=2)
    async with billing_scope(task.id):
        await record_seed_assets_llm_usage(db_session, user, 42, result)
    await db_session.commit()

    ev = (await db_session.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))).scalar_one()
    assert ev.billing_key == "llm_chat"
    assert ev.total_tokens > 0


@pytest.mark.asyncio
async def test_run_billed_ephemeral_sync_llm_creates_task_and_usage(db_session: AsyncSession) -> None:
    from app.services.billing import record_llm_chat_line, run_billed_ephemeral

    user = await make_user(db_session, balance_fen=50_000)

    async def _executor() -> str:
        await record_llm_chat_line(db_session, user_id=user.id, domain="kepu")
        return "ok"

    task, result = await run_billed_ephemeral(
        db_session,
        user,
        domain="kepu",
        task_type="content_expand",
        executor=_executor,
        payload={"mode": "theme"},
        commit=True,
    )
    assert result == "ok"
    assert task.task_type == "content_expand"
    assert task.billing_status == "settled"
    ev = (await db_session.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id))).scalar_one()
    assert ev.billing_key == "llm_chat"
    assert ev.settled is True


@pytest.mark.asyncio
async def test_estimate_new_llm_ephemeral_task_types(db_session: AsyncSession) -> None:
    from app.services.billing.estimates import estimate_task_fen

    user = await make_user(db_session)
    for domain, task_type in (
        ("kepu", "content_expand"),
        ("drama", "skill_optimize"),
        ("drama", "voice_prompt"),
    ):
        probe = TaskRun(domain=domain, task_type=task_type, requested_by=user.id, payload={})
        est = await estimate_task_fen(db_session, probe)
        assert est >= 1


@pytest.mark.asyncio
async def test_ensure_episode_outline_skips_llm_flag_when_titles_ready() -> None:
    from app.services.drama.agents import ensure_episode_outline

    existing = [
        {"episodeNumber": 1, "title": "开局", "body": "正文1"},
        {"episodeNumber": 2, "title": "转折", "body": ""},
    ]
    merged, used_llm = await ensure_episode_outline("创意", {"episodeCount": 2}, existing, 2)
    assert used_llm is False
    assert merged == existing
