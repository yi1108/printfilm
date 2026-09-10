"""Seedream / Seedance 上游 usage 与扣费换算。"""

from __future__ import annotations

from app.config import get_settings
from app.services.billing.pricing import charge_fen_for_usage, parse_upstream_cost_fen
from app.services.billing.usage import record_line


def test_parse_upstream_cost_fen_from_yuan():
    assert parse_upstream_cost_fen({"usage": {"cost": 1.23}}) == 123
    assert parse_upstream_cost_fen({"usage": {"cost_fen": 456}}) == 456


def test_charge_fen_for_usage_prefers_upstream_cost():
    settings = get_settings()
    settings.billing_markup = 1.5
    cost, charge, used = charge_fen_for_usage(
        0,
        "seedream",
        raw_usage={"usage": {"cost_fen": 1000}},
        settings=settings,
    )
    assert used is True
    assert cost == 1000
    assert charge == 1500


def test_charge_fen_for_usage_falls_back_to_tokens():
    settings = get_settings()
    settings.billing_markup = 1.5
    settings.billing_seedream_per_m = 8.0
    cost, charge, used = charge_fen_for_usage(
        1_000_000,
        "seedream",
        raw_usage={"usage": {"total_tokens": 1_000_000}},
        settings=settings,
    )
    assert used is False
    assert cost == 800
    assert charge == 1200


def test_build_task_result_includes_usage():
    from app.services.ark import _build_task_result_from_payload

    data = {
        "status": "succeeded",
        "content": {"video_url": "https://example.com/v.mp4"},
        "usage": {"total_tokens": 50000, "cost": 2.5},
    }
    result = _build_task_result_from_payload(data)
    assert result.total_tokens == 50000
    assert parse_upstream_cost_fen({"usage": result.raw_usage or {}}) == 250
