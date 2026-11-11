"""Team reservations use the same estimate/freeze/actual settlement lifecycle."""
from __future__ import annotations
from datetime import UTC, datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models import UsageEvent
from app.models_tasks import TaskRun
from app.models_team_billing import TeamMonthlyUsage

SHANGHAI = timezone(timedelta(hours=8))
ACTIVE = ("pending", "leased", "running", "awaiting_poll", "awaiting_review", "cancel_requested")


def billing_period(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(SHANGHAI).strftime("%Y-%m")


async def monthly_usage(db: AsyncSession, team_id: int, user_id: int, period: str) -> TeamMonthlyUsage:
    # Wallet row must already be locked, serializing creation of the first monthly row.
    row = (await db.execute(select(TeamMonthlyUsage).where(TeamMonthlyUsage.team_id == team_id, TeamMonthlyUsage.user_id == user_id, TeamMonthlyUsage.period == period).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        row = TeamMonthlyUsage(team_id=team_id, user_id=user_id, period=period, spent_fen=0, reserved_fen=0)
        db.add(row)
        await db.flush()
    return row


async def check_team_budget(db: AsyncSession, task: TaskRun, estimate: int, *, count: int = 1, reserve: bool = False) -> dict:
    """锁定所有者钱包，跨团队及个人任务共享余额承诺；检查两级月额度。"""
    from app.services.teams.access import get_team
    from app.services.billing.settlement import _lock_user, pending_task_commitment_fen
    team, member = await get_team(db, int(task.team_id), int(task.requested_by), lock=True)
    wallet = await _lock_user(db, team.owner_user_id)
    if wallet is None:
        raise ValueError("团队所有者不存在")
    period = billing_period()
    task.billing_payer_user_id = team.owner_user_id
    task.billing_enabled_snapshot = bool(get_settings().billing_enabled)
    task.billing_period = period
    if not task.billing_enabled_snapshot or task.task_type == "episode_compose":
        task.billing_status = "skipped"
        return {"unit_estimate_fen": 0, "requested_total_fen": 0, "pending_commitment_fen": 0, "required_total_fen": 0, "balance_fen": int(wallet.balance_fen or 0)}
    additional = max(0, int(estimate)) * max(1, int(count))
    from . import wallet as funds
    if funds.enabled():
        await funds.ensure_can_spend(db, wallet)
    pending = await pending_task_commitment_fen(db, wallet.id, exclude_task_id=task.id)
    if int(wallet.balance_fen or 0) < pending + additional:
        raise ValueError("团队所有者余额不足，请联系所有者为个人账户充值")
    spent, reserved = (await db.execute(select(func.coalesce(func.sum(TeamMonthlyUsage.spent_fen), 0), func.coalesce(func.sum(TeamMonthlyUsage.reserved_fen), 0)).where(TeamMonthlyUsage.team_id == task.team_id, TeamMonthlyUsage.period == period))).one()
    if team.monthly_limit_fen is not None and (team.monthly_limit_fen == 0 or spent + reserved + additional > team.monthly_limit_fen):
        raise ValueError("已达到团队月度消费额度，请联系所有者调整额度")
    usage = await monthly_usage(db, int(task.team_id), int(task.requested_by), period)
    limit = member.monthly_limit_fen
    if limit is not None and (int(limit) == 0 or int(usage.spent_fen or 0) + int(usage.reserved_fen or 0) + additional > int(limit)):
        raise ValueError("已达到成员月度消费额度，请联系团队所有者调整额度")
    visible_pending = pending if team.owner_user_id == task.requested_by else int(usage.reserved_fen or 0)
    if reserve:
        usage.reserved_fen = int(usage.reserved_fen or 0) + additional
        task.billing_status = "reserved"
    return {"unit_estimate_fen": int(estimate), "requested_total_fen": additional, "pending_commitment_fen": visible_pending, "required_total_fen": visible_pending + additional, "balance_fen": int(wallet.balance_fen or 0)}


async def freeze_team_task(db: AsyncSession, task: TaskRun) -> int:
    """使用受理时的钱包；历史任务继续原钱包生命周期。"""
    if task.billing_payer_user_id is None:
        from app.services.billing.team_legacy import freeze_team_task as legacy_freeze
        return await legacy_freeze(db, task)
    if task.billing_status in ("frozen", "settled"):
        from . import wallet as funds, wallet_tasks
        if funds.enabled() and task.billing_status == "frozen" and not task.provider_task_id:
            await wallet_tasks.validate_task_funding(db, task.billing_payer_user_id, task.id)
        return int(task.billing_estimate_fen or 0)
    if task.billing_enabled_snapshot is False or task.billing_status == "skipped":
        task.billing_status = "skipped"
        task.billing_estimate_fen = 0
        await db.flush()
        return 0
    from app.services.billing.settlement import _lock_user
    wallet = await _lock_user(db, int(task.billing_payer_user_id))
    if wallet is None:
        raise ValueError("付款所有者不存在")
    need = int(task.billing_estimate_fen or 0)
    from . import wallet as funds, wallet_tasks
    if funds.enabled():
        await wallet_tasks.reserve_task(db, wallet.id, task.id, need, note=f"team:{task.team_id} actor:{task.requested_by}")
        task.billing_status = "frozen"
        await db.flush()
        return need
    if int(wallet.balance_fen or 0) < need:
        raise ValueError("团队所有者余额不足，请联系所有者为个人账户充值")
    wallet.frozen_fen = int(wallet.frozen_fen or 0) + need
    task.billing_status = "frozen"
    await owner_ledger(db, wallet, task, -need, "freeze", ref_type="task_run", ref_id=str(task.id), note=f"freeze:{task.domain}/{task.task_type}")
    await db.flush()
    return need


async def settle_team_task(db: AsyncSession, task: TaskRun) -> dict[str, int]:
    """按实际用量扣费退冻结，操作者与付款所有者分别留痕。"""
    if task.billing_payer_user_id is None:
        from app.services.billing.team_legacy import settle_team_task as legacy_settle
        return await legacy_settle(db, task)
    if task.billing_status == "settled":
        return {"charged": int(task.billing_charged_fen or 0), "refunded": int(task.billing_refunded_fen or 0)}
    events = list((await db.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id, UsageEvent.settled.is_(False)))).scalars().all())
    if events:
        from app.services.billing.newapi_bill import apply_newapi_bills
        # Match personal settlement: failed upstream reconciliation does not lose recorded costs.
        try:
            await apply_newapi_bills(events)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Team upstream reconciliation failed task=%s", task.id)
    from app.services.billing.settlement import _lock_user
    wallet = await _lock_user(db, int(task.billing_payer_user_id))
    if wallet is None:
        raise ValueError("付款所有者不存在")
    disabled = task.billing_enabled_snapshot is False or task.billing_status == "skipped"
    charged = 0 if disabled else sum(int(e.charge_fen or 0) for e in events)
    from app.services.billing.text_price import text_charge
    charged = text_charge(task, events, charged)
    for event in events:
        event.user_id = int(task.requested_by)
        event.team_id = int(task.team_id)
        event.billing_payer_user_id = task.billing_payer_user_id
        if disabled:
            event.charge_fen = 0
        event.settled = True
    reserved = int(task.billing_estimate_fen or 0)
    if not disabled:
        usage = await monthly_usage(db, int(task.team_id), int(task.requested_by), task.billing_period or billing_period(task.created_at))
        usage.reserved_fen = max(0, int(usage.reserved_fen or 0) - reserved)
        usage.spent_fen = int(usage.spent_fen or 0) + charged
    frozen = reserved if task.billing_status == "frozen" else 0
    from . import wallet as funds, wallet_tasks
    if funds.enabled() and not disabled:
        result = await wallet_tasks.settle_task(db, wallet.id, task.id, charged, note=f"team:{task.team_id} actor:{task.requested_by}")
        task.billing_status = "settled"
        task.billing_charged_fen, task.billing_refunded_fen = result["charged"], result["refunded"]
        await db.flush()
        return {"charged": result["charged"], "refunded": result["refunded"]}
    refund = max(0, frozen - charged)
    wallet.frozen_fen = max(0, int(wallet.frozen_fen or 0) - frozen)
    if refund:
        await owner_ledger(db, wallet, task, refund, "unfreeze", ref_type="task_run", ref_id=str(task.id), note="refund_unused_freeze")
    extra = max(0, charged - frozen)
    if extra:
        await owner_ledger(db, wallet, task, -extra, "settle", ref_type="task_run", ref_id=str(task.id), note="settle_overage" if frozen else "settle_direct")
    if not disabled:
        await owner_ledger(db, wallet, task, 0, "settle", ref_type="task_run", ref_id=str(task.id), note=f"charged={charged} freeze={frozen} refund={refund}")
    task.billing_status = "settled"
    task.billing_charged_fen = charged
    task.billing_refunded_fen = refund
    await db.flush()
    return {"charged": charged, "refunded": refund}


async def owner_ledger(db, wallet, task, delta, kind, *, ref_type, ref_id, note=""):
    """个人流水注明团队和实际操作成员。"""
    from app.services.billing.settlement import _ledger
    await _ledger(db, wallet, delta, kind, ref_type=ref_type, ref_id=ref_id, note=f"team:{task.team_id} actor:{task.requested_by} {note}")
