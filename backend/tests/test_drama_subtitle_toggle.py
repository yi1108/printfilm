"""分镜字幕开关：关闭时不再注入字幕 cue；后期模式禁止 Seedance 烧录。"""

from app.services.drama.build_fragments import DRAMA_SUBTITLE_CUE, plan_fragments_from_scene
from app.services.drama.build_seedance_generate_body import (
    build_seedance_prompt_text,
    resolve_episode_burn_subtitles,
)
from app.services.drama.fragment_plan_prompt import build_fragment_plan_user_prompt
from app.services.seedance_segments import (
    build_seedance_production_section,
    strip_model_burn_subtitle_cues,
)


def test_plan_fragments_from_scene_omits_subtitle_cue_when_disabled():
    chunks = plan_fragments_from_scene(
        "旁白：河岸边风声渐起。",
        meta={},
        scene_asset_id=None,
        character_bindings=[],
        include_subtitles=False,
    )
    content, _duration = chunks[0]
    assert DRAMA_SUBTITLE_CUE not in content
    assert "同步字幕" not in content
    assert "旁白" in content


def test_plan_fragments_from_scene_omits_dialogue_subtitle_when_disabled():
    chunks = plan_fragments_from_scene(
        "阿禹：大家先后退。",
        meta={},
        scene_asset_id=None,
        character_bindings=[],
        include_subtitles=False,
    )
    content, _duration = chunks[0]
    assert "【对白·慢速清晰】" in content
    assert "同步字幕" not in content


def test_fragment_plan_user_prompt_marks_no_subtitles():
    prompt = build_fragment_plan_user_prompt(
        episode_name="大禹治水",
        episode_body="禹来到河边。",
        asset_catalog=[],
        include_subtitles=False,
    )
    assert "字幕需求：不要字幕" in prompt
    assert "不要写任何“字幕 / 叠字 / 同步字幕 / 字卡”等提示" in prompt


def test_resolve_episode_burn_subtitles_post_mode():
    assert resolve_episode_burn_subtitles({"subtitleMode": "post"}) is False
    assert resolve_episode_burn_subtitles({"subtitleMode": "model"}) is True
    assert resolve_episode_burn_subtitles({"subtitleEnabled": False}) is False


def test_strip_model_burn_subtitle_cues_keeps_dialogue():
    raw = (
        "【字幕：底部居中·简体中文·逐句轮换·与口播同步】\n"
        "@duration:4\n"
        "【对白·慢速清晰·同步字幕】禹：水患未平。"
    )
    cleaned = strip_model_burn_subtitle_cues(raw)
    assert "【字幕" not in cleaned
    assert "同步字幕" not in cleaned
    assert "【对白·慢速清晰】禹：水患未平。" in cleaned


def test_production_section_post_mode_forbids_burn():
    script = "@duration:4\n【对白·慢速清晰】禹：水患未平。"
    section = build_seedance_production_section(script, burn_subtitles=False)
    assert "禁止在画面内烧录字幕" in section
    assert "烧录简体中文字幕" not in section


def test_seedance_prompt_text_post_mode_strips_cues():
    content = (
        "【字幕：底部居中·简体中文·逐句轮换·与口播同步】\n"
        "@duration:4\n"
        "【对白·慢速清晰·同步字幕】禹：水患未平。"
    )
    prompt = build_seedance_prompt_text(content, [], burn_subtitles=False)
    assert "【字幕" not in prompt
    assert "同步字幕" not in prompt
    assert "禁止在画面内烧录字幕" in prompt
