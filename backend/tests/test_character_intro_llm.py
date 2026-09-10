"""人物介绍 LLM 补齐。"""

import asyncio
from unittest.mock import AsyncMock, patch

from types import SimpleNamespace

from app.services.drama.build_fragments import build_character_binding
from app.services.drama.character_intro_llm import (
    _parse_intro_response,
    collect_names_needing_intro,
    prepare_character_intro_overrides,
)


def test_parse_intro_response():
    raw = {"intros": {"鲧": "治水先驱/因盗息壤被诛", "舜": "尧帝禅让之君"}}
    parsed = _parse_intro_response(raw, ["鲧", "舜", "禹"])
    assert parsed["鲧"] == "治水先驱/因盗息壤被诛"
    assert parsed["舜"] == "尧帝禅让之君"
    assert "禹" not in parsed


def test_collect_names_needing_intro_skips_stub_identity():
    asset = SimpleNamespace(
        id=1,
        type="character",
        name="鲧",
        params={"title": "出场人物", "identityBackground": "剧本分集出场人物「鲧」"},
    )
    missing = collect_names_needing_intro([asset], summary={"characters": []})
    assert missing == ["鲧"]


def test_prepare_character_intro_overrides_uses_llm():
    asset = SimpleNamespace(
        id=1,
        type="character",
        name="鲧",
        params={"title": "出场人物", "identityBackground": "剧本分集出场人物「鲧」"},
    )
    mock_llm = AsyncMock(
        return_value={"intros": {"鲧": "治水先驱/盗息壤被诛"}},
    )
    with patch(
        "app.services.drama.character_intro_llm.drama_chat_json",
        mock_llm,
    ):
        overrides = asyncio.run(
            prepare_character_intro_overrides(
                [asset],
                summary={"storyType": "古风神话", "synopsis": "禹承父志治水。"},
                episode_bodies=[],
            )
        )
    assert overrides.get("鲧") == "治水先驱/盗息壤被诛"
    binding = build_character_binding(
        "鲧",
        asset,
        summary={"characters": []},
        intro_overrides=overrides,
    )
    assert binding["introText"] == "治水先驱/盗息壤被诛"
