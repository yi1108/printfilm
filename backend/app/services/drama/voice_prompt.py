"""根据角色设定生成音色描述提示词（供 TTS / Seedance reference_audio）。"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.models_drama import DramaAsset, DramaProject
from app.services.drama.llm import drama_chat_text
from app.services.drama.voice_synthesis import build_voice_sample_text
from app.services.voices import infer_drama_speaker_from_prompt

logger = logging.getLogger(__name__)

VOICE_PROMPT_SYSTEM = """你是短剧配音导演。根据角色设定，输出一条「音色描述」供 TTS 试听与 Seedance 视频 reference_audio 使用。

要求：
1. 只输出一条简体中文描述，50–120 字，不要 JSON、不要标题、不要引号包裹
2. 须明确或可推断：年龄感、性别、声线质感（清亮/低沉/沙哑/童声等）、语速、吐字、语气与情绪基调
3. 须贴合角色身份、性格与故事类型（古装神话/都市悬疑等）
4. 偏「配音选角说明」口吻，便于 TTS 与视频模型理解，避免写台词或剧情梗概"""

WHITESPACE_PATTERN = re.compile(r"\s+")


# 从剧本摘要中按名称查找角色
def find_summary_character(summary: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    if not summary or not name:
        return None
    target = name.strip()
    for ch in summary.get("characters") or []:
        if isinstance(ch, dict) and str(ch.get("name") or "").strip() == target:
            return ch
    return None


# 合并资产 params 与摘要字段，组装 LLM 输入
def build_character_voice_context(
    asset: DramaAsset,
    summary_char: dict[str, Any] | None = None,
) -> str:
    params = asset.params if isinstance(asset.params, dict) else {}
    summary = summary_char or {}

    def pick(*keys: str) -> str:
        for key in keys:
            raw = params.get(key)
            if raw is None and summary:
                raw = summary.get(key)
            text = str(raw or "").strip()
            if text:
                return text
        return ""

    lines = [f"角色名：{asset.name or '未命名'}"]
    mapping = [
        ("称谓", pick("title")),
        ("角色类型", pick("roleType")),
        ("核心标签", pick("coreTags")),
        ("身份背景", pick("identityBackground")),
        ("成长经历", pick("growthExperience")),
        ("性格", pick("personality")),
        ("人物关系", pick("relationships")),
        ("成长弧线", pick("growthArc")),
        ("外形气质", pick("visualImage", "visualPrompt")),
        ("人物介绍", pick("introText", "intro")),
    ]
    for label, value in mapping:
        if value:
            lines.append(f"{label}：{value}")
    return "\n".join(lines)


# 清洗 LLM 输出的音色描述
def normalize_voice_prompt_text(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^[\"'「『]|[\"'」』]$", "", text).strip()
    text = WHITESPACE_PATTERN.sub(" ", text)
    return text[:200]


# 无 LLM 时的规则兜底
def fallback_voice_prompt(asset: DramaAsset, summary_char: dict[str, Any] | None = None) -> str:
    params = asset.params if isinstance(asset.params, dict) else {}
    summary = summary_char or {}
    name = asset.name or "角色"
    role = str(params.get("roleType") or summary.get("roleType") or "").strip()
    personality = str(params.get("personality") or summary.get("personality") or "").strip()
    visual = str(params.get("visualImage") or summary.get("visualImage") or "").strip()

    age_gender = "青年"
    if any(k in f"{role}{personality}{visual}" for k in ("童", "少年", "幼")):
        age_gender = "少年"
    elif any(k in f"{role}{personality}{visual}" for k in ("老", "翁", "婆", "长")):
        age_gender = "中老年"
    if any(k in f"{role}{personality}{visual}" for k in ("女", "娘", "妃", "后", "妹")):
        tone = f"{age_gender}女声，吐字清晰，语速自然偏慢"
    elif any(k in f"{role}{personality}{visual}" for k in ("男", "公", "王", "将", "伯", "禹")):
        tone = f"{age_gender}男声，吐字清晰，语速沉稳"
    else:
        tone = f"{age_gender}声线，吐字清晰，语速适中"

    mood = "语气平和"
    if personality:
        if any(k in personality for k in ("冷", "峻", "狠", "刚")):
            mood = "语气冷峻克制"
        elif any(k in personality for k in ("温", "柔", "善", "仁")):
            mood = "语气温厚柔和"
        elif any(k in personality for k in ("活", "皮", "俏", "灵")):
            mood = "语气活泼清亮"

    return f"{name}：{tone}，{mood}，贴合{role or '角色'}身份。"


async def suggest_voice_prompt_for_character(
    asset: DramaAsset,
    project: DramaProject,
) -> tuple[str, str, str]:
    """根据角色资产与剧本摘要生成音色描述、推荐 speaker 与试听台词。"""
    summary = None
    if project.script and isinstance(project.script.summary, dict):
        summary = project.script.summary
    summary_char = find_summary_character(summary, asset.name or "")
    context = build_character_voice_context(asset, summary_char)

    logger.info(
        "生成音色提示词 project_id=%s asset_id=%s name=%s context_len=%s",
        project.id,
        asset.id,
        asset.name,
        len(context),
    )
    raw = await drama_chat_text(
        VOICE_PROMPT_SYSTEM,
        f"请为以下角色生成音色描述：\n\n{context}",
        temperature=0.6,
        max_tokens=512,
    )
    prompt = normalize_voice_prompt_text(raw)
    if len(prompt) < 8:
        prompt = fallback_voice_prompt(asset, summary_char)
    name = asset.name or "角色"
    speaker = infer_drama_speaker_from_prompt(prompt, character_name=name, asset_id=asset.id)
    sample_text = build_voice_sample_text(prompt, name, short=False)
    return prompt, speaker, sample_text
