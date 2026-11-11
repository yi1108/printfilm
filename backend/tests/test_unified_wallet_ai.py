"""统一资金来源接入原 AI 生命周期，使用独立测试库及事务回滚。"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import get_settings
from app.models import UsageEvent, WalletLedger
from app.models_wallet import WalletAllocation
from app.services.billing import settlement
from app.services.billing import wallet as funding
from app.services.billing.unified_ai import validate_before_upstream
from conftest import make_task, make_user
from test_marketplace_coins import coin_ctx  # noqa: F401


def test_funding_error_keeps_http_status_and_machine_code():
    """任务接口不能把资金迁移失败的 503 降为普通参数错误。"""
    from app.services.billing.http import http_exception_for_value_error
    error = funding.WalletError("WALLET_MIGRATION_REQUIRED", "账户尚未核对", 503)
    response = http_exception_for_value_error(error)
    assert response.status_code == 503
    assert response.detail == {"code": "WALLET_MIGRATION_REQUIRED", "message": "账户尚未核对"}


@pytest_asyncio.fixture
async def funded(db_session, monkeypatch):
    """只在测试库建新增表，以可核对的 Apple 实付资金初始化零余额账户。"""
    from app.marketplace.app_settings import get_app_settings
    from app.services.billing.wallet_schema import apply_schema

    monkeypatch.setattr(get_settings(), "unified_wallet_enabled", True)
    monkeypatch.setattr(get_app_settings(), "apple_environment", "Production")
    connection = await db_session.connection()
    await connection.run_sync(apply_schema)
    user = await make_user(db_session, balance_fen=0)
    await funding.initialize_account(db_session, user)
    await funding.credit(db_session, user.id, 100, source_type="apple_transaction",
                         source_ref="Production:ai-test", amount_fen=90)
    monkeypatch.setattr(settlement, "estimate_task_fen", AsyncMock(return_value=80))
    monkeypatch.setattr("app.services.billing.alerts.process_billing_alerts_after_charge", AsyncMock())
    return db_session, user


async def charge(db, task, units):
    """记录任务的真实用量，不调用任何 AI 服务。"""
    db.add(UsageEvent(user_id=task.requested_by, task_run_id=task.id,
                      billing_key="seedream", charge_fen=units, settled=False))
    await db.flush()
    return await settlement.settle_task(db, task.id)


@pytest.mark.asyncio
async def test_personal_freeze_and_unused_return_keep_original_sources(funded):
    """冻结只扣一次，真实费用较低时按原来源退回未用额度。"""
    db, user = funded
    task = await make_task(db, user)
    assert await settlement.freeze_for_task(db, task) == 80
    assert await settlement.freeze_for_task(db, task) == 80
    assert (user.balance_fen, user.frozen_fen) == (20, 80)
    assert await charge(db, task, 60) == {"charged": 60, "refunded": 20}
    assert await settlement.settle_task(db, task.id) == {"charged": 60, "refunded": 20}
    assert (user.balance_fen, user.frozen_fen) == (40, 0)
    allocations = list((await db.execute(select(WalletAllocation).where(
        WalletAllocation.user_id == user.id, WalletAllocation.business_type == "ai_task",
        WalletAllocation.state == "consumed"))).scalars())
    assert sum(item.units for item in allocations) == 60
    assert sum(item.amount_fen for item in allocations) == 54


@pytest.mark.asyncio
async def test_apple_sandbox_setting_does_not_switch_ai_wallet(funded, monkeypatch):
    from app.marketplace.app_settings import get_app_settings
    db, user = funded
    monkeypatch.setattr(get_app_settings(), "apple_environment", "Sandbox")
    task = await make_task(db, user)
    assert await settlement.freeze_for_task(db, task) == 80
    assert await charge(db, task, 60) == {"charged": 60, "refunded": 20}
    assert (user.balance_fen, user.frozen_fen) == (40, 0)


@pytest.mark.asyncio
async def test_actual_ai_overrun_becomes_explicit_debt(funded):
    """实际费用超过原资金时不写负余额，差额成为可追溯欠费。"""
    db, user = funded
    task = await make_task(db, user)
    await settlement.freeze_for_task(db, task)
    assert await charge(db, task, 150) == {"charged": 150, "refunded": 0}
    summary = await funding.snapshot(db, user.id)
    assert (summary["balance_fen"], summary["frozen_fen"], summary["debt_fen"]) == (0, 0, 50)
    assert await settlement.settle_task(db, task.id) == {"charged": 150, "refunded": 0}
    assert (await funding.snapshot(db, user.id))["debt_fen"] == 50
    new_task = await make_task(db, user)
    with pytest.raises(ValueError, match="欠费"):
        await settlement.ensure_balance_for_task(db, user, new_task)


@pytest.mark.asyncio
async def test_refunded_prepaid_source_never_returns_as_available_balance(funded):
    """退款后在途任务按真实费用记欠费，未用冻结不能变回有效余额。"""
    db, user = funded
    task = await make_task(db, user)
    await settlement.freeze_for_task(db, task)
    await funding.revoke_source(db, user.id, "apple_transaction", "Production:ai-test")
    with pytest.raises(funding.WalletError):
        await settlement.freeze_for_task(db, task)
    # 已有上游任务号的重入仅用于继续轮询/下载，不阻止按实结算。
    task.provider_task_id = "already-created"
    await db.flush()
    assert await settlement.freeze_for_task(db, task) == 80
    assert await charge(db, task, 30) == {"charged": 30, "refunded": 0}
    summary = await funding.snapshot(db, user.id)
    assert (summary["balance_fen"], summary["frozen_fen"], summary["debt_fen"]) == (0, 0, 30)
    await funding.reverse_source(db, user.id, "apple_transaction", "Production:ai-test")
    summary = await funding.snapshot(db, user.id)
    assert (summary["balance_fen"], summary["debt_fen"]) == (70, 0)


@pytest.mark.asyncio
async def test_existing_frozen_source_is_rechecked_at_new_provider_call(funded):
    """每个新提交都复核，而不是只在最初冻结时检查余额。"""
    db, user = funded
    task = await make_task(db, user, status="running")
    task.started_at = datetime.now(UTC)
    await settlement.freeze_for_task(db, task)
    await validate_before_upstream(db, task.id)
    await funding.revoke_source(db, user.id, "apple_transaction", "Production:ai-test")
    with pytest.raises(funding.WalletError):
        await validate_before_upstream(db, task.id)


@pytest.mark.asyncio
async def test_disabled_billing_does_not_require_funded_task(funded, monkeypatch):
    """原全局关闭计费及免费内联调用保持原语义。"""
    db, user = funded
    monkeypatch.setattr(get_settings(), "billing_enabled", False)
    task = await make_task(db, user, status="running")
    assert await settlement.freeze_for_task(db, task) == 0
    await validate_before_upstream(db, task.id)
    assert await charge(db, task, 25) == {"charged": 25, "refunded": 0}
    assert (user.balance_fen, user.frozen_fen) == (100, 0)


@pytest.mark.asyncio
async def test_refund_notice_cancels_only_unstarted_reserved_task(funded):
    """可靠待办取消未启动任务，不把已退款预扣重新送回余额。"""
    from app.models_wallet import WalletTaskNotice
    from app.services.billing.unified_ai import reconcile_refunded_task_notices

    db, user = funded
    task = await make_task(db, user)
    await settlement.freeze_for_task(db, task)
    await funding.revoke_source(db, user.id, "apple_transaction", "Production:ai-test")
    assert await reconcile_refunded_task_notices(db) == 1
    assert (task.status, task.billing_status) == ("cancelled", "settled")
    assert (user.balance_fen, user.frozen_fen) == (0, 0)
    assert (await funding.snapshot(db, user.id))["debt_fen"] == 0
    notice = await db.scalar(select(WalletTaskNotice).where(WalletTaskNotice.task_id == task.id))
    assert notice.status == "done"


@pytest.mark.asyncio
async def test_signup_and_admin_grants_keep_zero_cash_sources(funded, monkeypatch):
    """注册、赠额和管理员扣减也经过共享资金服务，不伪造现金收入。"""
    import uuid
    from app.api.auth import register
    from app.api.admin.users import patch_user
    from app.models import User
    from app.models_wallet import WalletFundingLot
    from app.schemas import AdminUserPatch, RegisterRequest

    db, admin = funded
    admin.role = "admin"
    monkeypatch.setattr("app.api.auth.settings", get_settings())
    monkeypatch.setattr(get_settings(), "billing_signup_grant_fen", 50)
    address = f"unified-{uuid.uuid4().hex}@example.com"
    await register(RegisterRequest(email=address, password="unified-test-pass"), db=db)
    user = await db.scalar(select(User).where(User.email == address))
    assert user.balance_fen == 50
    await patch_user(user.id, AdminUserPatch(balance_delta_fen=100, balance_note="测试赠额"), admin=admin, db=db)
    await patch_user(user.id, AdminUserPatch(balance_delta_fen=-30, balance_note="测试调减"), admin=admin, db=db)
    assert user.balance_fen == 120
    lots = list((await db.execute(select(WalletFundingLot).where(WalletFundingLot.user_id == user.id))).scalars())
    assert {lot.source_type for lot in lots} == {"signup_grant", "admin_grant"}
    assert sum(lot.total_amount_fen for lot in lots) == 0
    allocations = await funding.consume(db, user.id, 20, business_type="video_unlock", business_ref="gift-funded-video")
    assert sum(item.amount_fen for item in allocations) == 0


@pytest.mark.asyncio
async def test_team_uses_owner_sources_and_keeps_member_budget(funded, monkeypatch):
    """统一的是付款来源，团队所有者归属及成员月额度仍保留。"""
    from app.models_team_billing import TeamMonthlyUsage
    from app.models_teams import Team, TeamMember
    from app.models_tasks import TaskRun

    db, owner = funded
    member = await make_user(db, balance_fen=0)
    team = Team(name="统一资金团队", owner_user_id=owner.id, monthly_limit_fen=1000)
    db.add(team)
    await db.flush()
    db.add_all([TeamMember(team_id=team.id, user_id=owner.id, role="owner"),
                TeamMember(team_id=team.id, user_id=member.id, role="member", monthly_limit_fen=500)])
    await db.flush()
    task = TaskRun(team_id=team.id, requested_by=member.id, domain="drama", task_type="asset_image",
                    status="pending", billing_status="none", payload={})
    task.billing_estimate_fen = await settlement.ensure_balance_for_task(db, member, task)
    db.add(task)
    await db.flush()
    assert task.billing_payer_user_id == owner.id
    await settlement.freeze_for_task(db, task)
    assert await charge(db, task, 60) == {"charged": 60, "refunded": 20}
    assert (owner.balance_fen, owner.frozen_fen, member.balance_fen) == (40, 0, 0)
    usage = await db.scalar(select(TeamMonthlyUsage).where(TeamMonthlyUsage.team_id == team.id,
                                                        TeamMonthlyUsage.user_id == member.id))
    assert (usage.spent_fen, usage.reserved_fen) == (60, 0)
    ledger = list((await db.execute(select(WalletLedger).where(WalletLedger.user_id == owner.id))).scalars())
    assert sum(item.delta_fen for item in ledger) == 40
    assert all(f"team:{team.id} actor:{member.id}" in item.note
               for item in ledger if item.kind in {"freeze", "settle"})


@pytest.mark.asyncio
async def test_http_guard_blocks_post_but_does_not_block_existing_poll(monkeypatch):
    """资金校验失败不能被日志容错吞掉，已有请求的 GET 轮询继续进行。"""
    from types import SimpleNamespace
    from app.services.billing.context import billing_scope
    from app.services.tasks import upstream

    guard = AsyncMock(side_effect=ValueError("账号存在欠费"))
    monkeypatch.setattr("app.services.billing.unified_ai.guard_upstream_submission", guard)
    monkeypatch.setattr(upstream, "_safe_record", AsyncMock())
    response = SimpleNamespace(status_code=200, headers={}, json=lambda: {"status": "running"})
    client = SimpleNamespace(post=AsyncMock(return_value=response), get=AsyncMock(return_value=response))
    async with billing_scope(101):
        with pytest.raises(ValueError, match="欠费"):
            await upstream.observed_request(client, "POST", "https://provider.test/v1/videos", json={})
        assert await upstream.observed_request(client, "GET", "https://provider.test/v1/videos/existing") is response
    client.post.assert_not_awaited()
    client.get.assert_awaited_once()
    guard.assert_awaited_once_with(101)


@pytest.mark.asyncio
async def test_dispatch_authorization_does_not_wait_on_inline_task_row_lock(coin_ctx, monkeypatch):
    """内联任务持有自己的 TaskRun 锁时，新请求资金复核不能等待自己。"""
    import asyncio
    from app.models_tasks import TaskRun
    from app.services.billing.unified_ai import guard_upstream_submission

    ctx = coin_ctx
    await funding.credit(ctx.db, ctx.buyer.id, 100, source_type="web_order", source_ref="guard-lock", amount_fen=100)
    task = TaskRun(requested_by=ctx.buyer.id, domain="drama", task_type="agent_chat",
                    status="running", billing_status="frozen", billing_estimate_fen=80)
    ctx.db.add(task)
    await ctx.db.flush()
    await funding.reserve_task(ctx.db, ctx.buyer.id, task.id, 80)
    await ctx.db.commit()
    monkeypatch.setattr("app.database.AsyncSessionLocal", ctx.factory)
    async with ctx.factory() as inline_db:
        locked = await inline_db.scalar(select(TaskRun).where(TaskRun.id == task.id).with_for_update())
        locked.provider_status = "submitting"
        await inline_db.flush()
        await asyncio.wait_for(guard_upstream_submission(task.id), timeout=2)
        await inline_db.rollback()
