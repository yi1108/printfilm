"""pending/在途分镜视频任务作废判定：重新生成不得因旧 video 被误取消。"""

from types import SimpleNamespace

import pytest

from app.services.tasks.service import stale_pending_fragment_video_reason


def _frag(**kwargs):
    return SimpleNamespace(**kwargs)


def test_stale_reason_none_when_regen_queued_with_video():
    frag = _frag(
        video="https://cdn/old.mp4",
        params={"generation": {"status": "queued"}},
    )
    assert stale_pending_fragment_video_reason([frag]) is None


def test_stale_reason_skip_duplicate_when_video_done():
    frag = _frag(video="https://cdn/done.mp4", cover="", params={})
    assert stale_pending_fragment_video_reason([frag]) == "分镜已生成完成，跳过重复任务"


def test_stale_reason_keep_when_replace_existing_video():
    frag = _frag(video="https://cdn/old.mp4", cover="", params={})
    task = SimpleNamespace(payload={"replace_existing_video": True})
    assert stale_pending_fragment_video_reason([frag], task) is None


def test_stale_reason_keep_when_no_video_yet():
    frag = _frag(video="", params={"generation": {"status": "queued"}})
    assert stale_pending_fragment_video_reason([frag]) is None


def test_stale_reason_deleted_fragments():
    assert stale_pending_fragment_video_reason([]) == "分镜已变更，请重新生成"


@pytest.mark.asyncio
async def test_mark_task_cancelled_stale_settles_frozen_billing():
    """作废已预扣任务时必须 settle，避免 frozen 余额悬挂。"""
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, patch

    from app.services.tasks.service import _mark_task_cancelled_stale

    task = SimpleNamespace(
        id=3328,
        status="awaiting_poll",
        cancel_requested=False,
        error_code=None,
        error_message=None,
        finished_at=None,
        next_action_at=None,
        lease_token="x",
        lease_until=None,
        current_step_key="submit",
        billing_status="frozen",
        billing_estimate_fen=2650,
    )
    db = AsyncMock()
    settle = AsyncMock(return_value={"charged": 0, "refunded": 2650})
    with (
        patch("app.services.tasks.service.append_task_event", new=AsyncMock()) as append_ev,
        patch("app.services.billing.settlement.settle_task", new=settle),
    ):
        await _mark_task_cancelled_stale(db, task, "分镜已生成完成，跳过重复任务", datetime.now(UTC))
    assert task.status == "cancelled"
    append_ev.assert_awaited_once()
    settle.assert_awaited_once_with(db, 3328)