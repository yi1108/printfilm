"""计费依据展示与筛选。"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent
from app.services.billing.display import (
    billing_basis_label,
    billing_basis_sql_filter,
    resolve_billing_basis,
)
from tests.conftest import make_user


def test_resolve_billing_basis_estimate():
    assert resolve_billing_basis(estimated=True, raw_usage_json=None) == "estimate"
    assert billing_basis_label("estimate") == "估算"


def test_resolve_billing_basis_upstream_tokens():
    raw = '{"usage": {"total_tokens": 120000}}'
    assert resolve_billing_basis(estimated=False, raw_usage_json=raw) == "upstream_usage"
    assert billing_basis_label("upstream_usage") == "实测(token)"


def test_resolve_billing_basis_upstream_cost():
    raw = '{"usage": {"cost_fen": 500}}'
    assert resolve_billing_basis(estimated=False, raw_usage_json=raw) == "upstream_cost"
    assert billing_basis_label("upstream_cost") == "实测(费用)"


def test_resolve_billing_basis_unknown_without_usage():
    assert resolve_billing_basis(estimated=False, raw_usage_json=None) == "unknown"
    assert billing_basis_label("unknown") == "实测(未分类)"


@pytest.mark.asyncio
async def test_billing_basis_sql_filter_cost(db_session: AsyncSession) -> None:
    from app.api.admin.usage import list_usage_events

    user = await make_user(db_session)
    user.email = f"basis-{uuid.uuid4().hex[:8]}@example.com"
    user.role = "admin"
    await db_session.flush()

    db_session.add_all(
        [
            UsageEvent(
                user_id=user.id,
                domain="drama",
                capability="video",
                billing_key="seedance",
                model="m",
                charge_fen=10,
                estimated=False,
                raw_usage_json=json.dumps({"usage": {"cost_fen": 88}}),
            ),
            UsageEvent(
                user_id=user.id,
                domain="drama",
                capability="video",
                billing_key="seedance",
                model="m",
                charge_fen=5,
                estimated=False,
                raw_usage_json=json.dumps({"usage": {"total_tokens": 1000}}),
            ),
            UsageEvent(
                user_id=user.id,
                domain="drama",
                capability="llm",
                billing_key="llm_chat",
                model="m",
                charge_fen=1,
                estimated=True,
            ),
        ]
    )
    await db_session.commit()

    cost_only = await list_usage_events(
        user_id=user.id,
        task_run_id=None,
        project_id=None,
        drama_project_id=None,
        domain=None,
        billing_key=None,
        capability=None,
        estimated=None,
        billing_basis="upstream_cost",
        created_from=None,
        created_to=None,
        page=1,
        page_size=20,
        _admin=user,
        db=db_session,
    )
    assert len(cost_only.items) == 1
    assert cost_only.items[0].billing_basis == "upstream_cost"

    token_only = await list_usage_events(
        user_id=user.id,
        task_run_id=None,
        project_id=None,
        drama_project_id=None,
        domain=None,
        billing_key=None,
        capability=None,
        estimated=None,
        billing_basis="upstream_usage",
        created_from=None,
        created_to=None,
        page=1,
        page_size=20,
        _admin=user,
        db=db_session,
    )
    assert len(token_only.items) == 1
    assert token_only.items[0].billing_basis == "upstream_usage"

    assert billing_basis_sql_filter("invalid") is None
