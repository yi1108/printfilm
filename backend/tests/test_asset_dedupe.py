"""资产同名去重键与保留评分。"""

from types import SimpleNamespace

from app.services.drama.seed import (
    _asset_dedupe_key,
    _character_name_for_seed,
    _duplicate_asset_keep_score,
    _extract_cast_names_from_bodies,
    _is_voice_like_character_name,
    _normalize_asset_name,
)


def test_normalize_asset_name_collapses_whitespace():
    assert _normalize_asset_name("  周  明远 ") == "周 明远"


def test_dedupe_key_maps_none_to_material():
    assert _asset_dedupe_key("none", "石碑") == ("material", "石碑")
    assert _asset_dedupe_key("material", "石碑") == ("material", "石碑")


def test_keep_score_prefers_media_then_voice_then_older_id():
    bare = SimpleNamespace(id=5, cover="", url="", params={})
    with_cover = SimpleNamespace(id=9, cover="https://x/a.jpg", url="", params={})
    with_voice = SimpleNamespace(
        id=8,
        cover="https://x/a.jpg",
        url="",
        params={"voiceAudio": {"url": "https://x/v.mp3"}},
    )
    assert _duplicate_asset_keep_score(with_voice) > _duplicate_asset_keep_score(with_cover)
    assert _duplicate_asset_keep_score(with_cover) > _duplicate_asset_keep_score(bare)
    older = SimpleNamespace(id=1, cover="https://x/a.jpg", url="", params={})
    newer = SimpleNamespace(id=99, cover="https://x/a.jpg", url="", params={})
    assert _duplicate_asset_keep_score(older) > _duplicate_asset_keep_score(newer)


def test_voice_like_character_names_are_skipped():
    assert _is_voice_like_character_name("现代科普旁白（声音）")
    assert _is_voice_like_character_name("现代科普旁白 (声音)")
    assert _is_voice_like_character_name("李白音色")
    assert _is_voice_like_character_name("旁白音色")
    assert not _is_voice_like_character_name("李白")
    assert not _is_voice_like_character_name("现代科普旁白")
    assert not _is_voice_like_character_name("故乡（幻象）")
    assert _character_name_for_seed("现代科普旁白（声音）") == "现代科普旁白"
    assert _character_name_for_seed("李白音色") == "李白"
    assert _character_name_for_seed("旁白音色") is None
    assert _character_name_for_seed("李白") == "李白"


def test_extract_cast_skips_voice_like_names():
    bodies = ["出场人物：李白、现代科普旁白、现代科普旁白（声音）、故乡（幻象）"]
    assert _extract_cast_names_from_bodies(bodies) == [
        "李白",
        "现代科普旁白",
        "故乡（幻象）",
    ]
