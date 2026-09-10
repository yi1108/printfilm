"""入队生成应清除进程内分集取消标记。"""

from app.services.drama.jobs import (
    _is_episode_video_cancelled,
    _mark_episode_video_cancelled,
    clear_episode_video_cancelled,
)


def test_clear_episode_video_cancelled_removes_inprocess_flag():
    _mark_episode_video_cancelled(115)
    assert _is_episode_video_cancelled(115)
    clear_episode_video_cancelled(115)
    assert not _is_episode_video_cancelled(115)


def test_clear_episode_video_cancelled_is_idempotent():
    clear_episode_video_cancelled(999)
    assert not _is_episode_video_cancelled(999)
