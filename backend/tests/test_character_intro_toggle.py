"""人物介绍叠字开关与字幕开关独立。"""

from app.services.drama.build_fragments import CHARACTER_INTRO_CUE, plan_fragments_from_scene
from app.services.drama.build_seedance_generate_body import (
    build_seedance_prompt_text,
    resolve_episode_character_intro,
)
from app.services.seedance_segments import strip_character_intro_cues


def test_resolve_episode_character_intro():
    assert resolve_episode_character_intro({"characterIntroMode": "off"}) is False
    assert resolve_episode_character_intro({"characterIntroMode": "model"}) is True
    assert resolve_episode_character_intro({"characterIntroEnabled": False}) is False
    assert resolve_episode_character_intro({}) is False


def test_strip_character_intro_cues():
    text = (
        f"{CHARACTER_INTRO_CUE}小宇｜好奇心队长\n"
        "【BGM：轻柔】\n"
        "@duration:4\n"
        "【对白·慢速清晰】小宇：你好。"
    )
    out = strip_character_intro_cues(text)
    assert "人物介绍" not in out
    assert "【BGM：轻柔】" in out
    assert "小宇：你好" in out


def test_plan_fragments_omits_character_intro_when_disabled():
    chunks = plan_fragments_from_scene(
        "日外 公园。\n小宇看着米米。",
        {"sceneName": "公园"},
        None,
        [
            {
                "name": "小宇",
                "assetId": 1,
                "important": True,
                "introText": "好奇心队长",
            }
        ],
        include_character_intro=False,
    )
    joined = "\n".join(c for c, _ in chunks)
    assert "人物介绍" not in joined


def test_prompt_strips_intro_when_disabled():
    content = f"{CHARACTER_INTRO_CUE}小宇｜好奇心队长\n【对白·慢速清晰】小宇：嗨。"
    prompt = build_seedance_prompt_text(content, [], burn_subtitles=True, character_intro=False)
    assert CHARACTER_INTRO_CUE not in prompt
    assert "小宇｜好奇心队长" not in prompt
    assert "小宇：嗨" in prompt
