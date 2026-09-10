"""OSS 队列回填：漫剧表 + 旧 /static 补传。"""

from __future__ import annotations

from app.services.oss_queue import (
    _collect_local_urls_from_params,
    _rewrite_local_urls_in_params,
)


def test_rewrite_local_urls_in_params_nested():
    params = {
        "voiceAudio": "/static/generated/p1/voice.mp3",
        "canvas": {"voiceAudio": "/static/generated/p1/voice.mp3", "other": 1},
    }
    assert _rewrite_local_urls_in_params(
        params,
        "/static/generated/p1/voice.mp3",
        "https://cdn.example/voice.mp3",
    )
    assert params["voiceAudio"] == "https://cdn.example/voice.mp3"
    assert params["canvas"]["voiceAudio"] == "https://cdn.example/voice.mp3"


def test_collect_local_urls_from_params():
    found: set[str] = set()
    _collect_local_urls_from_params(
        {
            "voiceAudio": "/static/a.mp3",
            "canvas": {"voiceAudio": "https://cdn.example/b.mp3"},
            "note": "/static/not-a-media-key.txt",
        },
        found,
    )
    assert found == {"/static/a.mp3"}


def test_upload_local_url_sync_accepts_oss_https_even_if_local_file_exists(tmp_path, monkeypatch):
    """上传成功返回 OSS https 时，即使本地仍有文件也不应 raise。"""
    from pathlib import Path
    from unittest.mock import patch

    from app.services import oss_queue
    from app.services import storage as storage_mod

    local = tmp_path / "generated" / "p1" / "shot.png"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"png")
    local_url = "/static/generated/p1/shot.png"
    oss_https = "https://lsj-cc.oss-cn-beijing.aliyuncs.com/kepu/generated/p1/shot.png"

    monkeypatch.setattr(storage_mod, "STATIC_ROOT", tmp_path)
    monkeypatch.setattr(storage_mod, "is_local_static_url", lambda url: str(url or "").startswith("/static/"))
    monkeypatch.setattr(storage_mod, "local_path_from_url", lambda url: local if url == local_url else None)
    monkeypatch.setattr(storage_mod, "upload_local_sync", lambda path: oss_https)

    with patch.object(oss_queue.oss_svc, "oss_enabled", return_value=True):
        out = oss_queue.upload_local_url_sync(local_url)
    assert out == oss_https


def test_is_local_static_url_rejects_oss_https():
    """OSS https 不应因本地副本存在而被判为本地。"""
    from app.services.storage import is_local_static_url

    assert is_local_static_url("/static/generated/p1/a.png") is True
    assert (
        is_local_static_url("https://lsj-cc.oss-cn-beijing.aliyuncs.com/kepu/generated/p1/a.png")
        is False
    )
    assert is_local_static_url("https://www.printfilm.com/static/generated/p1/a.png") is True
