"""从剧本摘要与分集正文抽取道具（对齐 manju extractPropsMaterials，已停用素材）。"""

from __future__ import annotations

import json
from typing import Any

from app.services.drama.llm import drama_chat_json

SUMMARY_TEXT_MAX = 4000
EPISODE_SAMPLE_MAX = 2500

SYSTEM_PROMPT = """你是短剧美术统筹，负责从剧本摘要与分集正文中整理「道具」资产清单，供后续 AI 生图使用。

道具（props）：
- 可被角色持有、传递、特写的物件（兵器、信物、刑具、神器、文书等）
- 只保留对剧情有辨识度的关键道具，控制在 8–20 个
- 不要把地点、角色、天气现象、气氛空镜当成道具

输出要求：
1. 名称简短有辨识度；visualPrompt 用简体中文，每条 90–200 字，可直接作生图提示词
2. visualPrompt 须含：材质/形制、色彩、尺度、磨损或做旧、戏剧符号、建议构图（特写/俯拍等）
3. 必须输出严格 JSON 对象（不要 markdown）：{"props":[{"name":"...","visualPrompt":"..."}]}
4. 不要输出 materials / 素材字段
"""


# 按名称去重（保留首次）
def _dedupe_by_name(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        prompt = str(item.get("visualPrompt") or item.get("visualImage") or "").strip()
        if len(prompt) < 8:
            continue
        seen.add(name)
        result.append({"name": name, "visualPrompt": prompt})
    return result


# 规范化 LLM 返回
def _normalize_payload(raw: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {"props": [], "materials": []}

    def read_list(key: str) -> list[dict[str, Any]]:
        value = raw.get(key)
        if not isinstance(value, list):
            return []
        out: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(item)
        return out

    return {"props": read_list("props"), "materials": []}


async def extract_props_materials(
    *,
    summary: dict[str, Any] | None,
    episode_bodies: list[str],
) -> dict[str, list[dict[str, str]]]:
    """调用 LLM 抽取道具（materials 恒为空，兼容旧调用方）。

    Returns:
        {"props": [{"name","visualPrompt"}], "materials": []}
    """
    summary_text = json.dumps(summary or {}, ensure_ascii=False)
    samples = [b.strip() for b in episode_bodies if (b or "").strip()][:6]
    if samples:
        episode_block = "\n\n".join(
            f"【分集样例 {i + 1}】\n{text[:EPISODE_SAMPLE_MAX]}" for i, text in enumerate(samples)
        )
    else:
        episode_block = "（暂无分集正文）"

    user = "\n".join(
        [
            "【剧本摘要】",
            summary_text[:SUMMARY_TEXT_MAX],
            "",
            episode_block,
            "",
            "请抽取 props（不要输出 materials）。",
        ]
    )
    raw = await drama_chat_json(SYSTEM_PROMPT, user, max_tokens=4096)
    normalized = _normalize_payload(raw)
    return {
        "props": _dedupe_by_name(normalized["props"]),
        "materials": [],
    }
