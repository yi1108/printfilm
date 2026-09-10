"""单集 LLM 分镜：调用模型规划，再规范化为可落库分镜草稿。"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.drama.build_fragments import (
    FRAGMENT_DURATION_MIN,
    FRAGMENT_SOFT_MAX,
    FRAGMENT_TOTAL_MAX,
    _build_character_intro_lines,
    _build_production_cues,
    _strip_subtitle_instruction,
    _clamp_duration,
    _estimate_line_duration,
    _find_asset_by_name,
    _format_narrative_line,
    _inject_character_mentions,
    build_character_binding,
    build_summary_character_lookup,
)
from app.services.drama.fragment_plan_prompt import (
    FRAGMENT_PLAN_SYSTEM_PROMPT,
    build_fragment_plan_user_prompt,
)
from app.services.agent.runner import run_task_json

logger = logging.getLogger(__name__)


def build_asset_catalog(assets: list[Any]) -> list[dict[str, Any]]:
    # 压缩资产目录给 LLM（角色/场景/道具；素材已停用）
    catalog: list[dict[str, Any]] = []
    for asset in assets:
        kind = str(getattr(asset, "type", "") or "")
        if kind not in {"character", "scene", "prop"}:
            continue
        params = getattr(asset, "params", None) or {}
        if not isinstance(params, dict):
            params = {}
        catalog.append(
            {
                "id": int(asset.id),
                "type": kind,
                "name": str(getattr(asset, "name", "") or ""),
                "roleType": str(params.get("roleType") or "").strip() or None,
                "title": str(params.get("title") or "").strip() or None,
            }
        )
    return catalog


def _coerce_name_list(raw: Any) -> list[str]:
    # character_names / prop_names 等字段统一为去空白名称列表
    if isinstance(raw, str):
        return [p.strip() for p in re.split(r"[、，,/|]", raw) if p.strip()]
    if isinstance(raw, list):
        return [str(n).strip() for n in raw if str(n).strip()]
    return []


def _match_prop_material_bindings(
    names: list[str],
    candidates: list[Any],
    *,
    body_blob: str = "",
) -> list[dict[str, Any]]:
    # 按名匹配道具/素材；正文兜底扫描未点名但出现在行文中的资产
    bindings: list[dict[str, Any]] = []
    seen: set[int] = set()
    for name in names:
        asset = _find_asset_by_name(candidates, str(name))
        if asset is None:
            continue
        aid = int(asset.id)
        if aid in seen:
            continue
        seen.add(aid)
        bindings.append(
            {
                "name": str(getattr(asset, "name", "") or name).strip() or str(name),
                "assetId": aid,
            }
        )
    if body_blob:
        for asset in candidates:
            name = str(getattr(asset, "name", "") or "").strip()
            if not name or name not in body_blob:
                continue
            aid = int(asset.id)
            if aid in seen:
                continue
            seen.add(aid)
            bindings.append({"name": name, "assetId": aid})
    return bindings


def _build_character_bindings(
    character_names: list[str],
    character_assets: list[Any],
    *,
    summary_lookup: dict[str, dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
    intro_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    # 按名匹配角色资产，附带介绍文案与是否重要（摘要补全 stub）
    bindings: list[dict[str, Any]] = []
    for character_name in character_names:
        character_asset = _find_asset_by_name(character_assets, str(character_name))
        if character_asset is None:
            continue
        bindings.append(
            build_character_binding(
                str(character_name),
                character_asset,
                summary_lookup=summary_lookup,
                summary=summary,
                episode_bodies=episode_bodies,
                intro_overrides=intro_overrides,
            )
        )
    return bindings


def _coerce_lines(raw: Any) -> list[str]:
    # lines / content 字段统一成非空文本行
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        return [ln.strip() for ln in raw.replace("\r\n", "\n").split("\n") if ln.strip()]
    return []


def _clamp_fragment_duration(seconds: int, line_count: int) -> int:
    # 单镜时长钳制；无模型给值时按行数粗估
    if seconds <= 0:
        seconds = max(FRAGMENT_DURATION_MIN, min(FRAGMENT_TOTAL_MAX, line_count * 3 or 8))
    return min(max(int(seconds), 4), FRAGMENT_TOTAL_MAX)


def _truthy_opening_flag(
    item: dict[str, Any],
    index: int,
    *,
    allow_opening: bool = True,
) -> bool:
    # 首条默认开幕；或模型显式 is_opening；续拆时禁止开幕
    if not allow_opening:
        return False
    if index == 0:
        return True
    flag = item.get("is_opening")
    if flag is None:
        flag = item.get("isOpening")
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, (int, float)):
        return bool(flag)
    if isinstance(flag, str):
        return flag.strip().lower() in {"1", "true", "yes", "opening", "开幕"}
    return False


def _build_opening_cue_lines(
    *,
    episode_number: int | None,
    episode_name: str | None,
    project_title: str | None,
    story_type: str | None,
    one_line_story: str | None,
    background_blurb: str | None,
) -> list[str]:
    # 开幕叠字：集号 / 集名 / 剧名 / 背景简介
    cues: list[str] = []
    ep_no = int(episode_number or 0)
    title = (episode_name or "").strip()
    series = (project_title or "").strip()
    if ep_no > 0 and title:
        cues.append(f"【片头·集号叠字】第{ep_no}集｜{title}")
    elif ep_no > 0:
        cues.append(f"【片头·集号叠字】第{ep_no}集")
    elif title:
        cues.append(f"【片头·集名叠字】{title}")
    if series:
        cues.append(f"【片头·剧名叠字】{series}")
    genre = (story_type or "").strip()
    if genre:
        cues.append(f"【片头·类型标注】{genre}")
    bg = (background_blurb or one_line_story or "").strip()
    if bg:
        short = re.split(r"[。！？]", bg, maxsplit=1)[0].strip() or bg
        if len(short) > 48:
            short = short[:47] + "…"
        cues.append(f"【背景介绍·画面叠字】{short}")
    return cues


def _pick_background_blurb(
    *,
    one_line_story: str | None,
    synopsis: str | None,
    core_hook: str | None,
) -> str | None:
    # 开幕背景文案优先级：一句话 > 钩子 > 梗概首句
    for raw in (one_line_story, core_hook, synopsis):
        text = (raw or "").strip()
        if text:
            return text
    return None


def _merge_bindings_for_fragment_body(
    bindings: list[dict[str, Any]],
    raw_lines: list[str],
    body_text: str,
    character_assets: list[Any],
    *,
    summary_lookup: dict[str, dict[str, Any]] | None,
    summary: dict[str, Any] | None,
    episode_bodies: list[str] | None = None,
    intro_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    # 补全 LLM 未列 character_names、但正文/@asset 已点名的角色
    seen = {str(b.get("name") or "") for b in bindings}
    extra_names: list[str] = []
    raw_blob = "\n".join(raw_lines)
    for asset in character_assets:
        name = str(getattr(asset, "name", "") or "").strip()
        if not name or name in seen:
            continue
        aid = int(asset.id)
        if name in raw_blob or re.search(rf"@asset:{aid}(?!\d)", body_text):
            extra_names.append(name)
            seen.add(name)
    if not extra_names:
        return bindings
    return [
        *bindings,
        *_build_character_bindings(
            extra_names,
            character_assets,
            summary_lookup=summary_lookup,
            summary=summary,
            episode_bodies=episode_bodies,
            intro_overrides=intro_overrides,
        ),
    ]


def normalize_llm_fragment_items(
    items: list[Any],
    assets: list[Any],
    *,
    episode_number: int | None = None,
    episode_name: str | None = None,
    project_title: str | None = None,
    story_type: str | None = None,
    one_line_story: str | None = None,
    synopsis: str | None = None,
    core_hook: str | None = None,
    already_introduced: set[str] | None = None,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
    intro_overrides: dict[str, str] | None = None,
    allow_opening: bool = True,
    include_subtitles: bool = True,
) -> list[dict[str, Any]]:
    """
    将 LLM fragments 转为落库草稿。
    注入 @asset、字幕/BGM、开幕集号/背景、重要角色本剧首次出场介绍。
    already_introduced：更早分集已介绍过的角色名。
    summary：剧本摘要，stub 资产从此补人物介绍。
    allow_opening：False 时续拆，不注入开幕叠字。
    """
    character_assets = [a for a in assets if getattr(a, "type", "") == "character"]
    scene_assets = [a for a in assets if getattr(a, "type", "") == "scene"]
    prop_material_assets = [
        a
        for a in assets
        if str(getattr(a, "type", "") or "") in {"prop", "material", "none"}
    ]
    summary_lookup = build_summary_character_lookup(summary)
    # introduced 本剧已介绍角色（含更早分集）
    introduced: set[str] = set(already_introduced or ())
    drafts: list[dict[str, Any]] = []
    opening_cues = _build_opening_cue_lines(
        episode_number=episode_number,
        episode_name=episode_name,
        project_title=project_title,
        story_type=story_type,
        one_line_story=one_line_story,
        background_blurb=_pick_background_blurb(
            one_line_story=one_line_story,
            synopsis=synopsis,
            core_hook=core_hook,
        ),
    )

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        lines = _coerce_lines(item.get("lines") or item.get("content"))
        if not lines:
            continue
        scene_name = str(item.get("scene_name") or item.get("sceneName") or "").strip() or None
        character_names = _coerce_name_list(
            item.get("character_names") or item.get("characterNames") or []
        )
        prop_names = _coerce_name_list(item.get("prop_names") or item.get("propNames") or [])
        material_names = _coerce_name_list(
            item.get("material_names") or item.get("materialNames") or []
        )

        # 正文未点名但 catalog 有的角色：从行文再扫一次资产名
        bindings = _build_character_bindings(
            character_names,
            character_assets,
            summary_lookup=summary_lookup,
            summary=summary,
            episode_bodies=episode_bodies,
        )
        if not bindings:
            # 兜底：全角色资产按名扫描本镜正文
            mentioned = []
            blob = "\n".join(lines)
            for asset in character_assets:
                name = str(getattr(asset, "name", "") or "").strip()
                if name and name in blob:
                    mentioned.append(name)
            bindings = _build_character_bindings(
                mentioned,
                character_assets,
                summary_lookup=summary_lookup,
                summary=summary,
                episode_bodies=episode_bodies,
                intro_overrides=intro_overrides,
            )
            character_names = [b["name"] for b in bindings]

        scene_asset_id: int | None = None
        matched_ids: list[int] = []
        if scene_name:
            scene_asset = _find_asset_by_name(scene_assets, scene_name)
            if scene_asset is not None:
                scene_asset_id = int(scene_asset.id)
                matched_ids.append(scene_asset_id)
        for b in bindings:
            aid = int(b["assetId"])
            if aid not in matched_ids:
                matched_ids.append(aid)

        body_blob = "\n".join(lines)
        prop_bindings = _match_prop_material_bindings(
            [*prop_names, *material_names],
            prop_material_assets,
            body_blob=body_blob,
        )
        for pb in prop_bindings:
            aid = int(pb["assetId"])
            if aid not in matched_ids:
                matched_ids.append(aid)

        body_lines: list[str] = []
        used = 0
        # timed_blocks 本 LLM 镜内各行 (时长, 文本行)；超软/硬上限时拆成多条 Fragment
        timed_blocks: list[tuple[int, list[str]]] = []
        inject_bindings = [*bindings, *prop_bindings]
        for line in lines:
            raw = _inject_character_mentions(line, inject_bindings)
            formatted = _format_narrative_line(raw)
            if not include_subtitles:
                formatted = _strip_subtitle_instruction(formatted)
            if scene_asset_id and scene_name and scene_name in formatted and f"@asset:{scene_asset_id}" not in formatted:
                formatted = formatted.replace(scene_name, f"@asset:{scene_asset_id} {scene_name}", 1)
            line_dur = _clamp_duration(_estimate_line_duration(formatted))
            if line_dur <= 0:
                continue
            timed_blocks.append((line_dur, [f"@duration:{line_dur}", formatted]))

        if not timed_blocks:
            continue

        chunk_index = 0

        def flush_chunk(*, is_last: bool) -> None:
            # 落盘当前块：注入介绍 / 开幕 cue，并保证 duration_sec 与 @duration 合计一致
            nonlocal body_lines, used, bindings, matched_ids, character_names, chunk_index
            if not body_lines:
                return

            body_text = "\n".join(body_lines)
            bindings = _merge_bindings_for_fragment_body(
                bindings,
                lines,
                body_text,
                character_assets,
                summary_lookup=summary_lookup,
                summary=summary,
                episode_bodies=episode_bodies,
                intro_overrides=intro_overrides,
            )
            for b in bindings:
                aid = int(b["assetId"])
                if aid not in matched_ids:
                    matched_ids.append(aid)

            for pb in _match_prop_material_bindings(
                [],
                prop_material_assets,
                body_blob=body_text,
            ):
                aid = int(pb["assetId"])
                if aid not in matched_ids:
                    matched_ids.append(aid)
                # 已写入 body 的行若仍是裸名，在最终 content 里再注一次
                body_text = _inject_character_mentions(body_text, [pb])
                body_lines = body_text.split("\n") if body_text else body_lines

            is_opening = (
                _truthy_opening_flag(item, index, allow_opening=allow_opening)
                and not drafts
                and chunk_index == 0
            )
            pending = [
                b
                for b in bindings
                if b.get("important")
                and b.get("introText")
                and str(b.get("name") or "") not in introduced
            ]
            to_intro: list[dict[str, Any]] = []
            for b in pending:
                name = str(b["name"])
                asset_id = b.get("assetId")
                listed = name in character_names
                mentioned = name in body_text or (
                    asset_id is not None
                    and bool(re.search(rf"@asset:{int(asset_id)}(?!\d)", body_text))
                )
                if listed or mentioned:
                    to_intro.append(b)
                    introduced.add(name)

            intro_lines = _build_character_intro_lines(to_intro)
            opening_lines = opening_cues if is_opening else []
            cues = _build_production_cues(
                None,
                body_lines[:3],
                [*opening_lines, *intro_lines],
                include_subtitles=include_subtitles,
            )
            content = "\n".join([*cues, *body_lines]).strip()
            duration = min(FRAGMENT_TOTAL_MAX, max(used, FRAGMENT_DURATION_MIN))
            drafts.append(
                {
                    "content": content,
                    "duration_sec": duration,
                    "asset_ids": list(matched_ids),
                    "scene_name": scene_name,
                    "character_names": character_names,
                    "is_opening": is_opening,
                }
            )
            chunk_index += 1
            body_lines = []
            used = 0

        for block_dur, block_rows in timed_blocks:
            if used > 0 and used >= FRAGMENT_SOFT_MAX and used + block_dur > FRAGMENT_SOFT_MAX:
                flush_chunk(is_last=False)
            if used > 0 and used + block_dur > FRAGMENT_TOTAL_MAX:
                flush_chunk(is_last=False)

            take_dur = block_dur
            if take_dur > FRAGMENT_TOTAL_MAX:
                take_dur = FRAGMENT_TOTAL_MAX
            if used + take_dur > FRAGMENT_TOTAL_MAX:
                take_dur = FRAGMENT_TOTAL_MAX - used
            if take_dur <= 0:
                flush_chunk(is_last=False)
                take_dur = min(block_dur, FRAGMENT_TOTAL_MAX)

            if take_dur != block_dur:
                rewritten = [
                    f"@duration:{take_dur}" if ln.startswith("@duration:") else ln
                    for ln in block_rows
                ]
                body_lines.extend(rewritten)
            else:
                body_lines.extend(block_rows)
            used += take_dur

        flush_chunk(is_last=True)

    return drafts


async def plan_fragments_with_llm(
    *,
    episode_name: str,
    episode_body: str,
    assets: list[Any],
    episode_number: int | None = None,
    project_title: str | None = None,
    story_type: str | None = None,
    one_line_story: str | None = None,
    synopsis: str | None = None,
    core_hook: str | None = None,
    already_introduced: set[str] | None = None,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
    intro_overrides: dict[str, str] | None = None,
    locked_summaries: list[str] | None = None,
    db: Any | None = None,
    user_id: int | None = None,
    skill_ids: list[int] | None = None,
    include_subtitles: bool = True,
) -> list[dict[str, Any]]:
    """
    调用 LLM 规划分镜并规范化。
    若模型结果为空则抛错，由上层决定是否回退规则切分。
    already_introduced：本剧更早分集已介绍角色。
    locked_summaries：本集已拍分镜摘要；非空时续拆（不开幕）。
    db / user_id：注入 Agent Skill（如 CINEDANCE 导演手册）。
    skill_ids：本次勾选；None 表示全部启用，[] 表示不注入。
    """
    catalog = build_asset_catalog(assets)
    locked = [str(s).strip() for s in (locked_summaries or []) if str(s).strip()]
    user_prompt = build_fragment_plan_user_prompt(
        episode_name=episode_name,
        episode_body=episode_body,
        asset_catalog=catalog,
        episode_number=episode_number,
        project_title=project_title,
        story_type=story_type,
        one_line_story=one_line_story,
        synopsis=synopsis,
        core_hook=core_hook,
        locked_summaries=locked,
        include_subtitles=include_subtitles,
    )
    raw = await run_task_json(
        db,
        user_id,
        task="shot_plan",
        system=FRAGMENT_PLAN_SYSTEM_PROMPT,
        user=user_prompt,
        temperature=0.4,
        skill_ids=skill_ids,
    )
    items: list[Any] = []
    if isinstance(raw, dict):
        items = raw.get("fragments") or raw.get("shots") or raw.get("storyboard") or []
    elif isinstance(raw, list):
        items = raw
    if not isinstance(items, list) or not items:
        raise RuntimeError("LLM 分镜结果为空")

    drafts = normalize_llm_fragment_items(
        items,
        assets,
        episode_number=episode_number,
        episode_name=episode_name,
        project_title=project_title,
        story_type=story_type,
        one_line_story=one_line_story,
        synopsis=synopsis,
        core_hook=core_hook,
        already_introduced=already_introduced,
        summary=summary,
        episode_bodies=episode_bodies,
        intro_overrides=intro_overrides,
        allow_opening=not bool(locked),
        include_subtitles=include_subtitles,
    )
    if not drafts:
        raise RuntimeError("LLM 分镜规范化后为空")
    logger.info(
        "LLM 分镜完成 episode=%s ep_no=%s fragments=%s introduced_before=%s locked=%s",
        episode_name,
        episode_number,
        len(drafts),
        len(already_introduced or ()),
        len(locked),
    )
    return drafts
