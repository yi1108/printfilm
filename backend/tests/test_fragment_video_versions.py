"""分镜生成状态与视频版本。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.drama.generation import (
    activate_fragment_video_version,
    archive_fragment_video_version,
    fragment_generation_status,
    generation_queued_recently,
)


def _frag(**kwargs):
    return SimpleNamespace(**kwargs)


def test_fragment_generation_status_prefers_queued_over_video():
    frag = _frag(
        video="https://cdn/x.mp4",
        cover="https://cdn/x.jpg",
        params={"generation": {"status": "queued", "message": "已入队"}},
    )
    st = fragment_generation_status(frag)  # type: ignore[arg-type]
    assert st["status"] == "queued"


def test_fragment_generation_status_done_when_video_and_idle_gen():
    frag = _frag(video="https://cdn/x.mp4", cover="", params={"generation": {"status": "idle"}})
    st = fragment_generation_status(frag)  # type: ignore[arg-type]
    assert st["status"] == "done"


def test_archive_and_activate_video_version(tmp_path, monkeypatch):
    from pathlib import Path

    from app.services.drama import generation as gen_mod

    video_file = tmp_path / "shot_009.mp4"
    video_file.write_bytes(b"old-video")
    cover_file = tmp_path / "shot_009_cover.jpg"
    cover_file.write_bytes(b"old-cover")

    def fake_local_path(url: str):
        name = str(url).rsplit("/", 1)[-1]
        path = tmp_path / name
        return path if path.exists() else None

    def fake_rel(path: Path) -> str:
        return f"/static/generated/t/{path.name}"

    def fake_republish(url: str | None, *, sync: bool = True):
        return url

    monkeypatch.setattr("app.services.storage.local_path_from_url", fake_local_path)
    monkeypatch.setattr("app.services.storage.rel_static_url", fake_rel)
    monkeypatch.setattr("app.services.storage.republish_url", fake_republish)

    frag = _frag(
        id=9,
        video="/static/generated/t/shot_009.mp4",
        cover="/static/generated/t/shot_009_cover.jpg",
        params={"lastFrameUrl": "", "video_versions": []},
    )
    archived = archive_fragment_video_version(frag)  # type: ignore[arg-type]
    assert archived is not None
    hist_video = frag.params["video_versions"][0]["video"]
    assert "_hist_" in hist_video
    assert (tmp_path / hist_video.rsplit("/", 1)[-1]).exists()

    # 同 URL 再归档不应因去重丢掉上一条（覆盖场景）
    frag.video = "/static/generated/t/shot_009.mp4"
    archive_fragment_video_version(frag)  # type: ignore[arg-type]
    assert len(frag.params["video_versions"]) == 2

    frag.video = "https://cdn/new.mp4"
    frag.cover = "https://cdn/new.jpg"
    frag.params["lastFrameUrl"] = "https://cdn/new-last.jpg"
    version_id = frag.params["video_versions"][0]["id"]
    out = activate_fragment_video_version(frag, version_id)  # type: ignore[arg-type]
    assert out["video"] == hist_video or "_hist_" in out["video"]
    assert frag.video == out["video"]


def test_archive_skips_empty_video():
    frag = _frag(id=1, video="", cover="", params={})
    assert archive_fragment_video_version(frag) is None  # type: ignore[arg-type]


def test_generation_queued_recently_within_grace():
    now = datetime(2026, 8, 24, 7, 0, tzinfo=UTC)
    gen = {"status": "queued", "queued_at": (now - timedelta(seconds=10)).isoformat()}
    assert generation_queued_recently(gen, now=now) is True


def test_generation_queued_recently_expired():
    now = datetime(2026, 8, 24, 7, 0, tzinfo=UTC)
    gen = {"status": "queued", "queued_at": (now - timedelta(seconds=90)).isoformat()}
    assert generation_queued_recently(gen, now=now) is False
