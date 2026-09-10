"""漫剧音色 speaker 推断与试听文案测试。"""

from app.services.drama.voice_synthesis import (
    build_voice_sample_line_short,
    build_voice_sample_text,
    normalize_character_name,
)
from app.services.ark import ArkGateway
from app.services.voices import infer_drama_speaker_from_prompt


def test_normalize_character_name_strips_suffix() -> None:
    assert normalize_character_name("禹音色") == "禹"
    assert normalize_character_name("伯益") == "伯益"


def test_build_voice_sample_line_short() -> None:
    assert build_voice_sample_line_short("禹") == "你好，我是禹。"
    assert build_voice_sample_line_short("很长的角色名称测试") == "你好，我是很长的角色名称测。"


def test_build_voice_sample_text_short_mode() -> None:
    assert build_voice_sample_text("任意描述", "伯益", short=True) == "你好，我是伯益。"


def test_infer_drama_speaker_differs_by_role() -> None:
    yu = infer_drama_speaker_from_prompt(
        "中年男性，治水领袖，声线浑厚庄重",
        character_name="禹",
        asset_id=1,
    )
    boyi = infer_drama_speaker_from_prompt(
        "青年男性，儒雅谋士，声线清朗温和",
        character_name="伯益",
        asset_id=2,
    )
    elder = infer_drama_speaker_from_prompt(
        "老年男性，部落族老，声线沙哑沉稳",
        character_name="部落族老",
        asset_id=3,
    )
    assert yu != boyi or yu != elder
    assert all(s.startswith("zh_") for s in (yu, boyi, elder))


def test_build_voice_sample_text_uses_role_lines() -> None:
    yu = build_voice_sample_text("治水领袖，浑厚男声", "禹", short=False)
    crowd = build_voice_sample_text("百姓群像，朴实女声", "两岸百姓", short=False)
    assert "禹" in yu
    assert "两岸百姓" in crowd
    assert yu != crowd


def test_build_tts_additions_includes_context_texts() -> None:
    raw = ArkGateway._build_tts_additions("zh_female_vv_uranus_bigtts", "清亮少女音")
    assert raw is not None
    assert "context_texts" in raw
    assert "清亮少女音" in raw


def test_build_tts_additions_speaker_clone() -> None:
    raw = ArkGateway._build_tts_additions("S_abc123", "低沉男声")
    assert raw is not None
    assert "model_type" in raw
    assert "context_texts" in raw

