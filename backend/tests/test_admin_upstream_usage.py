"""官方上游用量快照与本地对照。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UpstreamUsageDaily, UsageEvent
from app.services.admin.upstream_usage import build_upstream_usage_compare
from tests.conftest import make_user


@pytest.mark.asyncio
async def test_build_upstream_usage_compare_merges_local_and_snapshot(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    day = datetime.now(UTC).date()
    db_session.add(
        UsageEvent(
            user_id=user.id,
            billing_key="seedance2:video0",
            model="doubao-seedance",
            total_tokens=50_000,
            cost_fen=2300,
            charge_fen=3450,
            estimated=False,
            domain="drama",
            created_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        )
    )
    db_session.add(
        UpstreamUsageDaily(
            usage_date=day,
            official_tokens=48_000,
            official_cost_fen=2208,
            local_cost_fen=2300,
            local_tokens=50_000,
            fetched_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    raw = await build_upstream_usage_compare(db_session, days=7)
    hit = next((row for row in raw["series"] if row["date"] == day.isoformat()), None)
    assert hit is not None
    assert hit["local_cost_fen"] == 2300
    assert hit["official_tokens"] == 48_000
    assert hit["official_cost_fen"] == 2208
    assert hit["delta_fen"] == 92
