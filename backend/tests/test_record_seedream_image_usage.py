"""record_seedream_image_usage 集成。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ark import ImageResult
from app.services.drama.billing_util import record_seedream_image_usage
from tests.conftest import make_user


@pytest.mark.asyncio
async def test_record_seedream_with_upstream_tokens(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    image = ImageResult(
        local_url="/static/x.png",
        total_tokens=120000,
        completion_tokens=120000,
        raw_usage={"total_tokens": 120000},
    )
    ev = await record_seedream_image_usage(
        db_session,
        user_id=user.id,
        model="seedream-test",
        domain="api",
        image_result=image,
    )
    await db_session.commit()
    assert ev.estimated is False
    assert ev.total_tokens == 120000
    assert ev.charge_fen >= 1


@pytest.mark.asyncio
async def test_record_seedream_with_upstream_cost_fen(db_session: AsyncSession, monkeypatch) -> None:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "billing_markup", 2.0)

    user = await make_user(db_session)
    image = ImageResult(
        local_url="/static/x.png",
        upstream_cost_fen=500,
        raw_usage={"cost_fen": 500},
    )
    ev = await record_seedream_image_usage(
        db_session,
        user_id=user.id,
        model="seedream-test",
        domain="studio",
        image_result=image,
    )
    await db_session.commit()
    assert ev.estimated is False
    assert ev.cost_fen == 500
    assert ev.charge_fen == 1000
