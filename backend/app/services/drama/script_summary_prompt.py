"""剧本摘要 Agent 提示词与用户消息（对齐 manju scriptSummary）。"""

from __future__ import annotations

from app.services.drama.image_styles import (
    IMAGE_STYLE_IDS,
    get_image_style_label,
    resolve_image_style_prompt,
)

# SCRIPT_SUMMARY_SYSTEM_PROMPT 指导 LLM 将原始创意转为结构化剧本摘要
SCRIPT_SUMMARY_SYSTEM_PROMPT = """你是专业的短剧/网剧剧本策划，负责把用户提供的原始创意、故事大纲或灵感，整理成可直接用于立项与编剧开工的结构化「剧本摘要」。

输出要求：
1. 忠实于用户创意，可合理补全细节，但不要擅自改掉核心设定、主线与结局
2. 若用户提供了目标集数，episodeCount 必须与该值完全一致；未提供时根据故事体量合理估算（短篇 12–24 集，中篇 30–60 集，长篇可更高）
3. 若用户提供了画面风格，人物 visualImage 须体现该风格的视觉美学，storyType 可融合风格相关标签
4. storyType、coreHook 用「+」连接多个标签，风格参考：古风奇幻+神话后传+反乌托邦
5. targetAudience 简洁，如：男频 / 大众、女频 / 青年 等
6. oneLineStory 一句话说清主线 + 最大反转或钩子
7. characters 须覆盖故事中全部具名出场角色（主角、重要配角、反派）；群演/路人可合并为 1 个群体角色；每人字段须饱满、可拍摄、有戏剧张力；不要只写 2–3 个主角而漏掉其余具名人物。禁止把「音色 / 声音 / 旁白音色」或带（声音）（音色）后缀的名字写成角色；旁白若需出场可写「某某旁白」本体，不要单独建「某某（声音）」
8. 人物小传中 growthArc 必须用「阶段A -> 阶段B -> 阶段C」格式
9. synopsis 用一段完整中文叙述故事，从世界观、矛盾、结盟、高潮、结局到余韵，长度 200–400 字
10. 语言统一使用简体中文，偏影视策划文档风格，避免空泛形容词堆砌
11. 每人 visualImage 须 100–200 字：写清性别年龄、脸型五官、发型、体型、服饰材质与配色、气质神态、标志性道具或细节；可直接作 AI 定妆照提示词；禁止仅写「英俊」「美丽」等空泛词
12. characters 建议 5–12 人；确有大量具名配角时宁可多列，也不要省略会反复出场的名字

必须输出严格 JSON 对象（不要 markdown、不要代码围栏），字段：
{
  "episodeCount": number,
  "storyType": string,
  "targetAudience": string,
  "coreHook": string,
  "oneLineStory": string,
  "characters": [
    {
      "name": string,
      "title": string,
      "roleType": string,
      "visualImage": string,
      "coreTags": string,
      "identityBackground": string,
      "growthExperience": string,
      "personality": string,
      "relationships": string,
      "growthArc": string
    }
  ],
  "synopsis": string
}"""


# 解析合法的画面风格 ID
def _resolve_image_style_id(style_id: str | None) -> str | None:
    if not style_id:
        return None
    sid = style_id.strip()
    return sid if sid in IMAGE_STYLE_IDS else None


# 将入参格式化为 LLM 用户消息（对齐 manju buildScriptSummaryUserMessage）
def build_script_summary_user_message(
    creative: str,
    *,
    episode_count: int | None = None,
    image_style_id: str | None = None,
) -> str:
    trimmed = (creative or "").strip()
    sections = [f"原始创意：\n{trimmed}"]
    production_params: list[str] = []

    if episode_count is not None:
        production_params.append(
            f"- 目标集数：{episode_count} 集（输出中的 episodeCount 必须与该值完全一致，不得自行修改）"
        )

    resolved_style = _resolve_image_style_id(image_style_id)
    if resolved_style:
        label = get_image_style_label(resolved_style)
        style_prompt = resolve_image_style_prompt(resolved_style)
        production_params.append(f"- 画面风格：{label}（{resolved_style}）")
        if style_prompt:
            production_params.append(f"  风格说明：{style_prompt}")
        production_params.append("  人物 visualImage、故事类型标签与整体美学须符合该画面风格")

    if production_params:
        sections.append("\n".join(["制作参数：", *production_params]))

    return "\n\n".join(sections)
