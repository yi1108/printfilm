"""统一钱包与 AI 运行时的边界：欠费检查和上游调用前的资金复核。"""
from __future__ import annotations

from app.services.billing import wallet as funding


async def ensure_paid_account(db, user_id: int) -> dict:
    """已冻结金额不属于可用余额；存在欠费时禁止受理新的付费任务。"""
    summary = await funding.snapshot(db, int(user_id))
    if int(summary["debt_fen"]) > 0:
        raise funding.WalletError("WALLET_DEBT_OUTSTANDING", "账号存在欠费，请先充值补齐后再使用付费功能")
    if summary.get("refund_pending"):
        raise funding.WalletError("WALLET_REFUND_PENDING", "退款关联任务正在结算，请稍后再使用付费功能")
    return summary


async def validate_before_upstream(db, task_id: int) -> None:
    """只读任务归属后校验资金，不锁任务或影响已有请求的轮询。"""
    if not funding.enabled():
        return
    from app.models_tasks import TaskRun
    from app.services.billing.settlement import billing_active

    # 内联调用方可能仍持任务行锁；独立授权事务不能反过来等待同一行。
    # 任务付款归属在受理时冻结，本检查不修改 TaskRun，只获取钱包锁。
    task = await db.get(TaskRun, int(task_id), populate_existing=True)
    if task is None:
        raise ValueError("计费任务不存在，不能发起新的生成调用")
    if task.billing_status == "skipped" or task.billing_enabled_snapshot is False:
        return
    if task.team_id is not None and task.billing_payer_user_id is None:
        # 历史团队钱包不属于统一个人余额，保持原生命周期。
        return
    if not billing_active() and task.billing_status != "frozen":
        return
    if task.cancel_requested or task.status in {"cancelled", "failed", "succeeded"}:
        raise ValueError("任务已停止，不能发起新的生成调用")
    payer = task.billing_payer_user_id if task.team_id is not None else task.requested_by
    if payer is None or task.billing_status != "frozen":
        raise ValueError("任务尚未完成预扣，不能发起新的生成调用")
    await funding.validate_task_funding(db, int(payer), int(task.id))


async def guard_upstream_submission(task_id: int) -> None:
    """独立短事务释放资金锁后才允许 HTTP 调用，退款后未提交的调用及时阻断。"""
    if not funding.enabled():
        return
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await validate_before_upstream(db, int(task_id))
        await db.commit()


async def reconcile_refunded_task_notices(db, *, limit: int = 100) -> int:
    """持久退款待办逐项短事务处理；已在途请求继续按实际用量收尾。"""
    if not funding.enabled():
        return 0
    from datetime import UTC, datetime
    from sqlalchemy import or_, select
    from app.models_tasks import TaskRun
    from app.models_wallet import WalletTaskNotice
    from app.services.billing.settlement import _lock_task, settle_task
    from app.services.tasks.service import append_task_event

    ids = list((await db.execute(select(WalletTaskNotice.id).outerjoin(TaskRun,
        TaskRun.id == WalletTaskNotice.task_id).where(WalletTaskNotice.status == "pending",
        or_(TaskRun.id.is_(None), TaskRun.billing_status == "settled",
            TaskRun.status.in_(("pending", "leased", "succeeded", "failed", "cancelled"))))
        .order_by(WalletTaskNotice.id).limit(limit))).scalars())
    processed = 0
    for notice_id in ids:
        notice = await db.get(WalletTaskNotice, notice_id, populate_existing=True)
        if notice is None or notice.status != "pending":
            continue
        task = await _lock_task(db, int(notice.task_id))
        if task is None or task.billing_status == "settled":
            notice.status = "done"
            processed += 1
        elif task.status in {"succeeded", "failed", "cancelled"}:
            await settle_task(db, int(task.id))
            notice.status = "done"
            processed += 1
        else:
            try:
                await funding.validate_task_funding(db, int(notice.user_id), int(task.id))
            except funding.WalletError:
                # 只有未开始的任务可零用量取消；运行中的网络请求不能假定未消耗。
                if task.status in {"pending", "leased"} and task.started_at is None and not task.provider_task_id:
                    task.cancel_requested = True
                    task.status = "cancelled"
                    task.error_code = "wallet_source_refunded"
                    task.error_message = "预扣资金已退款，任务未启动并已停止"
                    task.finished_at = datetime.now(UTC)
                    task.next_action_at = None
                    task.lease_until = None
                    await append_task_event(db, int(task.id), event_type="task.cancelled",
                        status="cancelled", phase=task.current_step_key, message=task.error_message)
                    await settle_task(db, int(task.id))
                    notice.status = "done"
                    processed += 1
            else:
                # 退款已撤销且预扣重新有效，不再重复处理旧待办。
                notice.status = "done"
                processed += 1
        # 不可持有上一用户的钱包锁再去获取下一任务锁。
        await db.commit()
    return processed
