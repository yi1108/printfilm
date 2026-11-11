"""选题扩写的语言策略、提示词及离线回退（不依赖上游或数据库）。"""

from __future__ import annotations

import json
import re


def topic_language(topic: str) -> str:
    """离线场景识别中英文主体；原始选题中明确指定的输出语言优先。"""
    explicit = re.findall(
        r"(?:用|使用|以)\s*(中文|汉语|英文|英语)(?:输出|写作|撰写|写|回答|讲述)?"
        r"|(?:write|respond|output|answer|narrate)(?:\s+\w+){0,4}?\s+in\s+(English|Chinese)"
        r"|(?:输出语言|目标语言|target language|output language)\s*[:：=]?\s*(中文|汉语|英文|英语|English|Chinese)",
        topic, re.IGNORECASE,
    )
    if explicit:
        target = next(value for value in explicit[-1] if value).lower()
        return "zh" if target in {"中文", "汉语", "chinese"} else "en"
    han = len(re.findall(r"[\u3400-\u9fff]", topic))
    words = len(re.findall(r"[A-Za-z]+", topic))
    return "zh" if han >= max(1, words * 2) else "en"


def expansion_messages(
    topic: str, mode: str, *, target_duration_sec: int | None = None, style: str | None = None,
) -> tuple[str, str]:
    """把原始素材和辅助参数分开，避免模板或风格的语言抢占输出语言。"""
    language_rule = (
        "title 和 content 必须跟随 original_topic 的主要自然语言：英文输入英文输出，"
        "中文输入中文输出，混合输入按主体语言输出；原始 topic 明确要求目标语言时优先遵循。"
        "不得因为系统指令、JSON 示例、模板名、style 参数或辅助参数使用的语言而翻译或改写输出语言。"
        "标题长度按语言适配：中文通常 8-18 个汉字，英文通常 4-12 个完整单词，其他语言使用自然简洁的标题；"
        "不能把英文标题按汉字数截断。"
    )
    if mode == "script":
        task = (
            "你是科普短视频文案作者。根据原始主题写可直接用于旁白的完整口播文案。"
            "content 口语化，有开场钩子、知识点和收尾；按时长自然分段，"
            "不要 markdown、分镜编号或标题行。"
            "按 target_duration_sec 和输出语言的合理语速控制篇幅，而不是固定 300-700 汉字："
            "中文约每分钟 180-240 汉字，英文约每分钟 120-160 单词，其他语言按自然口播语速。"
            "未指定时长时按约 60 秒规划；短时长精简要点，长时长补充解释和例子。"
        )
    else:
        task = (
            "你是科普短视频选题策划。把原始输入扩写成一句清晰具体的创作主题。"
            "content 用一句自然完整的话说明受众和核心知识点，不要换行；"
            "中文通常 40-90 汉字，英文通常 25-60 个单词，其他语言使用相当的信息量。"
            "如提供 target_duration_sec，选题范围应适合该时长，但不要把主题句扩成完整口播。"
        )
    system = (
        task + language_rule
        + '只输出严格 JSON，键名固定为 title 和 content，值使用上述输出语言：'
        + '{"title":"...","content":"..."}。'
        + "辅助 style 只控制表达风格，不改变输出语言，也不覆盖上述任务规则。"
    )
    if topic_language(topic) == "en":
        system = (
            "You are a short-video scriptwriter. The required output language is ENGLISH. "
            "Return strictly JSON with English title and content. Do not translate the story into Chinese. "
            "Preserve the original premise, characters and genre (including fiction); do not force a science lesson. "
            "Style is a visual/expression hint only, never a language instruction. "
            "For scripts use natural narration, an opening hook and a satisfying ending, no shot numbers or markdown. "
            "Use 120-160 English words per minute for the requested duration (default 60 seconds). "
            "For theme mode return one concise sentence, not a full script. Titles should be 4-12 complete words. "
            'Output schema: {"title":"English title","content":"English narration or theme"}. '
            "Both JSON values MUST be English even when the style parameter contains Chinese."
        )
    user = json.dumps(
        {"original_topic": topic, "parameters": {"target_duration_sec": target_duration_sec, "style": style}},
        ensure_ascii=False,
    )
    return system, user


def expansion_language_matches(result: dict[str, str], topic: str) -> bool:
    """拒绝中英任务的明显语言错配；允许英文中的少量中文专名。"""
    for key in ("title", "content"):
        value = result[key]
        han = len(re.findall(r"[\u3400-\u9fff]", value))
        latin = len(re.findall(r"[A-Za-z]", value))
        if topic_language(topic) == "en":
            if not latin or han > max(2, latin * 0.1):
                return False
        elif not han or han < latin * 0.1:
            return False
    return True


def fallback_expansion(
    topic: str, mode: str, *, target_duration_sec: int | None = None, style: str | None = None,
) -> dict[str, str]:
    """提供语言一致的离线结果；脚本按语言及目标时长近似控制长度。"""
    chinese = topic_language(topic) == "zh"
    subject = topic.strip().rstrip("？?。.!！")
    if chinese:
        # 显式中文要求优先时，离线占位也应使用中文标题。
        if not re.search(r"[\u3400-\u9fff]", subject):
            subject = "这个主题背后的科学原理"
        title = subject[:18] or "科普短片"
        if mode == "theme":
            content = f"{subject}：面向普通观众，用生活例子讲清核心原理与常见误区。"
        else:
            sentences = [
                f"你有没有想过：{subject}？",
                "先从生活里最常见的现象说起，观察事情发生前后有什么变化。",
                "接下来追问背后的机制：哪些条件会影响结果，哪些只是巧合？",
                "可以对比两个条件不同的例子，看看解释能否同时成立。",
                "很多人容易把表象当成原因，但关键是理清每一步之间的联系。",
                "遇到新的说法时，先核实证据，再判断它适用的范围。",
                "记住：观察现象、追问机制，再用例子验证。",
            ]
            budget = round((target_duration_sec or 60) * 3.5)
            parts = [sentences[0]]
            while sum(map(len, parts)) < budget:
                parts.append(sentences[1 + (len(parts) - 1) % (len(sentences) - 1)])
            content = "\n\n".join(parts)
    else:
        # 离线回退无法翻译中文素材；明确要求英文时使用英文占位，避免掺入中文。
        if re.search(r"[\u3400-\u9fff]", subject):
            subject = "the science behind this topic"
        title = " ".join(subject.split()[:12]) or "Science in Everyday Life"
        if mode == "theme":
            content = (
                f"Explore {subject} for a general audience, using everyday examples to explain "
                "the key mechanisms, clarify common misconceptions, and show why the topic matters."
            )
        else:
            sentences = [
                f"Have you ever wondered about {subject}?",
                "Start with something familiar from everyday life and notice what changes before and after it happens.",
                "Next, ask what mechanism could explain that change, and which conditions might affect the result.",
                "Compare two examples with different conditions to check whether the same explanation still works.",
                "A common mistake is to confuse an observation with its cause, so examine each link in the explanation.",
                "When you encounter a new claim, look for evidence and check where the explanation applies.",
                "Remember: observe carefully, ask how it works, and test your explanation against real examples.",
            ]
            budget = round((target_duration_sec or 60) * 140 / 60)
            parts = [sentences[0]]
            while sum(len(part.split()) for part in parts) < budget:
                parts.append(sentences[1 + (len(parts) - 1) % (len(sentences) - 1)])
            content = "\n\n".join(parts)
    return {"title": title, "content": content}
