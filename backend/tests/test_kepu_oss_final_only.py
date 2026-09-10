"""科普流水线：中间分镜不入 OSS，仅成片 final.mp4 上传。"""

from __future__ import annotations

from pathlib import Path

from app.services import storage
from app.services.oss_queue import collect_pending_column_targets


def test_skip_intermediates_keeps_shot_files_local(tmp_path, monkeypatch):
    # 分镜图/配音/镜头视频只返回 /static，不成队
    shot = tmp_path / "shot_001.png"
    shot.write_bytes(b"png")
    enqueued: list[str] = []

    monkeypatch.setattr(storage, "STATIC_ROOT", tmp_path)
    monkeypatch.setattr("app.services.oss.oss_enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.oss_queue.enqueue_oss_upload",
        lambda url: enqueued.append(url) or True,
    )
    monkeypatch.setattr(
        "app.services.storage.get_settings",
        lambda: type("S", (), {"oss_upload_async": True, "public_base_url": ""})(),
    )

    with storage.skip_oss_intermediates():
        url = storage.publish_local(shot)

    assert url.startswith("/static/")
    assert enqueued == []


def test_skip_intermediates_still_uploads_final_mp4(tmp_path, monkeypatch):
    # 成片文件仍入 OSS 队列
    final = tmp_path / "final.mp4"
    final.write_bytes(b"mp4")
    enqueued: list[str] = []

    monkeypatch.setattr(storage, "STATIC_ROOT", tmp_path)
    monkeypatch.setattr("app.services.oss.oss_enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.oss_queue.enqueue_oss_upload",
        lambda url: enqueued.append(url) or True,
    )
    monkeypatch.setattr(
        "app.services.storage.get_settings",
        lambda: type("S", (), {"oss_upload_async": True, "public_base_url": ""})(),
    )

    with storage.skip_oss_intermediates():
        url = storage.publish_local(final)

    assert url.startswith("/static/")
    assert enqueued == [url]


def test_collect_pending_skips_kepu_shot_columns():
    # 补传扫描不再扫分镜图/镜头视频/配音，避免把中间文件重新入队
    models = {model.__name__: fields for model, fields in collect_pending_column_targets()}
    assert "Shot" not in models
    assert models["Project"] == ["final_video_url"]
