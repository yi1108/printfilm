"""将分集剧本按场次切成视频向分镜（对齐 manju buildSerieFragmentsFromEpisode）。"""

from __future__ import annotations

import re
from typing import Any

from app.services.seedance_segments import DRAMA_SUBTITLE_CUE, DIALOGUE_PREFIX, VISUAL_PREFIX

# 场次标题：### 场1-2 / ### 场景1-2
SCENE_HEADER_RE = re.compile(r"^###\s*场(?:景)?\s*\d+\s*[-－—]\s*\d+\s*$")
# 兼容无空格、或标题后带说明
SCENE_HEADER_LOOSE_RE = re.compile(r"^###\s*场(?:景)?\s*\d+\s*[-－—]\s*\d+")
# 时间内外景行
SCENE_LOCATION_RE = re.compile(
    r"^(?:日|夜|晨|黄昏|傍晚|凌晨|清晨|午|晚)?\s*(?:内|外|内外)\s+(.+)$"
)
# 出场人物行
CAST_LINE_RE = re.compile(r"^出场人物[：:]\s*(.+)$")
EMPTY_CAST = {"无", "无出场", "无人物", "-", "—", "无。"}

FRAGMENT_DURATION_MIN = 3
FRAGMENT_DURATION_MAX = 12
# 单分镜软上限：超过后新开一条分镜（仍可继续填到硬上限）
FRAGMENT_SOFT_MAX = 20
# 单分镜总时长硬上限（Seedance 2.5 支持至 30s）
FRAGMENT_TOTAL_MAX = 30

# 重要角色：roleType / title / tags 命中则需要人物介绍叠字
IMPORTANT_ROLE_RE = re.compile(r"主角|男主|女主|重要|反派|BOSS|核心|主人公")
# 次要定位：默认不介绍
MINOR_ROLE_RE = re.compile(r"群演|路人|群众|龙套|配角|出场人物|兵丁|侍卫|士兵")
# 群体/无名角色名：不介绍
MINOR_NAME_RE = re.compile(r"(兵|百姓|群众|路人|侍从|侍卫|士兵|甲|乙|众人|百姓们)$")
# 无意义 intro 占位文案
GENERIC_INTRO_TEXTS = frozenset({"出场人物", "配角", "角色", "群演", "路人", "-"})
# stub 资产默认身份背景等占位句式
STUB_CAST_INTRO_RE = re.compile(r"剧本分集出场人物|出场\s*->\s*卷入")
# 已写入分镜的人物介绍叠字行（兼容旧「·画面叠字」与现行「·角色身旁」）
CHARACTER_INTRO_CUE = "【人物介绍·画面叠字·角色身旁】"
CHARACTER_INTRO_LINE_RE = re.compile(
    r"^【人物介绍·画面叠字(?:·角色身旁)?】\s*([^｜\|\n]+?)(?:\s*[｜|].*)?$"
)
LEGACY_CHARACTER_INTRO_CUE = "【人物介绍·画面叠字】"
# 纯画面/空镜标签（冒号前）：禁止当成「角色名：对白」
VISUAL_SHOT_LABEL_RE = re.compile(
    r"^(?:"
    r"空镜|画面|远景|近景|中景|全景|特写|大特写|"
    r"跟拍|俯拍|仰拍|航拍|推镜|拉镜|摇镜|环境|镜头|动作|转场|闪回|"
    r"建立镜头|气氛镜头"
    r")\s*[：:]"
)


def normalize_scene_location_name(raw: str) -> str:
    # 去掉斜杠说明、压缩空白
    primary = re.split(r"[／/]", raw)[0].strip()
    cleaned = re.sub(r"\s+", " ", primary).strip()
    if len(cleaned) < 2 or len(cleaned) > 40:
        return ""
    return cleaned


def parse_cast_names(raw: str) -> list[str]:
    # 解析「出场人物：A、B」
    trimmed = (raw or "").strip()
    if not trimmed or trimmed.rstrip("。.．") in EMPTY_CAST:
        return []
    names = [
        part.strip()
        for part in re.split(r"[、，,／/|]", trimmed)
        if part.strip() and part.strip() not in EMPTY_CAST
    ]
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def extract_introduced_names_from_content(content: str) -> list[str]:
    # 从分镜正文提取已写入的人物介绍角色名（保序）
    names: list[str] = []
    seen: set[str] = set()
    for line in (content or "").replace("\r\n", "\n").split("\n"):
        match = CHARACTER_INTRO_LINE_RE.match(line.strip())
        if not match:
            continue
        name = match.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def collect_series_introduced_names(
    episodes: list[Any],
    *,
    before_episode_number: int | None = None,
    exclude_episode_id: int | None = None,
) -> set[str]:
    """
    汇总本剧更早分集里已做过人物介绍的角色名。
    before_episode_number：只统计集号更小的分集；None 则按 exclude 排除当前集。
    """
    # rows (ep_no, ep_id, episode) 排序用
    rows: list[tuple[int, int, Any]] = []
    for ep in episodes:
        params = getattr(ep, "params", None) or {}
        if not isinstance(params, dict):
            params = {}
        ep_no = int(params.get("episodeNumber") or 0)
        ep_id = int(getattr(ep, "id", 0) or 0)
        if exclude_episode_id is not None and ep_id == int(exclude_episode_id):
            continue
        if before_episode_number is not None and before_episode_number > 0:
            if ep_no <= 0 or ep_no >= int(before_episode_number):
                continue
        rows.append((ep_no or 10**9, ep_id, ep))
    rows.sort(key=lambda x: (x[0], x[1]))

    introduced: set[str] = set()
    for _, _, ep in rows:
        for frag in getattr(ep, "fragments", None) or []:
            for name in extract_introduced_names_from_content(getattr(frag, "content", None) or ""):
                introduced.add(name)
    return introduced


def split_episode_content_into_scenes(content: str) -> list[dict[str, str]]:
    # 按 ### 场X-Y 拆分；无场头时整集一场
    lines = (content or "").replace("\r\n", "\n").split("\n")
    scenes: list[dict[str, str]] = []
    current: dict[str, Any] | None = None

    for line in lines:
        trimmed = line.strip()
        if SCENE_HEADER_RE.match(trimmed) or SCENE_HEADER_LOOSE_RE.match(trimmed):
            if current is not None:
                scenes.append(
                    {
                        "heading": current["heading"],
                        "body": "\n".join(current["lines"]).strip(),
                    }
                )
            current = {"heading": trimmed, "lines": []}
            continue
        if current is not None:
            current["lines"].append(line)

    if current is not None:
        scenes.append(
            {
                "heading": current["heading"],
                "body": "\n".join(current["lines"]).strip(),
            }
        )

    if scenes:
        return scenes

    trimmed_all = (content or "").strip()
    if not trimmed_all:
        return []
    return [{"heading": "", "body": trimmed_all}]


def extract_scene_meta(body: str) -> dict[str, Any]:
    # 抽取地点与出场人物
    scene_name: str | None = None
    character_names: list[str] = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        trimmed = line.strip()
        if not trimmed:
            continue
        if scene_name is None:
            loc = SCENE_LOCATION_RE.match(trimmed)
            if loc:
                normalized = normalize_scene_location_name(loc.group(1))
                scene_name = normalized or None
        cast = CAST_LINE_RE.match(trimmed)
        if cast:
            character_names = parse_cast_names(cast.group(1))
    return {"sceneName": scene_name, "characterNames": character_names}


def _find_asset_by_name(candidates: list[Any], name: str) -> Any | None:
    target = (name or "").strip()
    if not target:
        return None
    for item in candidates:
        asset_name = (getattr(item, "name", None) or "").strip()
        if asset_name == target:
            return item
    for item in candidates:
        asset_name = (getattr(item, "name", None) or "").strip()
        if asset_name and (target in asset_name or asset_name in target):
            return item
    return None


def _strip_screenplay_meta(body: str) -> tuple[str | None, list[str]]:
    location_line: str | None = None
    narrative: list[str] = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        trimmed = line.strip()
        if not trimmed:
            continue
        if SCENE_HEADER_RE.match(trimmed) or SCENE_HEADER_LOOSE_RE.match(trimmed):
            continue
        if CAST_LINE_RE.match(trimmed):
            continue
        if location_line is None and SCENE_LOCATION_RE.match(trimmed):
            location_line = trimmed
            continue
        narrative.append(trimmed)
    return location_line, narrative


def _strip_production_prefix(line: str) -> str:
    # 去掉已有【…】生产前缀，便于二次分类
    return re.sub(r"^【[^】]*】\s*", "", (line or "").strip()).strip()


def _is_visual_description_line(line: str) -> bool:
    # 空镜/景别/纯画面描写：不得配音、不得烧字幕
    trimmed = (line or "").strip()
    if not trimmed:
        return False
    if trimmed.startswith("【画面") or trimmed.startswith(VISUAL_PREFIX):
        return True
    if trimmed.startswith("【空镜"):
        return True
    if trimmed.startswith("△") or trimmed.startswith("Δ"):
        return True
    body = _strip_production_prefix(trimmed)
    if not body:
        return False
    if VISUAL_SHOT_LABEL_RE.match(body):
        return True
    if body.startswith("空镜") or body.startswith("△"):
        return True
    return False


def _format_narrative_line(line: str) -> str:
    # 将场记行标成画面/旁白/对白；空镜类必须走无配音前缀
    trimmed = line.strip()
    if not trimmed:
        return trimmed
    if trimmed.startswith("【画面") or trimmed.startswith("【旁白") or trimmed.startswith("【对白"):
        # 已打标但仍可能是误判的「对白·空镜：…」→ 纠正为画面
        if trimmed.startswith("【对白") and _is_visual_description_line(trimmed):
            return f"{VISUAL_PREFIX}{_strip_production_prefix(trimmed)}"
        if trimmed.startswith("【旁白") and _is_visual_description_line(trimmed):
            return f"{VISUAL_PREFIX}{_strip_production_prefix(trimmed)}"
        return trimmed
    if trimmed.startswith("【空镜"):
        return f"【空镜·可仅环境音与 BGM】{trimmed}"
    if _is_visual_description_line(trimmed):
        if trimmed.startswith("△") or trimmed.startswith("Δ"):
            body = trimmed.replace("Δ", "△", 1) if trimmed.startswith("Δ") else trimmed
            return f"{VISUAL_PREFIX}{body}"
        return f"{VISUAL_PREFIX}{trimmed}"
    if re.search(r"[（(](?:vo|VO|旁白)[）)]", trimmed):
        return f"【旁白·慢速清晰·同步字幕】{trimmed}"
    if re.search(r"[（(](?:os|OS)[）)]", trimmed):
        return f"【内心独白·同步字幕】{trimmed}"
    # 角色对白：排除空镜/景别等冒号标签，避免「空镜：…」被当成「角色名：台词」
    if re.match(r"^[^（(:：\n]{1,16}[（(][^）)]*[）)]\s*[：:].+", trimmed):
        return f"{DIALOGUE_PREFIX}{trimmed}"
    colon_speaker = re.match(r"^([^：:\n]{1,16})[：:](.+)$", trimmed)
    if colon_speaker and not VISUAL_SHOT_LABEL_RE.match(trimmed):
        return f"{DIALOGUE_PREFIX}{trimmed}"
    # 纯画面/动作描述：明确禁止配音，避免被全局字幕 cue 误读为旁白
    return f"{VISUAL_PREFIX}{trimmed}"


def _estimate_line_duration(line: str) -> int:
    trimmed = line.strip()
    if not trimmed:
        return 0
    if trimmed.startswith("【画面") or trimmed.startswith(VISUAL_PREFIX):
        body = re.sub(r"^【[^】]*】", "", trimmed).strip()
        return min(6, max(2, len(re.sub(r"\s+", "", body)) // 12))
    if trimmed.startswith("△"):
        return 2
    if trimmed.startswith("【空镜"):
        return 4
    if "旁白" in trimmed and trimmed.startswith("【旁白"):
        return min(8, max(3, len(re.sub(r"\s+", "", trimmed)) // 8))
    if trimmed.startswith("【对白") or "内心独白" in trimmed:
        return min(8, max(3, len(re.sub(r"\s+", "", trimmed)) // 10))
    return min(6, max(2, len(re.sub(r"\s+", "", trimmed)) // 12))


def _clamp_duration(seconds: int) -> int:
    if seconds <= 0:
        return 0
    return min(max(seconds, FRAGMENT_DURATION_MIN), FRAGMENT_DURATION_MAX)


def _inject_character_mentions(text: str, bindings: list[dict[str, Any]]) -> str:
    if not bindings:
        return text
    sorted_bindings = sorted(bindings, key=lambda b: len(b["name"]), reverse=True)
    parts = re.split(r"(@asset:\d+)", text)
    out: list[str] = []
    for part in parts:
        if re.fullmatch(r"@asset:\d+", part or ""):
            out.append(part)
            continue
        result = part
        for binding in sorted_bindings:
            result = result.replace(binding["name"], f"@asset:{binding['assetId']}")
        out.append(result)
    return "".join(out)


def _format_location_opener(
    location_line: str | None,
    scene_asset_id: int | None,
    scene_name: str | None,
) -> str:
    if not location_line:
        if scene_asset_id and scene_name:
            return f"@asset:{scene_asset_id} {scene_name}。"
        return ""
    match = SCENE_LOCATION_RE.match(location_line)
    if match and match.group(1) and scene_asset_id:
        prefix = location_line[: len(location_line) - len(match.group(1))].strip()
        location_part = match.group(1).strip()
        compressed = re.sub(r"\s+", "", prefix)
        return f"{compressed} @asset:{scene_asset_id} {location_part}。"
    return location_line if location_line.endswith("。") else f"{location_line}。"


def _infer_bgm_mood(hints: str) -> str:
    text = hints or ""
    rules = [
        (r"刑|斩|战|杀|怒|崩|劫|乱", "低沉紧张、鼓点渐强，烘托压迫与危机感"),
        (r"殿|宫|朝|帝|神|礼", "庄重史诗、弦乐铺底，气势恢宏但不抢戏"),
        (r"夜|暗|悬疑|密", "神秘悬疑、低频铺底，留白感强"),
        (r"水|河|海|雨|洪", "流动感环境音乐，水声与弦乐交织"),
        (r"晨|春|暖|光", "轻柔开阔、希望感，钢琴或弦乐为主"),
    ]
    for pattern, mood in rules:
        if re.search(pattern, text):
            return mood
    return "贴合剧情氛围的轻量配乐，情绪随画面起伏"


def _is_generic_intro_text(text: str) -> bool:
    cleaned = re.sub(r"\s+", "", (text or "").strip())
    if not cleaned:
        return True
    if cleaned in GENERIC_INTRO_TEXTS:
        return True
    if cleaned.startswith("出场人物"):
        return True
    if STUB_CAST_INTRO_RE.search(cleaned):
        return True
    return False


def _shorten_intro(text: str, max_len: int = 24) -> str:
    # 叠字描述截断：去空白、取首句、限长
    cleaned = re.sub(r"\s+", "", (text or "").strip())
    if not cleaned:
        return ""
    first = re.split(r"[。！？；;]", cleaned, maxsplit=1)[0].strip()
    if len(first) > max_len:
        return first[: max_len - 1] + "…"
    return first


def _resolve_character_intro_text(params: dict[str, Any] | None) -> str | None:
    # 优先 title，其次身份背景首句 / roleType / 标签；跳过占位文案
    if not isinstance(params, dict):
        return None
    title = str(params.get("title") or "").strip()
    role = str(params.get("roleType") or "").strip()
    identity = str(params.get("identityBackground") or "").strip()
    tags = str(params.get("coreTags") or "").strip()
    personality = str(params.get("personality") or "").strip()

    if title and not _is_generic_intro_text(title):
        return _shorten_intro(title)
    if identity:
        shortened = _shorten_intro(identity)
        if shortened and not _is_generic_intro_text(shortened):
            return shortened
    if role and not _is_generic_intro_text(role):
        if title and not _is_generic_intro_text(title):
            return _shorten_intro(f"{role}·{title}")
        return _shorten_intro(role)
    if personality:
        shortened = _shorten_intro(personality)
        if shortened and not _is_generic_intro_text(shortened):
            return shortened
    if tags:
        first_tag = re.split(r"[、，,/|]", tags)[0].strip()
        if first_tag and not _is_generic_intro_text(first_tag):
            return _shorten_intro(first_tag)
    return None


def _extract_intro_sentence_for_name(name: str, text: str) -> str | None:
    # 从梗概/分集正文截取含该角色的句子作叠字介绍
    char_name = (name or "").strip()
    blob = (text or "").strip()
    if not char_name or char_name not in blob:
        return None
    candidates: list[str] = []
    for sent in re.split(r"[。！？\n]", blob):
        if char_name not in sent:
            continue
        cleaned = re.sub(r"\s+", "", sent.strip())
        if len(cleaned) < 6:
            continue
        if CAST_LINE_RE.match(cleaned) or cleaned.startswith("出场人物"):
            continue
        if cleaned.startswith("###"):
            continue
        candidates.append(cleaned)
    if not candidates:
        return None
    # 叠字宜短：优先 12~36 字的句子
    best = min(candidates, key=lambda s: abs(len(s) - 22))
    return _shorten_intro(best, max_len=28)


def _resolve_intro_from_summary_narrative(
    name: str,
    summary: dict[str, Any] | None,
) -> str | None:
    char_name = (name or "").strip()
    if not char_name or not isinstance(summary, dict):
        return None
    for field in ("synopsis", "oneLineStory", "coreHook"):
        text = str(summary.get(field) or "").strip()
        intro = _extract_intro_sentence_for_name(char_name, text)
        if intro:
            return intro
    return None


def infer_character_intro_text(
    name: str,
    params: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
    intro_overrides: dict[str, str] | None = None,
) -> str | None:
    """人物介绍叠字文案：override → 资产字段 → 摘要梗概 → 分集剧本正文。"""
    char_name = (name or "").strip()
    if char_name and intro_overrides:
        override = str(intro_overrides.get(char_name) or "").strip()
        if override and not _is_generic_intro_text(override):
            return _shorten_intro(override, max_len=28)
    intro = _resolve_character_intro_text(params)
    if intro and not _is_generic_intro_text(intro):
        return intro
    intro = _resolve_intro_from_summary_narrative(name, summary)
    if intro:
        return intro
    for body in episode_bodies or []:
        intro = _extract_intro_sentence_for_name(name, body)
        if intro:
            return intro
    if isinstance(params, dict):
        for field in ("relationships", "growthExperience", "growthArc"):
            val = str(params.get(field) or "").strip()
            if not val or _is_generic_intro_text(val):
                continue
            shortened = _shorten_intro(val)
            if shortened and not _is_generic_intro_text(shortened):
                return shortened
    return None


def build_summary_character_lookup(summary: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    # 剧本摘要 characters[] 按名索引（保序，供 stub 资产补全小传）
    lookup: dict[str, dict[str, Any]] = {}
    if not isinstance(summary, dict):
        return lookup
    for item in summary.get("characters") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name and name not in lookup:
            lookup[name] = item
    return lookup


def _find_summary_character(
    lookup: dict[str, dict[str, Any]],
    name: str,
) -> dict[str, Any] | None:
    target = (name or "").strip()
    if not target or not lookup:
        return None
    if target in lookup:
        return lookup[target]
    for key, item in lookup.items():
        if key and (target in key or key in target):
            return item
    return None


def _merge_params_with_summary(
    params: dict[str, Any] | None,
    summary_char: dict[str, Any] | None,
) -> dict[str, Any]:
    # 资产 params 为 stub 时，用摘要人物字段补全
    merged = dict(params or {})
    if not summary_char:
        return merged
    for key in ("roleType", "title", "coreTags", "identityBackground", "personality"):
        summary_val = str(summary_char.get(key) or "").strip()
        if not summary_val:
            continue
        existing = str(merged.get(key) or "").strip()
        if not existing or _is_generic_intro_text(existing):
            merged[key] = summary_val
    return merged


def _character_mentioned_in_summary(name: str, summary: dict[str, Any] | None) -> bool:
    char_name = (name or "").strip()
    if not char_name or not isinstance(summary, dict):
        return False
    if _find_summary_character(build_summary_character_lookup(summary), char_name):
        return True
    blob = " ".join(
        str(summary.get(k) or "")
        for k in ("synopsis", "oneLineStory", "coreHook")
    )
    return char_name in blob


def build_character_binding(
    character_name: str,
    character_asset: Any,
    *,
    summary_lookup: dict[str, dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
    intro_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    # 组装单角色 binding：重要度 + 介绍文案（摘要优先于 stub 资产）
    name = str(character_name or "").strip()
    params = getattr(character_asset, "params", None) or {}
    if not isinstance(params, dict):
        params = {}
    lookup = summary_lookup if summary_lookup is not None else build_summary_character_lookup(summary)
    summary_char = _find_summary_character(lookup, name)
    merged = _merge_params_with_summary(params, summary_char)
    role_type = str(merged.get("roleType") or "").strip() or None
    title = str(merged.get("title") or "").strip() or None
    core_tags = str(merged.get("coreTags") or "").strip() or None
    intro = infer_character_intro_text(
        name,
        merged,
        summary,
        episode_bodies=episode_bodies,
        intro_overrides=intro_overrides,
    )
    important = _is_important_character(
        name,
        role_type=role_type,
        title=title,
        core_tags=core_tags,
    )
    if not important and _character_mentioned_in_summary(name, summary):
        important = True
    return {
        "name": name,
        "assetId": int(character_asset.id),
        "introText": intro,
        "important": important,
    }


def _is_important_character(
    name: str,
    *,
    role_type: str | None = None,
    title: str | None = None,
    core_tags: str | None = None,
) -> bool:
    # 仅重要角色做人物介绍：群体名 / 纯配角 stub 跳过
    char_name = (name or "").strip()
    if not char_name or MINOR_NAME_RE.search(char_name):
        return False
    role = (role_type or "").strip()
    ttl = (title or "").strip()
    tags = (core_tags or "").strip()
    blob = f"{role} {ttl} {tags}"
    if IMPORTANT_ROLE_RE.search(blob):
        return True
    if ttl and not _is_generic_intro_text(ttl):
        # 有具体身份头衔（如「治水英雄」「四岳首领」）视为可介绍
        return True
    if MINOR_ROLE_RE.search(role) or role in GENERIC_INTRO_TEXTS or not role:
        return False
    return True


def _strip_subtitle_instruction(line: str) -> str:
    # 关闭字幕时移除正文中的同步字幕提示，保留对白/旁白本身。
    trimmed = (line or "").strip()
    replacements = {
        DIALOGUE_PREFIX: "【对白·慢速清晰】",
        "【旁白·慢速清晰·同步字幕】": "【旁白·慢速清晰】",
        "【内心独白·同步字幕】": "【内心独白】",
    }
    for src, dest in replacements.items():
        if trimmed.startswith(src):
            return trimmed.replace(src, dest, 1)
    return trimmed


def _build_production_cues(
    location_line: str | None,
    narrative_lines: list[str],
    character_intro_lines: list[str],
    *,
    include_subtitles: bool = True,
) -> list[str]:
    # 字幕 / BGM / 人物介绍前置提示（字幕 cue 不含「旁白」字样，避免 Seedance 整镜念白）
    hint = " ".join(filter(None, [location_line or "", *narrative_lines[:3]]))
    lines = [f"【BGM：{_infer_bgm_mood(hint)}；音量低于人声】"]
    if include_subtitles:
        lines.insert(0, DRAMA_SUBTITLE_CUE)
    lines.extend(character_intro_lines)
    return lines


def _build_character_intro_lines(character_bindings: list[dict[str, Any]]) -> list[str]:
    # 人物介绍叠字：贴在对应角色身旁，非口播
    lines: list[str] = []
    for b in character_bindings:
        name = str(b.get("name") or "").strip()
        intro = str(b.get("introText") or "").strip()
        if not name or not intro:
            continue
        lines.append(f"{CHARACTER_INTRO_CUE}{name}｜{intro}")
    return lines


def _bindings_mentioned_in_text(
    text: str,
    bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # 正文或 @asset 引用中首次点名的角色（保序）
    if not text or not bindings:
        return []
    hit: list[dict[str, Any]] = []
    seen: set[str] = set()
    for binding in bindings:
        name = str(binding.get("name") or "").strip()
        if not name or name in seen:
            continue
        asset_id = binding.get("assetId")
        mentioned = name in text
        if not mentioned and asset_id is not None:
            mentioned = bool(re.search(rf"@asset:{int(asset_id)}(?!\d)", text))
        if mentioned:
            seen.add(name)
            hit.append(binding)
    return hit


def _flush_fragment_chunk(
    cue_lines: list[str],
    body_lines: list[str],
    used: int,
) -> tuple[str, int]:
    # 组装单条分镜草稿；无正文时给最小时长占位
    planned = [*cue_lines, *body_lines]
    duration = used
    if duration <= 0:
        planned.append(f"@duration:{FRAGMENT_DURATION_MIN}")
        duration = FRAGMENT_DURATION_MIN
    return "\n".join(planned).strip(), duration


def _pick_intros_for_fragment(
    body_lines: list[str],
    intro_candidates: list[dict[str, Any]],
    introduced: set[str],
    *,
    flush_remaining: bool = False,
) -> list[dict[str, Any]]:
    # 本镜首次出场的重要角色；末镜可兜底介绍本场剩余候选
    pending = [b for b in intro_candidates if str(b.get("name") or "") not in introduced]
    if not pending:
        return []
    body_text = "\n".join(body_lines)
    mentioned = _bindings_mentioned_in_text(body_text, pending)
    if flush_remaining:
        # 末镜：点名优先，其余未出场候选一并介绍，避免重要角色漏介绍
        mentioned_names = {str(b.get("name") or "") for b in mentioned}
        extras = [b for b in pending if str(b.get("name") or "") not in mentioned_names]
        return [*mentioned, *extras]
    return mentioned


def plan_fragments_from_scene(
    body: str,
    meta: dict[str, Any],
    scene_asset_id: int | None,
    character_bindings: list[dict[str, Any]],
    introduced: set[str] | None = None,
    *,
    include_subtitles: bool = True,
) -> list[tuple[str, int]]:
    """
    规划单场视频向分镜正文；超软上限时拆成多条，避免截断后半场。
    人物介绍仅注入「重要且本剧首次出场」的角色，落到其首次出现的分镜。
    introduced 跨集/跨场共享的已介绍角色名集合（会被原地更新）。
    返回 [(content, duration_sec), ...]
    """
    # introduced_names 本剧已介绍过的角色
    introduced_names = introduced if introduced is not None else set()
    location_line, narrative_lines = _strip_screenplay_meta(body)
    # intro_candidates 本场可介绍的重要角色（须有简短描述）
    intro_candidates = [
        b
        for b in character_bindings
        if b.get("important") and b.get("introText") and str(b.get("name") or "").strip()
    ]
    base_cues = _build_production_cues(
        location_line,
        narrative_lines,
        [],
        include_subtitles=include_subtitles,
    )

    # timed_blocks 待打包的 (时长, 文本行列表)
    timed_blocks: list[tuple[int, list[str]]] = []

    opener = _format_location_opener(location_line, scene_asset_id, meta.get("sceneName"))
    if opener:
        opener_dur = _clamp_duration(3)
        timed_blocks.append(
            (
                opener_dur,
                [
                    f"@duration:{opener_dur}",
                    _inject_character_mentions(opener, character_bindings),
                ],
            )
        )

    for line in narrative_lines:
        raw = _inject_character_mentions(line, character_bindings)
        formatted = _format_narrative_line(raw)
        if not include_subtitles:
            formatted = _strip_subtitle_instruction(formatted)
        line_dur = _clamp_duration(_estimate_line_duration(formatted))
        if line_dur <= 0:
            continue
        timed_blocks.append((line_dur, [f"@duration:{line_dur}", formatted]))

    if not timed_blocks:
        to_intro = _pick_intros_for_fragment([], intro_candidates, introduced_names, flush_remaining=True)
        cues = _build_production_cues(
            location_line,
            narrative_lines,
            _build_character_intro_lines(to_intro),
            include_subtitles=include_subtitles,
        )
        for b in to_intro:
            introduced_names.add(str(b["name"]))
        return [_flush_fragment_chunk(cues, [], 0)]

    fragments: list[tuple[str, int]] = []
    body_lines: list[str] = []
    used = 0

    def flush_current(*, is_last: bool) -> None:
        # 落盘当前镜并注入本镜首次出场介绍
        nonlocal body_lines, used
        to_intro = _pick_intros_for_fragment(
            body_lines,
            intro_candidates,
            introduced_names,
            flush_remaining=is_last,
        )
        intro_lines = _build_character_intro_lines(to_intro)
        cues = [*base_cues, *intro_lines] if intro_lines else list(base_cues)
        fragments.append(_flush_fragment_chunk(cues, body_lines, used))
        for b in to_intro:
            introduced_names.add(str(b["name"]))
        body_lines = []
        used = 0

    for block_dur, block_lines in timed_blocks:
        # 已达软上限且本块放不下 → 先落盘当前镜
        if used > 0 and used >= FRAGMENT_SOFT_MAX and used + block_dur > FRAGMENT_SOFT_MAX:
            flush_current(is_last=False)

        # 硬上限：本块放不下则开新镜；单块超过硬上限则截断到硬上限
        if used > 0 and used + block_dur > FRAGMENT_TOTAL_MAX:
            flush_current(is_last=False)

        take_dur = block_dur
        if take_dur > FRAGMENT_TOTAL_MAX:
            take_dur = FRAGMENT_TOTAL_MAX
        if used + take_dur > FRAGMENT_TOTAL_MAX:
            take_dur = FRAGMENT_TOTAL_MAX - used
        if take_dur <= 0:
            flush_current(is_last=False)
            take_dur = min(block_dur, FRAGMENT_TOTAL_MAX)

        if take_dur != block_dur:
            # 时长被截断时改写 @duration 行
            rewritten = [f"@duration:{take_dur}" if ln.startswith("@duration:") else ln for ln in block_lines]
            body_lines.extend(rewritten)
        else:
            body_lines.extend(block_lines)
        used += take_dur

    if body_lines or not fragments:
        flush_current(is_last=True)

    return fragments


# 解析已有分镜正文：片头 cue + (@duration + 正文) 块
def parse_fragment_timed_blocks(content: str) -> tuple[list[str], list[tuple[int, list[str]]]]:
    lines = (content or "").replace("\r\n", "\n").split("\n")
    header: list[str] = []
    blocks: list[tuple[int, list[str]]] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped.startswith("@duration:"):
            break
        header.append(raw)
        i += 1
    while i < len(lines):
        stripped = lines[i].strip()
        m = re.match(r"^@duration:(\d+)\s*$", stripped)
        if not m:
            i += 1
            continue
        dur = int(m.group(1))
        block_lines = [f"@duration:{dur}"]
        i += 1
        while i < len(lines) and not lines[i].strip().startswith("@duration:"):
            block_lines.append(lines[i])
            i += 1
        if dur > 0:
            blocks.append((dur, block_lines))
    return header, blocks


# 将已有超长分镜正文按软/硬上限拆成多条 content（保留片头 cue）
def split_overlong_fragment_content(
    content: str,
    *,
    soft_max: int = FRAGMENT_SOFT_MAX,
    hard_max: int = FRAGMENT_TOTAL_MAX,
) -> list[tuple[str, int]]:
    header, blocks = parse_fragment_timed_blocks(content)
    if not blocks:
        return []
    total = sum(d for d, _ in blocks)
    if total <= hard_max:
        used = total
        text = "\n".join([*header, *[ln for _, rows in blocks for ln in rows]]).strip()
        return [(text, used)] if text else []

    chunks: list[tuple[str, int]] = []
    body: list[str] = []
    used = 0

    def flush() -> None:
        nonlocal body, used
        if not body:
            return
        text = "\n".join([*header, *body]).strip()
        chunks.append((text, used))
        body = []
        used = 0

    for block_dur, block_lines in blocks:
        if used > 0 and used >= soft_max and used + block_dur > soft_max:
            flush()
        if used > 0 and used + block_dur > hard_max:
            flush()
        take = block_dur
        if take > hard_max:
            take = hard_max
        if used + take > hard_max:
            take = hard_max - used
        if take <= 0:
            flush()
            take = min(block_dur, hard_max)
        if take != block_dur:
            rewritten = [
                f"@duration:{take}" if ln.strip().startswith("@duration:") else ln
                for ln in block_lines
            ]
            body.extend(rewritten)
        else:
            body.extend(block_lines)
        used += take
    flush()
    return chunks


def plan_fragment_content_from_scene(
    body: str,
    meta: dict[str, Any],
    scene_asset_id: int | None,
    character_bindings: list[dict[str, Any]],
    *,
    include_subtitles: bool = True,
) -> tuple[str, int]:
    # 兼容旧调用：返回本场第一条分镜
    chunks = plan_fragments_from_scene(
        body,
        meta,
        scene_asset_id,
        character_bindings,
        include_subtitles=include_subtitles,
    )
    return chunks[0] if chunks else ("", FRAGMENT_DURATION_MIN)


def is_raw_screenplay_fragment(content: str) -> bool:
    # 仍为场记原文、需按新逻辑重切
    trimmed = (content or "").strip()
    if not trimmed:
        return True
    if "### 场" in trimmed or "### 场景" in trimmed:
        return True
    if re.search(r"^出场人物[：:]", trimmed, re.M):
        return True
    if "【字幕：" not in trimmed and "@duration:" not in trimmed:
        return True
    return False


def build_fragments_from_episode_body(
    content: str,
    assets: list[Any],
    already_introduced: set[str] | None = None,
    summary: dict[str, Any] | None = None,
    episode_bodies: list[str] | None = None,
    intro_overrides: dict[str, str] | None = None,
    *,
    include_subtitles: bool = True,
) -> list[dict[str, Any]]:
    """
    将一集正文拆成多场分镜草稿。
    already_introduced：本剧更早分集已介绍过的角色（跨集去重）。
    summary：剧本摘要，用于 stub 资产补全人物介绍文案。
    返回 [{content, duration_sec, asset_ids, scene_name, character_names}, ...]
    """
    character_assets = [a for a in assets if getattr(a, "type", "") == "character"]
    scene_assets = [a for a in assets if getattr(a, "type", "") == "scene"]
    prop_material_assets = [
        a
        for a in assets
        if str(getattr(a, "type", "") or "") in {"prop", "material", "none"}
    ]
    scenes = split_episode_content_into_scenes(content)
    summary_lookup = build_summary_character_lookup(summary)
    script_bodies = list(episode_bodies or [])
    if content and content not in script_bodies:
        script_bodies.append(content)

    if not scenes:
        return [
            {
                "content": "",
                "duration_sec": 8,
                "asset_ids": [],
                "scene_name": None,
                "character_names": [],
            }
        ]

    # introduced 本剧已做过人物介绍的角色名（含更早分集 + 本集跨场）
    introduced: set[str] = set(already_introduced or ())
    fragments: list[dict[str, Any]] = []
    for scene in scenes:
        meta = extract_scene_meta(scene["body"])
        matched_ids: list[int] = []
        scene_asset_id: int | None = None
        character_bindings: list[dict[str, Any]] = []

        if meta.get("sceneName"):
            scene_asset = _find_asset_by_name(scene_assets, str(meta["sceneName"]))
            if scene_asset is not None:
                scene_asset_id = int(scene_asset.id)
                matched_ids.append(scene_asset_id)

        for character_name in meta.get("characterNames") or []:
            character_asset = _find_asset_by_name(character_assets, str(character_name))
            if character_asset is None:
                continue
            character_bindings.append(
                build_character_binding(
                    str(character_name),
                    character_asset,
                    summary_lookup=summary_lookup,
                    summary=summary,
                    episode_bodies=script_bodies,
                    intro_overrides=intro_overrides,
                )
            )
            if character_asset.id not in matched_ids:
                matched_ids.append(int(character_asset.id))

        # 一场可拆多条分镜（按时长软/硬上限）；介绍落在首次出场镜
        for planned, duration in plan_fragments_from_scene(
            scene["body"],
            meta,
            scene_asset_id,
            character_bindings,
            introduced,
            include_subtitles=include_subtitles,
        ):
            # 规则切分：正文里出现的道具/素材名注入 @asset 并写入 asset_ids
            prop_bindings: list[dict[str, Any]] = []
            for asset in prop_material_assets:
                name = str(getattr(asset, "name", "") or "").strip()
                if not name or name not in planned:
                    continue
                aid = int(asset.id)
                prop_bindings.append({"name": name, "assetId": aid})
                if aid not in matched_ids:
                    matched_ids.append(aid)
            if prop_bindings:
                planned = _inject_character_mentions(planned, prop_bindings)
            fragments.append(
                {
                    "content": planned,
                    "duration_sec": duration or 8,
                    "asset_ids": list(matched_ids),
                    "scene_name": meta.get("sceneName"),
                    "character_names": meta.get("characterNames") or [],
                }
            )

    return fragments
