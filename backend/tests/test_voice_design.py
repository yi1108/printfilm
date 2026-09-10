"""音色设计工具函数测试。"""

from app.services.drama.voice_design import (
    clamp_voice_design_prompt,
    parse_speaker_pool,
    resolve_speaker_slot,
    voice_design_enabled,
)


def test_parse_speaker_pool() -> None:
    assert parse_speaker_pool("S_a, S_b ,zh_x") == ["S_a", "S_b"]


def test_resolve_speaker_slot_reuses_designed() -> None:
    assert resolve_speaker_slot(3, {"designedSpeakerId": "S_keep"}, ["S_a", "S_b"]) == "S_keep"


def test_resolve_speaker_slot_picks_from_pool() -> None:
    slot = resolve_speaker_slot(1, {}, ["S_a", "S_b", "S_c"])
    assert slot in {"S_a", "S_b", "S_c"}


def test_clamp_voice_design_prompt() -> None:
    prompt, text = clamp_voice_design_prompt("a" * 250, "b" * 400)
    assert len(prompt) == 200
    assert len(text) == 300


def test_voice_design_enabled_requires_pool_and_auth(monkeypatch) -> None:
    from app.config import Settings

    cfg = Settings(
        volc_tts_voice_design_speaker_ids="S_test",
        volc_tts_api_key="key",
    )
    assert voice_design_enabled(cfg) is True

    cfg2 = Settings(volc_tts_voice_design_speaker_ids="S_test")
    assert voice_design_enabled(cfg2) is False
