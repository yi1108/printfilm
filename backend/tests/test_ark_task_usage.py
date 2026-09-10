"""Seedance 任务查询响应 usage 解析。"""

from __future__ import annotations

from app.services.ark import TaskResult, _build_task_result_from_payload


def test_build_task_result_success_with_usage():
    data = {
        "status": "succeeded",
        "content": {"video_url": "https://example.com/v.mp4"},
        "usage": {"completion_tokens": 108900, "total_tokens": 108900},
    }
    result = _build_task_result_from_payload(data)
    assert result.status == "succeeded"
    assert result.url == "https://example.com/v.mp4"
    assert result.total_tokens == 108900
    assert result.completion_tokens == 108900
    assert result.raw_usage == {"completion_tokens": 108900, "total_tokens": 108900}


def test_build_task_result_failed_with_zero_usage():
    data = {
        "status": "failed",
        "error": {"message": "upstream error"},
        "usage": {"completion_tokens": 0, "total_tokens": 0},
    }
    result = _build_task_result_from_payload(data)
    assert result.status == "failed"
    assert result.total_tokens == 0


def test_build_task_result_running_without_usage():
    data = {"status": "running"}
    result = _build_task_result_from_payload(data)
    assert result.status == "running"
    assert result.total_tokens == 0


def test_task_result_dataclass_defaults():
    row = TaskResult(status="running")
    assert row.total_tokens == 0
    assert row.raw_usage is None
