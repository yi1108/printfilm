import pytest

from app.printfilm_studio.integration.media import media_task_payload


def test_media_task_payload_uses_scheduler_params_without_internal_kind():
    payload = media_task_payload("image", "  a neon city  ", ratio="16:9", model_id="seedream-5.0")
    assert payload == {"prompt": "a neon city", "ratio": "16:9", "model_id": "seedream-5.0"}


def test_media_task_payload_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unsupported media kind"):
        media_task_payload("3d", "scene")
