"""LLM 补齐人物介绍叠字（stub 角色 / 摘要缺小传时）。"""

from __future__ import annotations

import logging
from typing import Any

from app.services.drama.build_fragments import (
    build_summary_character_lookup,
    infer_character_intro_text,
    _find_summary_character,
    _is_generic_intro_text,
    _merge_params_with_summary,
    _shorten_intro,
)
from app.services.drama.llm import drama_chat_json

logger = logging.getLogger(__name__)

SUMMARY_TEXT_MAX = 3500
BODY_SAMPLE_MAX = 4000
BODY_PER_EPISODE_MAX = 1200

CHARACTER_INTRO_SYSTEM = """你是影视编剧助理，为短剧/漫剧角色写「人物介绍叠字」短文案。

用途：角色本剧首次出场时，画面在**该角色身旁**叠字一行「角色名｜身份头衔」（非口播、非底部字幕）。

要求：
1. 每条介绍 8~24 个汉字，突出身份、地位或与主线关系的一句话
2. 风格贴合故事类型与剧本语境，可用「/」连接两个短语（如「治水首领/夏朝始祖」）
3. 禁止占位废话：「出场人物」「剧本分集出场人物」「配角」等
4. 只写给定名单中的角色；不要编造名单外人物

输出严格 JSON（不要 markdown）：
{"intros": {"角色名": "叠字介绍文案"}}
"""


def _summary_blob(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict):
        return ""
    parts: list[str] = []
    for key in ("storyType", "oneLineStory", "coreHook", "synopsis"):
        val = str(summary.get(key) or "").strip()
        if val:
            parts.append(val)
    for ch in summary.get("characters") or []:
        if not isinstance(ch, dict):
            continue
        name = str(ch.get("name") or "").strip()
        if not name:
            continue
        bits = [
            str(ch.get("roleType") or "").strip(),
            str(ch.get("title") or "").strip(),
            str(ch.get("identityBackground") or "").strip(),
        ]
        line = " ".join(b for b in bits if b)
        if line:
            parts.append(f"{name}：{line}")
    blob = "\n".join(parts)
    return blob[:SUMMARY_TEXT_MAX]


def _bodies_sample(episode_bodies: list[str] | None) -> str:
    if not episode_bodies:
        return ""
    chunks: list[str] = []
    used = 0
    for body in episode_bodies:
        text = (body or "").strip()
        if not text:
            continue
        piece = text[:BODY_PER_EPISODE_MAX]
        if used + len(piece) > BODY_SAMPLE_MAX:
            piece = piece[: max(0, BODY_SAMPLE_MAX - used)]
        if not piece:
            break
        chunks.append(piece)
        used += len(piece)
    return "\n---\n".join(chunks)


def _build_intro_user_prompt(
    names: list[str],
    *,
    summary: dict[str, Any] | None,
    episode_bodies: list[str] | None,
    story_type: str | None,
) -> str:
    genre = (story_type or "").strip()
    if not genre and isinstance(summary, dict):
        genre = str(summary.get("storyType") or "").strip()
    lines = [
        "请为以下角色各写一条人物介绍叠字文案：",
        "、".join(names),
    ]
    if genre:
        lines.append(f"故事类型：{genre}")
    summary_text = _summary_blob(summary)
    if summary_text:
        lines.append(f"剧本摘要：\n{summary_text}")
    body_text = _bodies_sample(episode_bodies)
    if body_text:
        lines.append(f"分集剧本节选：\n{body_text}")
    return "\n\n".join(lines)


def _parse_intro_response(raw: Any, names: list[str]) -> dict[str, str]:
    allowed = {n.strip() for n in names if n.strip()}
    result: dict[str, str] = {}
    if isinstance(raw, dict):
        intros = raw.get("intros")
        if isinstance(intros, dict):
            for key, val in intros.items():
                name = str(key or "").strip()
                intro = _shorten_intro(str(val or ""), max_len=28)
                if name in allowed and intro and not _is_generic_intro_text(intro):
                    result[name] = intro
        for key in ("characters", "items"):
            items = raw.get(key)
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    intro = _shorten_intro(
                        str(item.get("intro") or item.get("title") or item.get("introText") or ""),
                        max_len=28,
                    )
                    if name in allowed and intro and not _is_generic_intro_text(intro):
                        result[name] = intro
    return result


async def llm_enrich_character_intros(
    names: list[str],
    *,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
    story_type: str | None = None,
) -> dict[str, str]:
    """批量 LLM 生成人物介绍叠字；失败时返回空 dict。"""
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        n = str(name or "").strip()
        if n and n not in seen:
            seen.add(n)
            unique.append(n)
    if not unique:
        return {}
    user = _build_intro_user_prompt(
        unique,
        summary=summary,
        episode_bodies=episode_bodies,
        story_type=story_type,
    )
    try:
        raw = await drama_chat_json(
            CHARACTER_INTRO_SYSTEM,
            user,
            temperature=0.35,
            max_tokens=1024,
        )
        parsed = _parse_intro_response(raw, unique)
        logger.info("LLM 人物介绍补齐 count=%s names=%s", len(parsed), list(parsed.keys()))
        return parsed
    except Exception:  # noqa: BLE001
        logger.exception("LLM 人物介绍补齐失败 names=%s", unique)
        return {}


def collect_names_needing_intro(
    character_assets: list[Any],
    *,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
) -> list[str]:
    """规则链路仍缺介绍文案的角色名（保序）。"""
    lookup = build_summary_character_lookup(summary)
    missing: list[str] = []
    seen: set[str] = set()
    for asset in character_assets:
        name = str(getattr(asset, "name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        params = getattr(asset, "params", None) or {}
        if not isinstance(params, dict):
            params = {}
        merged = _merge_params_with_summary(params, _find_summary_character(lookup, name))
        if infer_character_intro_text(name, merged, summary, episode_bodies):
            continue
        missing.append(name)
    return missing


async def prepare_character_intro_overrides(
    character_assets: list[Any],
    *,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
    story_type: str | None = None,
) -> dict[str, str]:
    """先规则推断，缺的再一次性 LLM 补齐。"""
    names = collect_names_needing_intro(
        character_assets,
        summary=summary,
        episode_bodies=episode_bodies,
    )
    if not names:
        return {}
    return await llm_enrich_character_intros(
        names,
        summary=summary,
        episode_bodies=episode_bodies,
        story_type=story_type,
    )
