"""AI 重新分镜：force 须清空旧分镜（含已有视频/手改）。"""

from types import SimpleNamespace

from app.services.drama.seed import _fragment_is_protected


def test_fragment_is_protected_detects_video_and_user_edited():
    with_video = SimpleNamespace(
        video="https://example.com/a.mp4",
        params={},
    )
    user_edited = SimpleNamespace(
        video="",
        params={"user_edited": True},
    )
    plain = SimpleNamespace(video="", params={"user_edited": False})
    assert _fragment_is_protected(with_video) is True
    assert _fragment_is_protected(user_edited) is True
    assert _fragment_is_protected(plain) is False


def test_fragment_plan_handler_passes_force_flag():
    from unittest.mock import AsyncMock, patch

    from app.services.tasks import handlers

    fake_run = AsyncMock(return_value={"ok": True})
    task = SimpleNamespace(
        episode_id=99,
        payload={"force": True, "fallback_rules": False},
    )
    with patch("app.services.drama.jobs.run_episode_fragment_plan_job", fake_run):
        import asyncio

        asyncio.run(handlers._run_drama_fragment_plan(task))

    fake_run.assert_awaited_once_with(
        99,
        fallback_rules=False,
        subtitle_enabled=None,
        force=True,
    )
