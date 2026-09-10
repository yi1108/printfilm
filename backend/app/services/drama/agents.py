"""Drama script agents: summary + episode outline + episode scripts."""

from __future__ import annotations

from typing import Any

from app.services.drama.llm import drama_chat_json
from app.services.drama.script_summary_prompt import (
    SCRIPT_SUMMARY_SYSTEM_PROMPT,
    build_script_summary_user_message,
)

# 与 manju episodeScript 对齐：先规划全集集名
EPISODE_OUTLINE_SYSTEM = """你是专业的短剧/网剧编剧策划，负责根据原始创意与剧本摘要，规划全部分集的「集数 + 集名」大纲。

输出要求：
1. 必须严格按照用户给定的总集数生成，episodes 数组长度必须与总集数完全一致
2. episodeNumber 从 1 开始连续递增，不得跳号、不得重复
3. 每集 title 为 4-12 个汉字的集名，概括本集核心事件或冲突钩子，风格参考：金箍碎佛规、罪臣之子承玄圭
4. 全剧分集须覆盖剧本摘要中的起承转合：前期立人设与世界观、中期升级矛盾与反转、后期高潮与结局，节奏适合短剧连载
5. 相邻集名之间要有因果衔接与追剧钩子，避免重复套路
6. 语言使用简体中文

必须输出严格 JSON：
{"episodes":[{"episodeNumber":1,"title":"集名"}, ...]}"""

# 与 manju episodeScript 对齐：逐集撰写拍摄正文
EPISODE_BATCH_CONTENT_SYSTEM = """你是专业的短剧/网剧编剧，负责根据原始创意、剧本摘要、分集规划与已有剧集正文，撰写指定集数的拍摄剧本正文。

输出要求：
1. 每次任务只输出用户指定批次范围内的集数，episodes 数组长度必须与批次集数完全一致
2. episodeNumber 须与用户指定的集数一一对应，不得遗漏、不得额外生成
3. 须携带并参考「已有剧集正文」保持剧情、人设与世界观连贯；首批次无已有正文时从第 1 集开篇写起
4. 批次内各集之间须有因果衔接，末集结尾留追剧钩子
5. 必须输出对象格式：{"episodes":[{"episodeNumber":数字,"title":"集名","content":"..."}]}，不要直接输出数组
6. content 为正文主字段；不要把正文写得过短

格式要求（每集 content 须严格遵守）：
1. 按场次组织，场号格式为 ### 场{集数}-{场次}，如第 1 集第 2 场：### 场1-2
2. 场头下一行写时间内外景，如：日 内 灵山大雄宝殿 / 夜 外 妖寨大门外 / 晨外 羽山刑场
3. 下一行写：出场人物：角色A、角色B（只写可出镜人物名；不要写「某某（声音）」「某某音色」等音色标注）
4. 动作用 △ 开头，独占一行；动作须具体可拍（景别、调度、道具、表情），禁止一句带过
5. 台词格式：角色名（情绪/vo/os/动作）：台词内容；旁白用 vo，内心独白用 os；台词要有潜台词与冲突；括号内写情绪/vo/os，不要写「声音」「音色」
6. 关键镜头可用【空镜：描述】收尾一场或一段
7. content 内不要输出「第X集」或「X.集名：」标题行，只输出场戏正文
8. 每集 3-5 场；每场至少 3 段 △ 动作与 4 句以上台词（或对白+vo）；整集 content 不少于 800 汉字
9. 语言使用简体中文，偏影视剧本风格，动作与台词可拍摄、有张力"""

# 正文过短阈值（汉字量近似用去空白后长度）
MIN_EPISODE_CONTENT_CHARS = 500


async def run_script_summary(
    creative: str,
    episode_count: int | None = None,
    image_style_id: str | None = None,
) -> dict[str, Any]:
    # Build structured outline from creative brief
    trimmed = (creative or "").strip()
    if len(trimmed) < 10:
        raise ValueError("原始创意至少需要 10 个字")

    user_message = build_script_summary_user_message(
        trimmed,
        episode_count=episode_count,
        image_style_id=image_style_id,
    )
    data = await drama_chat_json(
        SCRIPT_SUMMARY_SYSTEM_PROMPT,
        user_message,
        max_tokens=8192,
    )
    if episode_count:
        data["episodeCount"] = episode_count
    return data


def resolve_episode_target(
    summary: dict[str, Any] | None,
    project_params: dict[str, Any] | None = None,
    script_params: dict[str, Any] | None = None,
) -> int:
    # 解析目标总集数：优先项目创建时的集数，其次摘要 / 剧本参数
    candidates = [
        (project_params or {}).get("episode_count"),
        (summary or {}).get("episodeCount"),
        (script_params or {}).get("episode_count"),
    ]
    for raw in candidates:
        try:
            value = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if value >= 1:
            return value
    return 12


def merge_episode_bodies(
    existing: list[dict[str, Any]],
    batch: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # 按集号合并；正文更长者优先，标题非空则更新
    by_number: dict[int, dict[str, Any]] = {}
    for item in existing + batch:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("episodeNumber") or item.get("episode_number") or 0)
        except (TypeError, ValueError):
            continue
        if number < 1:
            continue
        body = str(item.get("body") or item.get("content") or "")
        title = str(item.get("title") or "").strip() or f"第 {number} 集"
        prev = by_number.get(number)
        if prev:
            prev_body = str(prev.get("body") or "")
            if len(prev_body.strip()) > len(body.strip()):
                body = prev_body
            if title.startswith("第 ") and prev.get("title"):
                title = str(prev.get("title"))
            elif not title or title == f"第 {number} 集":
                title = str(prev.get("title") or title)
        by_number[number] = {
            "episodeNumber": number,
            "title": title,
            "body": body,
        }
    return [by_number[n] for n in sorted(by_number)]


def count_completed_episodes(episodes: list[dict[str, Any]], total: int) -> int:
    # 统计 1..total 中正文达到质量阈值的集数
    done = 0
    for item in episodes:
        try:
            number = int(item.get("episodeNumber") or 0)
        except (TypeError, ValueError):
            continue
        body = str(item.get("body") or "").strip()
        if 1 <= number <= total and _content_char_len(body) >= MIN_EPISODE_CONTENT_CHARS:
            done += 1
    return done


def _content_char_len(text: str) -> int:
    return len("".join((text or "").split()))


def format_summary_text(summary: dict[str, Any]) -> str:
    # Human-readable outline for UI / LLM context
    lines = [
        f"集数：{summary.get('episodeCount', '')}",
        f"类型：{summary.get('storyType', '')}",
        f"受众：{summary.get('targetAudience', '')}",
        f"钩子：{summary.get('coreHook', '')}",
        f"一句话：{summary.get('oneLineStory', '')}",
        "",
        "人物：",
    ]
    for c in summary.get("characters") or []:
        if isinstance(c, dict):
            lines.append(
                f"- {c.get('name', '')}（{c.get('roleType', '')}/{c.get('title', '')}）："
                f"{c.get('visualImage', '')}；标签：{c.get('coreTags', '')}；"
                f"弧光：{c.get('growthArc', '')}"
            )
    lines.extend(["", "梗概：", str(summary.get("synopsis") or "")])
    return "\n".join(lines)


def _format_episode_title_list(episodes: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in sorted(episodes, key=lambda x: int(x.get("episodeNumber") or 0)):
        num = item.get("episodeNumber")
        title = item.get("title") or f"第 {num} 集"
        rows.append(f"第 {num} 集：{title}")
    return "\n".join(rows) if rows else "（暂无分集规划）"


def _format_existing_episode_content(episodes: list[dict[str, Any]], limit: int = 3) -> str:
    # 仅附最近若干集正文，控制上下文长度
    completed = [
        item
        for item in episodes
        if isinstance(item, dict) and str(item.get("body") or item.get("content") or "").strip()
    ]
    completed.sort(key=lambda x: int(x.get("episodeNumber") or 0))
    if not completed:
        return "（暂无，本批次从开篇写起）"
    tail = completed[-limit:]
    blocks: list[str] = []
    for item in tail:
        num = item.get("episodeNumber")
        title = item.get("title") or f"第 {num} 集"
        body = str(item.get("body") or item.get("content") or "").strip()
        # 过长时截断尾部摘要，避免挤占当前集生成空间
        if len(body) > 1800:
            body = body[:1800] + "\n…（上文已截断）"
        blocks.append(f"{num}.{title}：\n{body}")
    return "\n\n".join(blocks)


def _titles_ready(existing: list[dict[str, Any]], total: int) -> bool:
    titled = {
        int(item.get("episodeNumber") or 0)
        for item in existing
        if isinstance(item, dict)
        and str(item.get("title") or "").strip()
        and not str(item.get("title") or "").startswith("第 ")
    }
    # 也接受「第 N 集」以外、或至少有 total 条带 title 的记录
    with_title = [
        item
        for item in existing
        if isinstance(item, dict)
        and 1 <= int(item.get("episodeNumber") or 0) <= total
        and str(item.get("title") or "").strip()
    ]
    if len(with_title) >= total:
        # 若全是占位「第 N 集」则仍需重跑大纲
        placeholder_only = all(
            str(item.get("title") or "").strip() in {f"第 {item.get('episodeNumber')} 集", f"第{item.get('episodeNumber')}集"}
            for item in with_title
        )
        return not placeholder_only
    return len(titled) >= total


async def run_episode_outline(
    creative: str,
    summary: dict[str, Any],
    episode_count: int,
) -> list[dict[str, Any]]:
    # 生成全集集名大纲
    summary_text = format_summary_text(summary)
    user = "\n".join(
        [
            f"总集数：{episode_count} 集（episodes 数组必须恰好 {episode_count} 项）",
            "",
            f"原始创意：\n{(creative or '').strip()}",
            "",
            f"剧本摘要：\n{summary_text}",
            "",
            "请输出全部分集的 episodeNumber 与 title。",
        ]
    )
    data = await drama_chat_json(EPISODE_OUTLINE_SYSTEM, user, max_tokens=4096)
    episodes = data.get("episodes") if isinstance(data, dict) else data
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("分集大纲返回格式无效")
    result: list[dict[str, Any]] = []
    for i, item in enumerate(episodes):
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("episodeNumber") or (i + 1))
        except (TypeError, ValueError):
            number = i + 1
        title = str(item.get("title") or "").strip() or f"第 {number} 集"
        result.append({"episodeNumber": number, "title": title, "body": ""})
    if len(result) < episode_count:
        # 补齐缺失集号
        have = {int(x["episodeNumber"]) for x in result}
        for n in range(1, episode_count + 1):
            if n not in have:
                result.append({"episodeNumber": n, "title": f"第 {n} 集", "body": ""})
    result.sort(key=lambda x: int(x["episodeNumber"]))
    return result[:episode_count]


async def ensure_episode_outline(
    creative: str,
    summary: dict[str, Any],
    existing: list[dict[str, Any]],
    total: int,
) -> tuple[list[dict[str, Any]], bool]:
    """返回 (合并后分集列表, 是否实际调用 LLM 生成大纲)。"""
    if _titles_ready(existing, total):
        return existing, False
    outline = await run_episode_outline(creative, summary, total)
    return merge_episode_bodies(outline, existing), True


async def run_episode_script_batch(
    summary: dict[str, Any],
    existing: list[dict[str, Any]],
    batch_size: int = 1,
    total: int | None = None,
    creative: str = "",
) -> list[dict[str, Any]]:
    # 按缺失集号生成下一批正文（默认逐集）
    target = int(total or summary.get("episodeCount") or 12)
    have_body = {
        int(item.get("episodeNumber") or 0)
        for item in existing
        if isinstance(item, dict)
        and _content_char_len(str(item.get("body") or item.get("content") or ""))
        >= MIN_EPISODE_CONTENT_CHARS
    }
    missing = [n for n in range(1, target + 1) if n not in have_body]
    if not missing:
        return []
    start = missing[0]
    end = start
    for i in range(1, min(batch_size, len(missing))):
        if missing[i] != end + 1:
            break
        end = missing[i]

    title_by_num = {
        int(item.get("episodeNumber") or 0): str(item.get("title") or "")
        for item in existing
        if isinstance(item, dict)
    }
    batch_titles = "\n".join(
        f"第 {n} 集：{title_by_num.get(n) or f'第 {n} 集'}" for n in range(start, end + 1)
    )
    batch_size_n = end - start + 1
    summary_text = format_summary_text(summary)
    user = "\n".join(
        [
            f"当前任务：撰写第 {start} 集至第 {end} 集（共 {batch_size_n} 集）的完整剧本正文",
            f"全剧共 {target} 集",
            f"episodes 输出数组必须恰好 {batch_size_n} 项，episodeNumber 从 {start} 到 {end}",
            f"每集 content 不少于 {MIN_EPISODE_CONTENT_CHARS} 汉字，含 3-5 场戏、充分 △ 动作与台词",
            "",
            f"原始创意：\n{(creative or '').strip() or '（无额外创意，以摘要为准）'}",
            "",
            f"剧本摘要：\n{summary_text}",
            "",
            f"全剧分集规划：\n{_format_episode_title_list(existing)}",
            "",
            f"本批次待撰写：\n{batch_titles}",
            "",
            f"已有剧集正文：\n{_format_existing_episode_content(existing)}",
            "",
            f"请输出第 {start}–{end} 集各集的 content 字段（可附带 title）。",
        ]
    )

    data = await drama_chat_json(
        EPISODE_BATCH_CONTENT_SYSTEM,
        user,
        temperature=0.6,
        max_tokens=16384,
    )

    episodes = data.get("episodes") if isinstance(data, dict) else data
    if not isinstance(episodes, list):
        raise ValueError("分集剧本返回格式无效")

    normalized = _normalize_batch_episodes(episodes, start, end, title_by_num)
    # 正文过短则带强调提示重试一次
    too_short = [
        item
        for item in normalized
        if _content_char_len(str(item.get("body") or "")) < MIN_EPISODE_CONTENT_CHARS
    ]
    if too_short:
        retry_user = (
            user
            + "\n\n上次输出过短。请重写本批次，每集 content 必须 ≥ "
            + str(MIN_EPISODE_CONTENT_CHARS)
            + " 汉字，包含完整场次、△ 动作与对白，不得压缩成梗概。"
        )
        retry = await drama_chat_json(
            EPISODE_BATCH_CONTENT_SYSTEM,
            retry_user,
            temperature=0.6,
            max_tokens=16384,
        )
        retry_eps = retry.get("episodes") if isinstance(retry, dict) else retry
        if isinstance(retry_eps, list):
            normalized = _normalize_batch_episodes(retry_eps, start, end, title_by_num)

    if not normalized:
        raise ValueError(f"模型未返回第 {start}–{end} 集正文")
    return normalized


def _normalize_batch_episodes(
    episodes: list[Any],
    start: int,
    end: int,
    title_by_num: dict[int, str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for offset, item in enumerate(episodes):
        if not isinstance(item, dict):
            continue
        number = item.get("episodeNumber") or item.get("episode_number") or (start + offset)
        try:
            number_i = int(number)
        except (TypeError, ValueError):
            number_i = start + offset
        if number_i < start or number_i > end:
            continue
        body = str(item.get("content") or item.get("body") or "").strip()
        if not body:
            continue
        title = (
            str(item.get("title") or "").strip()
            or title_by_num.get(number_i)
            or f"第 {number_i} 集"
        )
        normalized.append(
            {
                "episodeNumber": number_i,
                "title": title,
                "body": body,
            }
        )
    return normalized
