"""额度告警：用户里程碑弹窗与管理员邮件。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent
from app.services.billing.alerts import (
    acknowledge_user_alert,
    list_pending_user_alerts,
    process_admin_cost_alert,
    process_billing_alerts_after_charge,
    process_user_milestone_alert,
)
from tests.conftest import make_user


async def _add_settled_usage(
    db: AsyncSession,
    *,
    user_id: int,
    charge_fen: int,
    cost_fen: int = 0,
) -> UsageEvent:
    ev = UsageEvent(
        user_id=user_id,
        domain="api",
        capability="llm",
        billing_key="llm_chat",
        model="test",
        total_tokens=100,
        charge_fen=charge_fen,
        cost_fen=cost_fen,
        settled=True,
    )
    db.add(ev)
    await db.flush()
    return ev


@pytest.mark.asyncio
async def test_user_milestone_creates_popup_notification(db_session: AsyncSession, monkeypatch) -> None:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "billing_user_alert_enabled", True)
    monkeypatch.setattr(settings, "billing_user_alert_interval_fen", 1000)

    user = await make_user(db_session)
    await _add_settled_usage(db_session, user_id=user.id, charge_fen=2500)
    await db_session.commit()

    created = await process_user_milestone_alert(db_session, user, settings=settings)
    await db_session.commit()

    assert len(created) == 2
    assert created[0].milestone_fen == 1000
    assert created[1].milestone_fen == 2000
    assert int(user.billing_alert_last_milestone_fen) == 2000

    pending = await list_pending_user_alerts(db_session, user.id)
    assert len(pending) == 2

    ok = await acknowledge_user_alert(db_session, user.id, pending[0].id)
    assert ok is True
    await db_session.commit()
    pending_after = await list_pending_user_alerts(db_session, user.id)
    assert len(pending_after) == 1


@pytest.mark.asyncio
async def test_admin_cost_alert_sends_email_once_per_level(db_session: AsyncSession, monkeypatch) -> None:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "billing_admin_cost_alert_enabled", True)
    monkeypatch.setattr(settings, "billing_admin_cost_alert_threshold_fen", 1000)
    monkeypatch.setattr(settings, "billing_admin_cost_alert_period", "all_time")
    monkeypatch.setattr(settings, "billing_admin_cost_alert_emails", "ops@test.local")
    monkeypatch.setattr(settings, "billing_admin_cost_alert_last_period_key", "")
    monkeypatch.setattr(settings, "billing_admin_cost_alert_last_level", 0)
    monkeypatch.setattr(settings, "app_name", "PRINTFILM")

    user = await make_user(db_session)
    await _add_settled_usage(db_session, user_id=user.id, charge_fen=100, cost_fen=1500)
    await db_session.commit()

    with patch("app.services.billing.alerts.send_email", new_callable=AsyncMock) as send_mock:
        send_mock.return_value = True
        sent = await process_admin_cost_alert(db_session, settings=settings)
        await db_session.commit()
        assert sent is True
        send_mock.assert_called_once()

        send_mock.reset_mock()
        sent_again = await process_admin_cost_alert(db_session, settings=settings)
        assert sent_again is False
        send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_process_after_charge_triggers_user_alert(db_session: AsyncSession, monkeypatch) -> None:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "billing_user_alert_enabled", True)
    monkeypatch.setattr(settings, "billing_user_alert_interval_fen", 1000)
    monkeypatch.setattr(settings, "billing_admin_cost_alert_enabled", False)

    user = await make_user(db_session)
    await _add_settled_usage(db_session, user_id=user.id, charge_fen=900)
    await _add_settled_usage(db_session, user_id=user.id, charge_fen=200)
    await db_session.commit()

    await process_billing_alerts_after_charge(db_session, user, charged_fen=200, settings=settings)
    await db_session.commit()

    pending = await list_pending_user_alerts(db_session, user.id)
    assert len(pending) == 1
    assert pending[0].milestone_fen == 1000
