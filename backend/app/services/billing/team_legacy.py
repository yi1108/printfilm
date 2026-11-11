"""Team reservations use the same estimate/freeze/actual settlement lifecycle."""
from __future__ import annotations
from datetime import UTC, datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models import UsageEvent
from app.models_tasks import TaskRun
from app.models_team_billing import TeamMonthlyUsage, TeamWallet, TeamWalletLedger

SHANGHAI = timezone(timedelta(hours=8))
ACTIVE = ("pending", "leased", "running", "awaiting_poll", "awaiting_review", "cancel_requested")


def billing_period(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(SHANGHAI).strftime("%Y-%m")


async def lock_wallet(db: AsyncSession, team_id: int) -> TeamWallet:
    wallet = (await db.execute(select(TeamWallet).where(TeamWallet.team_id == team_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if wallet is None:
        raise ValueError("团队钱包不存在")
    return wallet


async def monthly_usage(db: AsyncSession, team_id: int, user_id: int, period: str) -> TeamMonthlyUsage:
    # Wallet row must already be locked, serializing creation of the first monthly row.
    row = (await db.execute(select(TeamMonthlyUsage).where(TeamMonthlyUsage.team_id == team_id, TeamMonthlyUsage.user_id == user_id, TeamMonthlyUsage.period == period).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        row = TeamMonthlyUsage(team_id=team_id, user_id=user_id, period=period, spent_fen=0, reserved_fen=0)
        db.add(row)
        await db.flush()
    return row


async def ledger(db: AsyncSession, wallet: TeamWallet, actor: int, delta: int, kind: str, *, ref_type: str, ref_id: str, note: str = "") -> None:
    wallet.balance_fen = int(wallet.balance_fen or 0) + int(delta)
    db.add(TeamWalletLedger(team_id=wallet.team_id, actor_user_id=actor, delta_fen=int(delta), balance_after_fen=wallet.balance_fen, kind=kind, ref_type=ref_type, ref_id=ref_id, note=note[:255]))


async def freeze_team_task(db: AsyncSession, task: TaskRun) -> int:
    if task.billing_status in ("frozen", "settled"):
        return int(task.billing_estimate_fen or 0)
    if task.billing_enabled_snapshot is False or task.billing_status == "skipped":
        task.billing_status = "skipped"
        task.billing_estimate_fen = 0
        await db.flush()
        return 0
    wallet = await lock_wallet(db, int(task.team_id))
    need = int(task.billing_estimate_fen or 0)
    if int(wallet.balance_fen or 0) < need:
        raise ValueError("团队余额不足，请联系所有者充值")
    wallet.frozen_fen = int(wallet.frozen_fen or 0) + need
    task.billing_status = "frozen"
    await ledger(db, wallet, int(task.requested_by), -need, "freeze", ref_type="task_run", ref_id=str(task.id), note=f"freeze:{task.domain}/{task.task_type}")
    await db.flush()
    return need


async def settle_team_task(db: AsyncSession, task: TaskRun) -> dict[str, int]:
    if task.billing_status == "settled":
        return {"charged": int(task.billing_charged_fen or 0), "refunded": int(task.billing_refunded_fen or 0)}
    wallet = await lock_wallet(db, int(task.team_id))
    events = list((await db.execute(select(UsageEvent).where(UsageEvent.task_run_id == task.id, UsageEvent.settled.is_(False)))).scalars().all())
    if events:
        from app.services.billing.newapi_bill import apply_newapi_bills
        # Match personal settlement: failed upstream reconciliation does not lose recorded costs.
        try:
            await apply_newapi_bills(events)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Team upstream reconciliation failed task=%s", task.id)
    disabled = task.billing_enabled_snapshot is False or task.billing_status == "skipped"
    charged = 0 if disabled else sum(int(e.charge_fen or 0) for e in events)
    from app.services.billing.text_price import text_charge
    charged = text_charge(task, events, charged)
    for event in events:
        event.user_id = int(task.requested_by)
        event.team_id = int(task.team_id)
        if disabled:
            event.charge_fen = 0
        event.settled = True
    reserved = int(task.billing_estimate_fen or 0)
    if not disabled:
        usage = await monthly_usage(db, int(task.team_id), int(task.requested_by), task.billing_period or billing_period(task.created_at))
        usage.reserved_fen = max(0, int(usage.reserved_fen or 0) - reserved)
        usage.spent_fen = int(usage.spent_fen or 0) + charged
    frozen = reserved if task.billing_status == "frozen" else 0
    refund = max(0, frozen - charged)
    wallet.frozen_fen = max(0, int(wallet.frozen_fen or 0) - frozen)
    if refund:
        await ledger(db, wallet, int(task.requested_by), refund, "unfreeze", ref_type="task_run", ref_id=str(task.id), note="refund_unused_freeze")
    extra = max(0, charged - frozen)
    if extra:
        await ledger(db, wallet, int(task.requested_by), -extra, "settle", ref_type="task_run", ref_id=str(task.id), note="settle_overage" if frozen else "settle_direct")
    if not disabled:
        await ledger(db, wallet, int(task.requested_by), 0, "settle", ref_type="task_run", ref_id=str(task.id), note=f"charged={charged} freeze={frozen} refund={refund}")
    task.billing_status = "settled"
    task.billing_charged_fen = charged
    task.billing_refunded_fen = refund
    await db.flush()
    return {"charged": charged, "refunded": refund}
