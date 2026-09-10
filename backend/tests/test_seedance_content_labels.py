"""describe_seedance_content_slots 与 content[] 下标对齐。"""

from app.services.drama.build_seedance_generate_body import (
    build_seedance_content_items,
    describe_seedance_content_slots,
)


def test_content_slot_labels_match_content_indices():
    reference = [
        {
            "id": 1,
            "type": "scene",
            "name": "羽山",
            "cover": "https://example.com/scene.jpg",
            "url": "",
            "params": {},
        },
        {
            "id": 2,
            "type": "character",
            "name": "相柳",
            "cover": "https://example.com/a.jpg",
            "url": "",
            "params": {},
        },
        {
            "id": 3,
            "type": "character",
            "name": "流民群演",
            "cover": "https://example.com/b.jpg",
            "url": "",
            "params": {},
        },
    ]
    items = build_seedance_content_items(
        "文案",
        reference,
        continuity_first_frame_url=None,
    )
    labels = describe_seedance_content_slots(reference, None, has_text=True)
    assert len(labels) == len(items)
    assert labels[0] == "分镜文案"
    assert "羽山" in labels[1]
    assert "相柳" in labels[2]
    assert "流民群演" in labels[3]
