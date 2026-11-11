"""扩写语言、提示、API 参数透传均为无数据库/无上游网络单元测试。"""

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.schemas import ContentExpandRequest
from app.services.ark import ArkGateway
from app.services.content_expansion import topic_language


@pytest.fixture
def gateway(monkeypatch):
    """默认走真实分支，但由测试替换 LLM 入口。"""
    monkeypatch.setattr(ArkGateway, "mock", property(lambda self: False))
    return ArkGateway()


@pytest.mark.parametrize("mode", ["theme", "script"])
@pytest.mark.parametrize("topic", ["Why do stars twinkle?", "为什么星星会闪烁？", "用英文讲述为什么星星闪烁"])
async def test_prompt_preserves_original_language_and_separates_parameters(gateway, monkeypatch, mode, topic):
    """捕获实际模型消息，确保原始输入和语言/语速规则完整且参数不混入主题。"""
    response = {"title": "自然的中文标题", "content": "完整的中文解说。"} if topic_language(topic) == "zh" else {"title": "A natural title", "content": "A complete explanation."}
    chat = AsyncMock(return_value=json.dumps(response))
    monkeypatch.setattr("app.services.ark.chat_completions", chat)
    await gateway.expand_content(topic, mode, target_duration_sec=90, style="电影感 cinematic")
    system, user = chat.call_args.args
    assert json.loads(user) == {
        "original_topic": topic,
        "parameters": {"target_duration_sec": 90, "style": "电影感 cinematic"},
    }
    if topic_language(topic) == 'en':
        assert 'required output language is ENGLISH' in system
        assert '120-160 English words per minute' in system
        assert 'even when the style parameter contains Chinese' in system
    else:
        for rule in ["英文输入英文输出", "中文输入中文输出", "混合输入按主体", "目标语言", "模板名", "4-12 个完整单词"]:
            assert rule in system
        if mode == "script":
            assert "每分钟 180-240 汉字" in system
        else:
            assert "25-60 个单词" in system


async def test_wrong_language_is_corrected_before_success(gateway, monkeypatch):
    """复现英文小猫主题加中文风格返回中文，纠正后才可成功。"""
    english = {"title": "A New Friend in the Rain", "content": "A shy kitten meets a friendly puppy on a rainy day."}
    chat = AsyncMock(side_effect=[json.dumps({"title": "雨天里的新朋友", "content": "一只害羞的小猫在雨天结交朋友。"}), json.dumps(english)])
    monkeypatch.setattr("app.services.ark.chat_completions", chat)
    result = await gateway.expand_content("A shy kitten makes a new friend on a rainy day", "script", target_duration_sec=60, style="3D 动画")
    assert result == english
    assert chat.await_count == 2


async def test_repeated_wrong_language_fails_instead_of_returning_chinese(gateway, monkeypatch):
    """纠正仍失败时不能把错误语言标记为成功。"""
    chat = AsyncMock(return_value=json.dumps({"title": "雨天朋友", "content": "中文故事正文。"}))
    monkeypatch.setattr("app.services.ark.chat_completions", chat)
    with pytest.raises(ValueError, match="输入语言"):
        await gateway.expand_content("A shy kitten makes a new friend on a rainy day", "script", style="3D 动画")
    assert chat.await_count == 2


async def test_legacy_call_and_long_english_result_are_not_truncated(gateway, monkeypatch):
    """旧参数调用兼容；英文标题及超过 100 字符的主题不被汉字上限裁断。"""
    title = "Why Ordinary Everyday Objects Reveal Extraordinary Secrets About Our Universe"
    content = "Explain why stars appear to twinkle to curious beginners, using the atmosphere and changing light paths as everyday examples without confusing stars with planets."
    chat = AsyncMock(return_value=json.dumps({"title": title, "content": content}))
    monkeypatch.setattr("app.services.ark.chat_completions", chat)
    assert await gateway.expand_content("Why do stars twinkle?", "theme") == {"title": title, "content": content}
    assert json.loads(chat.call_args.args[1])["parameters"] == {"target_duration_sec": None, "style": None}


@pytest.mark.parametrize("mode", ["theme", "script"])
@pytest.mark.parametrize("topic,chinese", [("Why do stars twinkle?", False), ("为什么星星闪烁", True)])
async def test_mock_language(gateway, monkeypatch, mode, topic, chinese):
    """mock 仍校验模型路由，但英文文案不会掺中文模板。"""
    monkeypatch.setattr(ArkGateway, "mock", property(lambda self: True))
    route = AsyncMock()
    monkeypatch.setattr("app.services.ark.resolve_upstream_model", lambda *args: None)
    monkeypatch.setattr("app.services.ark.chat_completions", route)
    result = await gateway.expand_content(topic, mode, target_duration_sec=30, style="friendly")
    assert bool(re.search(r"[\u3400-\u9fff]", result["content"])) is chinese
    assert result["title"]
    route.assert_not_called()


@pytest.mark.parametrize("raw", ["not JSON", "{broken}", "[]", "null", '{"title":"Only title"}', '{"content": 42}'])
@pytest.mark.parametrize("mode", ["theme", "script"])
async def test_invalid_response_fallback_keeps_english(gateway, monkeypatch, raw, mode):
    """所有解析回退路径保留英文语言和请求时长。"""
    monkeypatch.setattr("app.services.ark.chat_completions", AsyncMock(return_value=raw))
    result = await gateway.expand_content("How does rain form?", mode, target_duration_sec=120)
    assert not re.search(r"[\u3400-\u9fff]", result["title"] + result["content"])
    if mode == "script":
        assert 270 <= len(result["content"].split()) <= 310


@pytest.mark.parametrize("topic,chinese", [
    ("雨是如何形成的？", True),
    ("用英文讲述雨是如何形成的", False),
    ("Explain rain, write in Chinese", True),
])
def test_fallback_respects_chinese_and_explicit_language(gateway, topic, chinese):
    """中文和显式目标语言对 mock 与损坏 JSON 使用相同语言策略。"""
    result = gateway._parse_expand_content("invalid", topic, "theme")
    assert bool(re.search(r"[\u3400-\u9fff]", result["title"])) is chinese
    assert bool(re.search(r"[\u3400-\u9fff]", result["content"])) is chinese


@pytest.mark.parametrize("topic", ["How does rain form?", "雨是如何形成的？"])
def test_mock_script_duration_scales(gateway, topic):
    """mock 不再写死三分钟，目标时长控制近似篇幅。"""
    short = gateway._mock_expand_content(topic, "script", target_duration_sec=15)
    long = gateway._mock_expand_content(topic, "script", target_duration_sec=120)
    assert len(long["content"]) > len(short["content"]) * 3
    assert "三分钟" not in short["content"]


@pytest.mark.parametrize("topic,expected", [
    ("Why do stars twinkle?", "en"), ("为什么星星闪烁", "zh"),
    ("解释 AI 如何改变我们的日常生活", "zh"), ("Explain AI and its impact on 日常生活", "en"),
    ("用英文讲述为什么星星闪烁", "en"), ("Explain stars, write in Chinese", "zh"),
    ("目标语言：English，介绍星星", "en"),
])
def test_fallback_language_selection(topic, expected):
    """中英主体和显式目标语言在离线回退中保持一致。"""
    assert topic_language(topic) == expected


@pytest.mark.parametrize("duration", [5, 600, None])
def test_request_accepts_duration_boundaries(duration):
    """有效请求范围含两端点，并保持旧请求默认值。"""
    body = ContentExpandRequest(topic="science", target_duration_sec=duration, style="a" * 200)
    assert body.target_duration_sec == duration
    assert ContentExpandRequest(topic="science").style is None


@pytest.mark.parametrize("kwargs", [{"target_duration_sec": 4}, {"target_duration_sec": 601}, {"target_duration_sec": 5.5}, {"style": "a" * 201}])
def test_request_rejects_invalid_options(kwargs):
    """请求参数在 schema 层校验，无需数据库。"""
    with pytest.raises(ValidationError):
        ContentExpandRequest(topic="science", **kwargs)


async def test_api_forwards_options_without_database(monkeypatch):
    """直接调用端点，替换计费执行器验证 keyword-only 透传。"""
    from app.api import projects

    expand = AsyncMock(return_value={"title": "Stars", "content": "Why stars twinkle."})
    monkeypatch.setattr(projects, "get_ark", lambda: SimpleNamespace(expand_content=expand))
    monkeypatch.setattr(projects, "record_llm_chat_line", AsyncMock())

    async def run(_db, _user, **kwargs):
        """执行闭包而不触达任务平台或计费数据库。"""
        return SimpleNamespace(id=123), await kwargs["executor"]()

    monkeypatch.setattr(projects, "run_billed_ephemeral", run)
    result = await projects.expand_content(
        ContentExpandRequest(topic=" Stars ", mode="script", target_duration_sec=45, style="幽默"),
        db=object(), user=SimpleNamespace(id=7),
    )
    expand.assert_awaited_once_with("Stars", "script", target_duration_sec=45, style="幽默")
    assert result.task_id == 123
