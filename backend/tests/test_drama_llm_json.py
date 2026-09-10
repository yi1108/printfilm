"""drama LLM JSON 解析单测。"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.drama.llm import _ensure_json_word_in_prompt, _extract_json, drama_chat_json


def test_extract_json_plain_object():
    data = _extract_json('{"oneLineStory": "测试"}')
    assert data["oneLineStory"] == "测试"


def test_extract_json_strips_fences():
    raw = '```json\n{"episodeCount": 12}\n```'
    data = _extract_json(raw)
    assert data["episodeCount"] == 12


def test_extract_json_repairs_trailing_comma():
    raw = '{"characters": [{"name": "沈令仪",},], "synopsis": "test",}'
    data = _extract_json(raw)
    assert data["characters"][0]["name"] == "沈令仪"
    assert data["synopsis"] == "test"


def test_extract_json_repairs_smart_quotes():
    raw = '{"oneLineStory": "将门孤女"}'
    data = _extract_json(raw)
    assert "将门孤女" in data["oneLineStory"]


def test_extract_json_raises_on_invalid_payload():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("not json at all")


def test_ensure_json_word_appends_when_missing():
    system, user = _ensure_json_word_in_prompt("你是编剧", "写第1集")
    assert "json" in f"{system}\n{user}".lower()
    assert "写第1集" in user


def test_ensure_json_word_keeps_existing():
    system, user = _ensure_json_word_in_prompt("输出 JSON", "写第1集")
    assert system == "输出 JSON"
    assert user == "写第1集"


@pytest.mark.asyncio
async def test_drama_chat_json_injects_json_before_response_format():
    """无 json 字样时应注入后再带 response_format 调用，避免 DeepSeek 400。"""
    captured: dict = {}

    async def _fake_chat(system, user, **kwargs):
        captured["system"] = system
        captured["user"] = user
        captured["response_format"] = kwargs.get("response_format")
        return '{"ok": true}'

    with patch("app.services.drama.llm.chat_completions", new=AsyncMock(side_effect=_fake_chat)):
        data = await drama_chat_json("你是编剧", "写大纲")
    assert data == {"ok": True}
    assert "json" in f"{captured['system']}\n{captured['user']}".lower()
    assert captured["response_format"] == {"type": "json_object"}
