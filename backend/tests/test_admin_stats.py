"""管理端仪表盘 / 项目用量聚合：日趋势、补零、Top10、能力分解。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent
from app.services.admin.stats import aggregate_usage_summary, build_admin_dashboard_stats
from tests.conftest import make_user


def _utc_days_ago(days: int, *, hour: int = 12) -> datetime:
    base = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0)
    return base - timedelta(days=days)


async def _add_usage(
    db: AsyncSession,
    *,
    user_id: int,
    charge_fen: int,
    cost_fen: int = 0,
    created_at: datetime | None = None,
    capability: str = "llm",
    domain: str = "drama",
    billing_key: str = "llm_chat",
    project_id: int | None = None,
    drama_project_id: int | None = None,
    total_tokens: int = 100,
    task_run_id: int | None = None,
) -> UsageEvent:
    """写入一条用量事件。"""
    ev = UsageEvent(
        user_id=user_id,
        project_id=project_id,
        drama_project_id=drama_project_id,
        task_run_id=task_run_id,
        domain=domain,
        capability=capability,
        billing_key=billing_key,
        model="test-model",
        prompt_tokens=total_tokens,
        completion_tokens=0,
        total_tokens=total_tokens,
        charge_fen=charge_fen,
        cost_fen=cost_fen,
        estimated=False,
        settled=True,
    )
    if created_at is not None:
        ev.created_at = created_at
    db.add(ev)
    await db.flush()
    return ev


@pytest.mark.asyncio
async def test_dashboard_daily_usage_pads_seven_days(db_session: AsyncSession) -> None:
    """近 7 日趋势固定 7 行，无数据的日期补零。"""
    user = await make_user(db_session)
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=50,
        cost_fen=20,
        created_at=_utc_days_ago(0),
        capability="image",
        billing_key="seedream",
    )
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=30,
        created_at=_utc_days_ago(2),
        capability="video",
        billing_key="seedance2:video0",
        domain="kepu",
    )
    await db_session.commit()

    stats = await build_admin_dashboard_stats(db_session)
    daily = stats["daily_usage"]
    assert len(daily) == 7
    assert all("date" in d and "calls" in d and "charge_fen" in d and "cost_fen" in d for d in daily)
    # 日期升序且连续
    dates = [d["date"] for d in daily]
    assert dates == sorted(dates)
    today_key = _utc_days_ago(0).date().isoformat()
    two_ago = _utc_days_ago(2).date().isoformat()
    by_day = {d["date"]: d for d in daily}
    assert by_day[today_key]["calls"] == 1
    assert by_day[today_key]["charge_fen"] == 50
    assert by_day[two_ago]["calls"] == 1
    assert by_day[two_ago]["charge_fen"] == 30
    empty_days = [d for d in daily if d["date"] not in {today_key, two_ago}]
    assert all(d["calls"] == 0 and d["charge_fen"] == 0 for d in empty_days)

    assert stats["usage_calls_total"] == 2
    assert stats["usage_charge_total_fen"] == 80
    assert stats["usage_cost_total_fen"] == 20
    assert stats["usage_calls_today"] == 1
    assert stats["usage_charge_today_fen"] == 50


@pytest.mark.asyncio
async def test_dashboard_filters_domain_and_capability(db_session: AsyncSession) -> None:
    """按领域与能力筛选后，分布桶只含匹配数据。"""
    user = await make_user(db_session)
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=50,
        cost_fen=20,
        created_at=_utc_days_ago(1),
        capability="image",
        domain="drama",
        billing_key="seedream",
    )
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=30,
        cost_fen=10,
        created_at=_utc_days_ago(1),
        capability="video",
        billing_key="seedance2:video0",
        domain="kepu",
    )
    await db_session.commit()

    drama_only = await build_admin_dashboard_stats(db_session, days=7, domain="drama")
    assert sum(b["calls"] for b in drama_only["usage_by_capability"]) == 1
    assert drama_only["usage_by_capability"][0]["key"] == "image"
    assert drama_only["usage_by_capability"][0]["cost_fen"] == 20

    video_only = await build_admin_dashboard_stats(db_session, days=7, capability="video")
    assert len(video_only["usage_by_domain"]) == 1
    assert video_only["usage_by_domain"][0]["key"] == "kepu"
    assert video_only["daily_usage"][-1]["calls"] == 0


@pytest.mark.asyncio
async def test_dashboard_today_window(db_session: AsyncSession) -> None:
    """days=1 时仅统计今日，趋势序列 1 行。"""
    user = await make_user(db_session)
    domain = "test_today_window"
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=40,
        cost_fen=12,
        created_at=_utc_days_ago(0),
        capability="llm",
        domain=domain,
    )
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=99,
        created_at=_utc_days_ago(1),
        capability="llm",
        domain=domain,
    )
    await db_session.commit()

    stats = await build_admin_dashboard_stats(db_session, days=1, domain=domain)
    assert len(stats["daily_usage"]) == 1
    today_key = _utc_days_ago(0).date().isoformat()
    assert stats["daily_usage"][0]["date"] == today_key
    assert stats["daily_usage"][0]["calls"] == 1
    assert stats["daily_usage"][0]["charge_fen"] == 40
    assert sum(b["calls"] for b in stats["usage_by_capability"]) == 1


@pytest.mark.asyncio
async def test_admin_stats_http_query_days_accepts_string_query() -> None:
    """HTTP ?days=7 应能解析为 int，不能因 Literal 校验返回 422。"""
    import httpx
    from httpx import ASGITransport

    from app.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/api/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
        if login.status_code != 200:
            pytest.skip("demo 账号不可用，跳过 HTTP stats 回归")
        token = login.json()["access_token"]
        res = await client.get(
            "/api/admin/stats?days=7",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "usage_calls_month" in body
    assert "usage_calls_total" in body


@pytest.mark.asyncio
async def test_admin_stats_route_days_one(db_session: AsyncSession) -> None:
    """admin_stats 路由 days=1 返回单日趋势。"""
    import uuid

    from app.api.admin.dashboard import admin_stats

    admin = await make_user(db_session)
    admin.email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    admin.role = "admin"
    await db_session.flush()

    domain = "test_stats_route_today"
    await _add_usage(
        db_session,
        user_id=admin.id,
        charge_fen=25,
        created_at=_utc_days_ago(0),
        capability="llm",
        domain=domain,
    )
    await _add_usage(
        db_session,
        user_id=admin.id,
        charge_fen=80,
        created_at=_utc_days_ago(1),
        capability="llm",
        domain=domain,
    )
    await db_session.commit()

    out = await admin_stats(
        days=1,
        domain=domain,
        capability="all",
        top_metric="charge",
        _admin=admin,
        db=db_session,
    )
    assert len(out.daily_usage) == 1
    assert out.daily_usage[0].calls == 1
    assert out.daily_usage[0].charge_fen == 25


@pytest.mark.asyncio
async def test_dashboard_days_window_padding(db_session: AsyncSession) -> None:
    """days=14 时趋势序列固定 14 行并补零。"""
    user = await make_user(db_session)
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=10,
        created_at=_utc_days_ago(10),
        capability="llm",
    )
    await db_session.commit()

    stats = await build_admin_dashboard_stats(db_session, days=14)
    assert len(stats["daily_usage"]) == 14
    ten_ago = _utc_days_ago(10).date().isoformat()
    by_day = {d["date"]: d for d in stats["daily_usage"]}
    assert by_day[ten_ago]["calls"] == 1
    assert by_day[ten_ago]["charge_fen"] == 10


@pytest.mark.asyncio
async def test_dashboard_top_users_by_charge(db_session: AsyncSession) -> None:
    """近 30 日按扣费排序，最多 10 人。"""
    high = await make_user(db_session)
    low = await make_user(db_session)
    domain = "test_top_users_charge"
    await _add_usage(
        db_session, user_id=high.id, charge_fen=900, created_at=_utc_days_ago(1), domain=domain
    )
    await _add_usage(
        db_session, user_id=high.id, charge_fen=100, created_at=_utc_days_ago(5), domain=domain
    )
    await _add_usage(
        db_session, user_id=low.id, charge_fen=10, created_at=_utc_days_ago(1), domain=domain
    )
    await db_session.commit()

    stats = await build_admin_dashboard_stats(db_session, days=30, domain=domain)
    top = stats["top_users_by_charge"]
    assert len(top) == 2
    assert top[0]["user_id"] == high.id
    assert top[0]["charge_fen"] == 1000
    assert top[0]["calls"] == 2
    assert top[0]["email"] == high.email
    assert top[1]["user_id"] == low.id
    assert top[1]["charge_fen"] == 10


@pytest.mark.asyncio
async def test_dashboard_top_users_by_cost(db_session: AsyncSession) -> None:
    """top_metric=cost 时按上游成本排序。"""
    high = await make_user(db_session)
    low = await make_user(db_session)
    domain = "test_top_users_cost"
    await _add_usage(
        db_session,
        user_id=high.id,
        charge_fen=10,
        cost_fen=500,
        created_at=_utc_days_ago(1),
        domain=domain,
    )
    await _add_usage(
        db_session,
        user_id=low.id,
        charge_fen=900,
        cost_fen=50,
        created_at=_utc_days_ago(1),
        domain=domain,
    )
    await db_session.commit()

    stats = await build_admin_dashboard_stats(db_session, days=30, domain=domain, top_metric="cost")
    top = stats["top_users_by_charge"]
    assert len(top) == 2
    assert top[0]["user_id"] == high.id
    assert top[0]["cost_fen"] == 500
    assert top[1]["user_id"] == low.id
    assert top[1]["cost_fen"] == 50


@pytest.mark.asyncio
async def test_validate_stats_days_rejects_invalid_value() -> None:
    from fastapi import HTTPException

    from app.api.admin.dashboard import _validate_stats_days

    assert _validate_stats_days(7) == 7
    with pytest.raises(HTTPException) as exc:
        _validate_stats_days(5)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_admin_stats_http_query_days_invalid_returns_422() -> None:
    """非法 days 档位应返回 422。"""
    import httpx
    from httpx import ASGITransport

    from app.main import app

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/admin/stats?days=5")
    assert res.status_code in (401, 422)
    if res.status_code == 422:
        assert "days must be one of" in res.text


@pytest.mark.asyncio
async def test_dashboard_capability_derived_from_billing_key(db_session: AsyncSession) -> None:
    """capability 为空时按 billing_key 归入能力分布，避免全部落到 unknown。"""
    user = await make_user(db_session)
    domain = "test_cap_derived_domain"
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=500,
        billing_key="seedance2:video0",
        capability=None,  # type: ignore[arg-type]
        domain=domain,
        created_at=_utc_days_ago(0),
    )
    await _add_usage(
        db_session,
        user_id=user.id,
        charge_fen=80,
        billing_key="llm_chat",
        capability=None,  # type: ignore[arg-type]
        domain=domain,
        created_at=_utc_days_ago(0),
    )
    await db_session.commit()

    stats = await build_admin_dashboard_stats(db_session, days=7, domain=domain)
    by_cap = {row["key"]: row for row in stats["usage_by_capability"]}
    assert by_cap.get("unknown", {}).get("charge_fen", 0) == 0
    assert by_cap.get("other", {}).get("charge_fen", 0) == 0
    assert by_cap["video"]["charge_fen"] == 500
    assert by_cap["llm"]["charge_fen"] == 80


@pytest.mark.asyncio
async def test_aggregate_usage_summary_breakdown(db_session: AsyncSession) -> None:
    """单项目用量拆分图/视/LLM/TTS。"""
    user = await make_user(db_session)
    pid = 42
    await _add_usage(
        db_session, user_id=user.id, project_id=pid, charge_fen=10, billing_key="seedream", capability="image"
    )
    await _add_usage(
        db_session,
        user_id=user.id,
        project_id=pid,
        charge_fen=20,
        billing_key="seedance2:video0",
        capability="video",
    )
    await _add_usage(
        db_session, user_id=user.id, project_id=pid, charge_fen=5, billing_key="llm_chat", capability="llm"
    )
    await _add_usage(
        db_session, user_id=user.id, project_id=pid, charge_fen=3, billing_key="tts", capability="tts"
    )
    # 其他项目不应计入
    await _add_usage(
        db_session, user_id=user.id, project_id=99, charge_fen=999, billing_key="seedream", capability="image"
    )
    await db_session.commit()

    summary = await aggregate_usage_summary(db_session, project_id=pid)
    assert summary["calls"] == 4
    assert summary["charge_fen"] == 38
    assert summary["image_gens"] == 1
    assert summary["video_gens"] == 1
    assert summary["llm_calls"] == 1
    assert summary["tts_gens"] == 1

    batch = await aggregate_usage_summary(db_session, project_ids=[pid, 99, 7])
    assert batch[pid]["tts_gens"] == 1
    assert batch[99]["image_gens"] == 1
    assert batch[99]["charge_fen"] == 999
    assert batch[7]["calls"] == 0
    assert batch[7]["tts_gens"] == 0


@pytest.mark.asyncio
async def test_aggregate_drama_project_usage(db_session: AsyncSession) -> None:
    """漫剧项目按 drama_project_id 聚合。"""
    user = await make_user(db_session)
    did = 7
    await _add_usage(
        db_session,
        user_id=user.id,
        drama_project_id=did,
        charge_fen=15,
        cost_fen=8,
        billing_key="tts",
        capability="tts",
        total_tokens=50,
    )
    await db_session.commit()

    summary = await aggregate_usage_summary(db_session, drama_project_id=did)
    assert summary["calls"] == 1
    assert summary["charge_fen"] == 15
    assert summary["cost_fen"] == 8
    assert summary["tokens"] == 50
    assert summary["tts_gens"] == 1


@pytest.mark.asyncio
async def test_aggregate_keeps_multi_llm_dedupes_seedance(db_session: AsyncSession) -> None:
    """同 task 下 llm_chat 多行保留；seedance 重复行只计一条。"""
    user = await make_user(db_session)
    # drama_project_id 无 FK，避免依赖 projects 行；用高位 id 降低脏数据干扰
    did = 880_001_903
    tid = 9001
    await _add_usage(
        db_session,
        user_id=user.id,
        drama_project_id=did,
        task_run_id=tid,
        charge_fen=5,
        billing_key="llm_chat",
        capability="llm",
    )
    await _add_usage(
        db_session,
        user_id=user.id,
        drama_project_id=did,
        task_run_id=tid,
        charge_fen=7,
        billing_key="llm_chat",
        capability="llm",
    )
    await _add_usage(
        db_session,
        user_id=user.id,
        drama_project_id=did,
        task_run_id=tid,
        charge_fen=20,
        billing_key="seedance2:video0",
        capability="video",
    )
    await _add_usage(
        db_session,
        user_id=user.id,
        drama_project_id=did,
        task_run_id=tid,
        charge_fen=20,
        billing_key="seedance2:video0",
        capability="video",
    )
    await db_session.commit()

    summary = await aggregate_usage_summary(db_session, drama_project_id=did)
    assert summary["llm_calls"] == 2
    assert summary["video_gens"] == 1
    assert summary["calls"] == 3
    assert summary["charge_fen"] == 5 + 7 + 20
