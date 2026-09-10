"""方舟管控面用量响应解析。"""

from __future__ import annotations

from app.services.ark_control_usage import (
    aggregate_usage_by_day,
    build_inference_usage_request_body,
    parse_inference_usage_rows,
)


def test_build_inference_usage_request_body_uses_query_interval():
    body = build_inference_usage_request_body("2026-08-01", "2026-08-07")
    assert body == {
        "StartTime": "2026-08-01",
        "EndTime": "2026-08-07",
        "QueryInterval": "Day",
    }


def test_parse_inference_usage_rows_table():
    result = {
        "Fields": [
            {"Name": "Day", "Type": "DATE"},
            {"Name": "ModelName", "Type": "STRING"},
            {"Name": "Value", "Type": "BIGINT"},
        ],
        "Data": [
            ["2026-08-26", "doubao-seedance-2-0", 500000],
            ["2026-08-27", "doubao-seedance-2-0", 800000],
        ],
    }
    rows = parse_inference_usage_rows(result)
    assert len(rows) == 2
    assert rows[0]["Day"] == "2026-08-26"
    daily = aggregate_usage_by_day(rows)
    assert daily["2026-08-26"] == 500000
    assert daily["2026-08-27"] == 800000


def test_aggregate_usage_by_day_skips_non_video_models():
    rows = [
        {"Day": "2026-08-26", "ModelName": "doubao-seedream", "Value": 1000},
        {"Day": "2026-08-26", "ModelName": "doubao-seedance-2-0", "Value": 2000},
    ]
    daily = aggregate_usage_by_day(rows)
    assert daily.get("2026-08-26") == 2000
