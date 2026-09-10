# -*- coding: utf-8 -*-
"""任务级预扣与结算。"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import UsageEvent, User, WalletLedger
from app.models_tasks import TaskRun
from app.services.billing.estimates import estimate_task_fen

logger = logging.getLogger(__name__)

# 仍占用余额承诺、尚未预扣冻结的进行中任务
_PENDING_BILLING_TASK_STATUSES = frozenset(
    {
        "pending",
        "leased",
        "running",
        "awaiting_poll",
        "awaiting_review",
        "cancel_requested",
    }
)


def billing_active(user: User | None = None, settings: Settings | None = None) -> bool:
    """全局计费开关；user 参数保留兼容调用方，不再按用户跳过扣费。"""
    _ = user
    s = settings or get_settings()
    return bool(s.billing_enabled)


async def _ledger(
    db: AsyncSession,
    user: User,
    delta_fen: int,
    kind: str,
    *,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> None:
    user.balance_fen = int(user.balance_fen or 0) + int(delta_fen)
    db.add(
        WalletLedger(
            user_id=user.id,
            delta_fen=int(delta_fen),
            balance_after=int(user.balance_fen),
            kind=kind,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note[:255],
        )
    )


async def _lock_user(db: AsyncSession, user_id: int) -> User | None:
    """行锁用户钱包，避免并发预扣/结算透支；populate_existing 防止会话内过期余额。"""
    return (
        await db.execute(
            select(User)
            .where(User.id == int(user_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _lock_task(db: AsyncSession, task_id: int) -> TaskRun | None:
    """行锁 TaskRun，保证结算/预扣幂等；populate_existing 防止会话内过期 billing_status。"""
    return (
        await db.execute(
            select(TaskRun)
            .where(TaskRun.id == int(task_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def pending_task_commitment_fen(
    db: AsyncSession,
    user_id: int,
    *,
    exclude_task_id: int | None = None,
) -> int:
    """汇总用户进行中、尚未预扣冻结的任务估算占用（分）。"""
    stmt = select(TaskRun).where(
        TaskRun.requested_by == int(user_id),
        TaskRun.billing_status == "none",
        TaskRun.status.in_(_PENDING_BILLING_TASK_STATUSES),
    )
    if exclude_task_id is not None:
        stmt = stmt.where(TaskRun.id != int(exclude_task_id))
    rows = list((await db.execute(stmt)).scalars().all())
    total = 0
    for row in rows:
        est = int(row.billing_estimate_fen or 0)
        if est <= 0:
            est = await estimate_task_fen(db, row)
        total += est
    return total


async def ensure_balance_for_task(db: AsyncSession, user: User, task: TaskRun) -> int:
    """入队前同步校验余额（含排队中未冻结估算），不足抛 ValueError；返回本任务估算分。"""
    if not billing_active(user):
        return 0
    locked = await _lock_user(db, int(user.id))
    if locked is None:
        raise ValueError("用户不存在")
    # 同步调用方持有的 user 对象余额
    user.balance_fen = int(locked.balance_fen or 0)
    user.frozen_fen = int(locked.frozen_fen or 0)
    need = await estimate_task_fen(db, task)
    pending = await pending_task_commitment_fen(db, int(user.id))
    available = int(locked.balance_fen or 0)
    required = pending + need
    if available < required:
        if pending > 0:
            raise ValueError(
                f"余额不足：本次需要 ¥{need/100:.2f}（含排队中 ¥{pending/100:.2f}），"
                f"当前 ¥{available/100:.2f}，请先充值"
            )
        raise ValueError(f"余额不足：需要 ¥{need/100:.2f}，当前 ¥{available/100:.2f}，请先充值")
    return need


async def ensure_balance_for_task_batch(
    db: AsyncSession,
    user: User,
    task: TaskRun,
    count: int,
) -> dict[str, int]:
    """批量入队前校验：pending + unit*count。不足抛 ValueError。"""
    if not billing_active(user):
        return {"unit_estimate_fen": 0, "required_total_fen": 0}
    qty = max(1, int(count))
    locked = await _lock_user(db, int(user.id))
    if locked is None:
        raise ValueError("用户不存在")
    user.balance_fen = int(locked.balance_fen or 0)
    user.frozen_fen = int(locked.frozen_fen or 0)
    unit = await estimate_task_fen(db, task)
    pending = await pending_task_commitment_fen(db, int(user.id))
    additional = unit * qty
    required = pending + additional
    available = int(locked.balance_fen or 0)
    if available < required:
        raise ValueError(
            f"余额不足：批量生成 {qty} 项需 ¥{additional/100:.2f}"
            f"（含排队中 ¥{pending/100:.2f}），当前 ¥{available/100:.2f}，请先充值"
        )
    return {
        "unit_estimate_fen": unit,
        "pending_commitment_fen": pending,
        "requested_total_fen": additional,
        "required_total_fen": required,
        "balance_fen": available,
    }


async def freeze_for_task(db: AsyncSession, task: TaskRun) -> int:
    """任务开始前预扣估算；余额不足抛 ValueError。已 frozen 时幂等返回原估算。"""
    locked_task = await _lock_task(db, int(task.id))
    if not locked_task:
        return 0
    # 回写到调用方持有的 task 引用
    if locked_task is not task:
        task.billing_status = locked_task.billing_status
        task.billing_estimate_fen = locked_task.billing_estimate_fen
    if task.billing_status == "frozen":
        return int(task.billing_estimate_fen or 0)

    user = await _lock_user(db, int(task.requested_by))
    if not user or not billing_active(user):
        task.billing_status = "skipped"
        task.billing_estimate_fen = 0
        await db.flush()
        return 0
    need = await estimate_task_fen(db, task)
    available = int(user.balance_fen or 0)
    if available < need:
        raise ValueError(f"余额不足：需要 ¥{need/100:.2f}，当前 ¥{available/100:.2f}，请先充值")
    # 仅通过 _ledger 扣余额，避免双重扣款
    user.frozen_fen = int(user.frozen_fen or 0) + need
    task.billing_estimate_fen = need
    task.billing_status = "frozen"
    await _ledger(
        db,
        user,
        -need,
        "freeze",
        ref_type="task_run",
        ref_id=str(task.id),
        note=f"freeze:{task.domain}/{task.task_type}",
    )
    await db.flush()
    return need


async def settle_task(db: AsyncSession, task_id: int) -> dict[str, int]:
    """任务结束时按 usage_events 结算，多退少补冻结额。"""
    task = await _lock_task(db, task_id)
    if not task:
        return {"charged": 0, "refunded": 0}
    if task.billing_status == "settled":
        return {
            "charged": int(task.billing_charged_fen or 0),
            "refunded": int(task.billing_refunded_fen or 0),
        }

    # 钱包侧幂等：已有 unfreeze/settle 流水则只对齐状态，禁止二次退还
    if task.billing_status == "frozen":
        prior = (
            await db.execute(
                select(WalletLedger.id)
                .where(
                    WalletLedger.ref_type == "task_run",
                    WalletLedger.ref_id == str(task_id),
                    WalletLedger.kind.in_(("unfreeze", "settle")),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if prior is not None:
            result = await db.execute(
                select(UsageEvent).where(
                    UsageEvent.task_run_id == task_id,
                    UsageEvent.settled.is_(False),
                )
            )
            for e in result.scalars().all():
                e.settled = True
            task.billing_status = "settled"
            await db.flush()
            return {
                "charged": int(task.billing_charged_fen or 0),
                "refunded": int(task.billing_refunded_fen or 0),
            }

    result = await db.execute(
        select(UsageEvent).where(
            UsageEvent.task_run_id == task_id,
            UsageEvent.settled.is_(False),
        )
    )
    events = list(result.scalars().all())
    # 用量已结但状态仍 frozen（异常中断）：按已落账实扣对齐，禁止把整笔预扣当退款
    if (
        task.billing_status == "frozen"
        and not events
        and int(task.billing_charged_fen or 0) > 0
    ):
        task.billing_status = "settled"
        await db.flush()
        return {
            "charged": int(task.billing_charged_fen or 0),
            "refunded": int(task.billing_refunded_fen or 0),
        }
    if task.billing_status == "skipped" and not events:
        # 全局关闭计费且无用量：结算完成，统一标 settled 便于管理端展示
        task.billing_status = "settled"
        task.billing_charged_fen = int(task.billing_charged_fen or 0)
        await db.flush()
        return {
            "charged": int(task.billing_charged_fen or 0),
            "refunded": 0,
        }

    charged = sum(int(e.charge_fen or 0) for e in events)
    for e in events:
        e.settled = True

    # 全局关闭计费：标记用量已结算，不动钱包，任务标 settled
    if task.billing_status == "skipped":
        task.billing_charged_fen = charged
        task.billing_status = "settled"
        await db.flush()
        return {"charged": charged, "refunded": 0}

    user = await _lock_user(db, int(task.requested_by)) if task.requested_by else None
    if not user or task.billing_status != "frozen":
        # 非 frozen（如 none）但已有用量：只落账用量，不碰钱包
        task.billing_charged_fen = charged
        if events:
            task.billing_status = "settled"
        await db.flush()
        if charged > 0 and user:
            from app.services.billing.alerts import process_billing_alerts_after_charge

            await process_billing_alerts_after_charge(db, user, charged_fen=charged)
        return {"charged": charged, "refunded": 0}

    frozen_for_task = int(task.billing_estimate_fen or 0)
    user.frozen_fen = max(0, int(user.frozen_fen or 0) - frozen_for_task)
    extra = max(0, charged - frozen_for_task)
    refund = max(0, frozen_for_task - charged)

    if extra > 0:
        logger.warning(
            "settle overage user=%s task=%s extra_fen=%s balance=%s",
            user.id,
            task_id,
            extra,
            user.balance_fen,
        )
        await _ledger(
            db,
            user,
            -extra,
            "settle",
            ref_type="task_run",
            ref_id=str(task_id),
            note="settle_overage",
        )
    if refund > 0:
        await _ledger(
            db,
            user,
            refund,
            "unfreeze",
            ref_type="task_run",
            ref_id=str(task_id),
            note="refund_unused_freeze",
        )

    task.billing_charged_fen = charged
    task.billing_refunded_fen = refund
    task.billing_status = "settled"
    await _ledger(
        db,
        user,
        0,
        "settle",
        ref_type="task_run",
        ref_id=str(task_id),
        note=f"charged={charged} freeze={frozen_for_task} refund={refund}",
    )
    await db.flush()
    if charged > 0 and user:
        from app.services.billing.alerts import process_billing_alerts_after_charge

        await process_billing_alerts_after_charge(db, user, charged_fen=charged)
    return {"charged": charged, "refunded": refund}


async def settle_project(db: AsyncSession, project_id: int) -> dict[str, int]:
    """兼容旧科普项目结算：按 project_id 汇总未结算 usage（无 task_run_id 的历史行）。"""
    from app.models import Project

    project = await db.get(Project, project_id)
    if not project:
        return {"charged": 0, "refunded": 0}
    user = await _lock_user(db, int(project.user_id))
    result = await db.execute(
        select(UsageEvent).where(
            UsageEvent.project_id == project_id,
            UsageEvent.settled.is_(False),
        )
    )
    events = list(result.scalars().all())
    charged = sum(int(e.charge_fen or 0) for e in events)
    for e in events:
        e.settled = True

    if not user or not billing_active(user):
        await db.flush()
        return {"charged": 0, "refunded": 0}

    frozen_before = int(user.frozen_fen or 0)
    extra = max(0, charged - frozen_before)
    refund = max(0, frozen_before - charged)
    user.frozen_fen = 0

    if extra > 0:
        await _ledger(
            db,
            user,
            -extra,
            "settle",
            ref_type="project",
            ref_id=str(project_id),
            note="settle_overage",
        )
    if refund > 0:
        await _ledger(
            db,
            user,
            refund,
            "unfreeze",
            ref_type="project",
            ref_id=str(project_id),
            note="refund_unused_freeze",
        )
    await _ledger(
        db,
        user,
        0,
        "settle",
        ref_type="project",
        ref_id=str(project_id),
        note=f"charged={charged} refund={refund}",
    )
    await db.flush()
    if charged > 0 and user:
        from app.services.billing.alerts import process_billing_alerts_after_charge

        await process_billing_alerts_after_charge(db, user, charged_fen=charged)
    return {"charged": charged, "refunded": refund}


async def credit_topup(
    db: AsyncSession,
    user: User,
    credit_fen: int,
    *,
    ref_type: str,
    ref_id: str,
    note: str = "",
) -> None:
    locked = await _lock_user(db, int(user.id))
    target = locked or user
    await _ledger(db, target, int(credit_fen), "topup", ref_type=ref_type, ref_id=ref_id, note=note)
    if locked is not None and locked is not user:
        user.balance_fen = locked.balance_fen
        user.frozen_fen = locked.frozen_fen
    await db.flush()


async def close_expired_pending_orders(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    out_trade_no: str | None = None,
) -> int:
    from datetime import datetime, timezone

    from app.models import Order

    now = datetime.now(timezone.utc)
    stmt = select(Order).where(Order.status == "pending")
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    if out_trade_no is not None:
        stmt = stmt.where(Order.out_trade_no == out_trade_no)
    rows = (await db.execute(stmt)).scalars().all()
    closed = 0
    for order in rows:
        created = order.created_at
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created).total_seconds() < 300:
            continue
        order.status = "closed"
        closed += 1
    if closed:
        await db.commit()
    return closed


async def settle_usage_charge(
    db: AsyncSession,
    user: User,
    charge_fen: int,
    *,
    ref_type: str = "api",
    ref_id: str = "",
) -> None:
    """即时扣费（已由 task 结算覆盖时仅作兼容）。"""
    if not billing_active(user):
        return
    need = max(0, int(charge_fen))
    if need <= 0:
        return
    locked = await _lock_user(db, int(user.id))
    target = locked or user
    available = int(target.balance_fen or 0)
    if available < need:
        raise ValueError(f"余额不足：需要 ¥{need / 100:.2f}，当前 ¥{available / 100:.2f}，请先充值")
    await _ledger(
        db,
        target,
        -need,
        "settle",
        ref_type=ref_type,
        ref_id=ref_id,
        note="api_usage",
    )
    if locked is not None and locked is not user:
        user.balance_fen = locked.balance_fen
        user.frozen_fen = locked.frozen_fen
    await db.flush()
    from app.services.billing.alerts import process_billing_alerts_after_charge

    await process_billing_alerts_after_charge(db, target, charged_fen=need)


async def get_task_usage_lines(db: AsyncSession, task_id: int) -> list[UsageEvent]:
    result = await db.execute(
        select(UsageEvent)
        .where(UsageEvent.task_run_id == task_id)
        .order_by(UsageEvent.id.asc())
    )
    return list(result.scalars().all())


async def get_task_billing_summary(db: AsyncSession, task_id: int) -> dict[str, Any]:
    task = await db.get(TaskRun, task_id)
    if not task:
        return {}
    lines = await get_task_usage_lines(db, task_id)
    return {
        "billing_status": task.billing_status,
        "billing_estimate_fen": int(task.billing_estimate_fen or 0),
        "billing_charged_fen": int(task.billing_charged_fen or 0),
        "billing_refunded_fen": int(task.billing_refunded_fen or 0),
        "usage_count": len(lines),
        "total_tokens": sum(int(l.total_tokens or 0) for l in lines),
        "lines": lines,
    }
