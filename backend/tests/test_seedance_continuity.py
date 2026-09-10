"""Seedance 请求体：尾帧衔接不可与 reference 媒体混用 first_frame。"""

from app.services.drama.build_seedance_generate_body import build_seedance_generate_body


def test_build_body_without_continuity_keeps_ratio():
    body = build_seedance_generate_body(
        {
            "content": "@duration:4\n空镜：江面起雾",
            "aspect_ratio": "9:16",
            "resolution": "480p",
            "duration_fallback": 8,
        }
    )
    assert body["ratio"] == "9:16"
    assert body["return_last_frame"] is True
    assert not any(
        item.get("role") == "first_frame" for item in body["content"] if isinstance(item, dict)
    )


def test_build_body_continuity_alone_uses_first_frame_and_omits_ratio():
    body = build_seedance_generate_body(
        {
            "content": "@duration:6\n近景：禹抬头望天",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration_fallback": 8,
            "continuity_first_frame_url": "https://cdn.example.com/prev_last.jpg",
        }
    )
    assert "ratio" not in body
    assert body["return_last_frame"] is True
    first = next(
        item
        for item in body["content"]
        if isinstance(item, dict) and item.get("role") == "first_frame"
    )
    assert first["image_url"]["url"] == "https://cdn.example.com/prev_last.jpg"
    text = next(item for item in body["content"] if item.get("type") == "text")
    assert "镜头衔接" in text["text"]


def test_build_body_continuity_with_reference_uses_reference_image_keeps_ratio():
    body = build_seedance_generate_body(
        {
            "content": "@duration:6\n禹：水患未平。",
            "aspect_ratio": "9:16",
            "resolution": "480p",
            "duration_fallback": 8,
            "continuity_first_frame_url": "https://cdn.example.com/prev_last.jpg",
            "reference": [
                {
                    "id": 1,
                    "type": "character",
                    "name": "禹",
                    "cover": "https://cdn.example.com/yu.jpg",
                    "url": "https://cdn.example.com/yu.jpg",
                    "params": {},
                }
            ],
        }
    )
    assert body["ratio"] == "9:16"
    roles = [item.get("role") for item in body["content"] if isinstance(item, dict)]
    assert "first_frame" not in roles
    assert roles.count("reference_image") >= 2
    last_image = [
        item
        for item in body["content"]
        if isinstance(item, dict) and item.get("role") == "reference_image"
    ][-1]
    assert last_image["image_url"]["url"] == "https://cdn.example.com/prev_last.jpg"
    text = next(item for item in body["content"] if item.get("type") == "text")
    assert "参考图序列最后一张" in text["text"]
