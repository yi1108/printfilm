# -*- coding: utf-8 -*-
"""额度告警：用户消费里程碑弹窗 + 平台总费用邮件。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import BillingAlertNotification, UsageEvent, User
from app.models_settings import AppSettings
from app.services.admin.stats import _usage_window_totals
from app.services.email import send_email
from app.services.model_settings import _decrypt_flat_config, _encrypt_flat_config, _settings_to_dict

logger = logging.getLogger(__name__)


def _fen_to_yuan(fen: int) -> str:
    return f"¥{int(fen) / 100:.2f}"


async def _user_total_charge_fen(db: AsyncSession, user_id: int) -> int:
    row = (
        await db.execute(
            select(func.coalesce(func.sum(UsageEvent.charge_fen), 0)).where(
                UsageEvent.user_id == int(user_id),
                UsageEvent.settled.is_(True),
            )
        )
    ).scalar_one()
    return int(row or 0)


def _period_key(period: str, now: datetime | None = None) -> tuple[str, datetime | None]:
    """返回统计周期键与 since 时间。"""
    current = now or datetime.now(timezone.utc)
    p = (period or "monthly").strip().lower()
    if p == "daily":
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.date().isoformat(), start
    if p == "all_time":
        return "all_time", None
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m"), start


async def _get_or_create_settings_row(db: AsyncSession) -> AppSettings:
    row = (await db.execute(select(AppSettings).where(AppSettings.id == "default"))).scalar_one_or_none()
    if row:
        return row
    row = AppSettings(id="default", config_json={"flat": _settings_to_dict()})
    db.add(row)
    await db.flush()
    return row


async def _read_admin_alert_dedup(db: AsyncSession) -> tuple[str, int]:
    row = await _get_or_create_settings_row(db)
    flat = _decrypt_flat_config(dict(row.config_json or {}))
    return (
        str(flat.get("billing_admin_cost_alert_last_period_key") or ""),
        int(flat.get("billing_admin_cost_alert_last_level") or 0),
    )


async def _persist_flat_keys(db: AsyncSession, updates: dict[str, Any]) -> None:
    """写入 app_settings.flat 运行时去重字段。"""
    row = await _get_or_create_settings_row(db)
    config = dict(row.config_json or {})
    flat = _decrypt_flat_config(config)
    flat.update(updates)
    config["flat"] = _encrypt_flat_config(flat)
    row.config_json = config
    await db.flush()


async def _resolve_admin_recipients(db: AsyncSession, settings: Settings) -> list[str]:
    raw = str(settings.billing_admin_cost_alert_emails or "").strip()
    emails = [e.strip() for e in raw.split(",") if e.strip()]
    if emails:
        return emails
    rows = (
        await db.execute(
            select(User.email).where(User.role == "admin", User.email.is_not(None)).order_by(User.id.asc())
        )
    ).all()
    return [str(r[0]).strip() for r in rows if r[0]]


async def process_user_milestone_alert(
    db: AsyncSession,
    user: User,
    *,
    settings: Settings | None = None,
) -> list[BillingAlertNotification]:
    """结算后检查用户累计扣费是否跨越里程碑，写入待弹窗通知。"""
    s = settings or get_settings()
    if not s.billing_user_alert_enabled:
        return []
    interval = int(s.billing_user_alert_interval_fen or 0)
    if interval <= 0:
        return []

    total = await _user_total_charge_fen(db, int(user.id))
    last = int(getattr(user, "billing_alert_last_milestone_fen", 0) or 0)
    created: list[BillingAlertNotification] = []

    while last + interval <= total:
        last += interval
        note = BillingAlertNotification(
            user_id=int(user.id),
            kind="user_milestone",
            title="消费提醒",
            message=(
                f"您已累计消费 {_fen_to_yuan(last)}。"
                f"当前累计扣费 {_fen_to_yuan(total)}，请注意账户余额。"
            ),
            milestone_fen=last,
        )
        db.add(note)
        created.append(note)

    if created:
        user.billing_alert_last_milestone_fen = last
        await db.flush()
    return created


async def process_admin_cost_alert(
    db: AsyncSession,
    *,
    settings: Settings | None = None,
) -> bool:
    """平台总上游成本达阈值时发邮件给管理员（按周期去重）。"""
    s = settings or get_settings()
    if not s.billing_admin_cost_alert_enabled:
        return False
    threshold = int(s.billing_admin_cost_alert_threshold_fen or 0)
    if threshold <= 0:
        return False

    period = str(s.billing_admin_cost_alert_period or "monthly")
    period_key, since = _period_key(period)
    totals = await _usage_window_totals(db, since=since)
    cost_fen = int(totals.get("cost_fen") or 0)
    if cost_fen < threshold:
        return False

    stored_period, last_level = await _read_admin_alert_dedup(db)
    if stored_period != period_key:
        last_level = 0

    target_level = cost_fen // threshold
    if target_level <= last_level:
        return False

    recipients = await _resolve_admin_recipients(db, s)
    if not recipients:
        logger.warning("admin cost alert skipped: no recipients cost_fen=%s", cost_fen)
        return False

    subject = f"[{s.app_name}] 平台费用告警"
    body = (
        f"统计周期：{period_key}\n"
        f"累计上游成本：{_fen_to_yuan(cost_fen)}\n"
        f"告警阈值：每 {_fen_to_yuan(threshold)}\n"
        f"当前档位：{target_level}\n\n"
        f"请登录管理后台查看用量详情。"
    )
    sent = await send_email(to_addrs=recipients, subject=subject, body=body, settings=s)
    if not sent:
        return False

    await _persist_flat_keys(
        db,
        {
            "billing_admin_cost_alert_last_period_key": period_key,
            "billing_admin_cost_alert_last_level": target_level,
        },
    )
    logger.info(
        "admin cost alert sent period=%s level=%s cost_fen=%s recipients=%s",
        period_key,
        target_level,
        cost_fen,
        len(recipients),
    )
    return True


async def process_billing_alerts_after_charge(
    db: AsyncSession,
    user: User | None,
    *,
    charged_fen: int,
    settings: Settings | None = None,
) -> None:
    """结算产生扣费后触发用户弹窗与管理员邮件检查。"""
    if int(charged_fen or 0) <= 0:
        return
    s = settings or get_settings()
    if user is not None:
        await process_user_milestone_alert(db, user, settings=s)
    await process_admin_cost_alert(db, settings=s)


async def list_pending_user_alerts(db: AsyncSession, user_id: int) -> list[BillingAlertNotification]:
    rows = (
        await db.execute(
            select(BillingAlertNotification)
            .where(
                BillingAlertNotification.user_id == int(user_id),
                BillingAlertNotification.acknowledged.is_(False),
            )
            .order_by(BillingAlertNotification.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def acknowledge_user_alert(db: AsyncSession, user_id: int, alert_id: int) -> bool:
    row = await db.get(BillingAlertNotification, int(alert_id))
    if not row or int(row.user_id) != int(user_id):
        return False
    row.acknowledged = True
    await db.flush()
    return True
