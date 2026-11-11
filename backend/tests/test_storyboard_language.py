"""分镜原始素材语言回归：无数据库写入、无真实模型调用。"""
import json
from unittest.mock import AsyncMock

import pytest

from app.services.ark import ArkGateway
from app.services import seedance_segments as seg


def draft(language):
    """覆盖所有面向用户和模型的自然语言字段。"""
    text = "Blue light scatters through the air." if language == "en" else "蓝光在空气中散射。"
    visual = "Wide shot of sunlight crossing the atmosphere." if language == "en" else "远景，阳光穿过大气层。"
    title = "Why the Sky Wears Blue" if language == "en" else "天空为什么是蓝色"
    return {"character_bible": visual, "bgm_lock": text, "shots": [{
        "title": title, "subtitle": text, "text": text, "img_prompt": visual,
        "video_prompt": visual, "camera": visual, "bgm": text,
        "segments": [{"kind": "visual", "duration": 3, "text": visual},
                     {"kind": "narration", "duration": 3, "text": text}],
    }]}


@pytest.mark.parametrize("mode", ["full", "image_text"])
@pytest.mark.parametrize("language", ["en", "zh"])
async def test_original_source_controls_all_fields(monkeypatch, mode, language):
    """中文模板和 addon 不影响英文原文，中文原文仍用中文。"""
    monkeypatch.setattr(ArkGateway, "mock", property(lambda self: False))
    payload = draft(language)
    chat = AsyncMock(return_value=json.dumps(payload))
    monkeypatch.setattr("app.services.ark.chat_completions", chat)
    source = "Why the Sky Wears Blue" if language == "en" else "天空为什么是蓝色"
    result = await ArkGateway().chat_storyboard(source, "script", "中国水墨风格", "所有输出必须是中文", 4, 12, 12, pipeline_mode=mode)
    system = chat.call_args.args[0]
    assert "MANDATORY OUTPUT LANGUAGE: " + ("English" if language == "en" else "Simplified Chinese") in system
    assert system.rfind("MANDATORY OUTPUT LANGUAGE") > system.rfind("所有输出必须是中文")
    shot = result.shots[0]
    assert shot.overlay_title == payload["shots"][0]["title"]
    assert shot.text == payload["shots"][0]["text"]
    assert shot.img_prompt == payload["shots"][0]["img_prompt"]
    assert "简体中文" not in shot.segment_script
    assert seg.narration_from_script(shot.segment_script) == shot.text
    prompt = seg.build_seedance_prompt(shot.segment_script, burn_subtitles=True)
    assert "简体中文字幕" not in prompt
    assert "英文原文必须英文配音和英文字幕" in prompt


@pytest.mark.parametrize("mode", ["full", "image_text"])
@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("field", ["all", "title", "text", "visual_segment", "narration_segment", "img_prompt", "camera"])
async def test_wrong_language_cannot_succeed(monkeypatch, mode, language, field):
    """任意错误语言字段明确失败，不用中文 fallback 冒充成功。"""
    monkeypatch.setattr(ArkGateway, "mock", property(lambda self: False))
    payload, wrong = draft(language), draft("zh" if language == "en" else "en")
    if field == "all":
        payload = wrong
    elif field.endswith("_segment"):
        index = 0 if field == "visual_segment" else 1
        payload["shots"][0]["segments"][index] = wrong["shots"][0]["segments"][index]
    else:
        payload["shots"][0][field] = wrong["shots"][0][field]
    monkeypatch.setattr("app.services.ark.chat_completions", AsyncMock(return_value=json.dumps(payload)))
    with pytest.raises(RuntimeError, match="语言与原始素材不一致"):
        await ArkGateway().chat_storyboard("Why the Sky Wears Blue" if language == "en" else "天空为什么是蓝色", "script", "水墨", "中文模板", 4, 12, 12, pipeline_mode=mode)


def test_english_legacy_defaults_and_script_edits():
    """缺少可选字段时不产生中文标题、运镜或字幕语言要求。"""
    result = ArkGateway()._parse_storyboard(json.dumps({"shots": [{"text": "Blue light scatters.", "video_prompt": "Wide shot of the sky."}]}), "中文模板", 4, 12, 12, source_text="Why the Sky Wears Blue")
    shot = result.shots[0]
    assert shot.overlay_title == "Scene 1"
    assert shot.camera == "Slow pan"
    assert shot.bgm == "Calm"
    assert shot.text == "Blue light scatters."
    edited = seg.apply_segment_script_edit(shot.segment_script)
    assert edited["narration"] == shot.text
    assert "简体中文" not in edited["segment_script"]
