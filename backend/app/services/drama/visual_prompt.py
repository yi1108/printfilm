"""根据角色/场景设定解析资产生图提示词（规则 + LLM）。"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models_drama import DramaAsset, DramaProject
from app.services.billing import record_llm_chat_line
from app.services.drama.llm import drama_chat_text
from app.services.llm_client import LlmUnavailableError
from app.services.drama.seed import _episode_bodies
from app.services.drama.seed_asset_params import (
    build_scene_params,
    compose_character_visual_text,
)
from app.services.drama.voice_prompt import find_summary_character

logger = logging.getLogger(__name__)

WEAK_PROMPT_PATTERN = re.compile(
    r"^(character|scene|prop|material|none|image|audio|video)\s+\S+$",
    re.IGNORECASE,
)

# 模板化套话：出现且总长偏短则视为需 AI 重写
GENERIC_TEMPLATE_MARKERS = (
    "影视级写实环境空间",
    "构图层次分明、光影有戏剧张力",
    "适合短剧横屏拍摄",
    "影视级写实人物",
    "白底全身定妆照",
    "材质与氛围清晰，构图简洁",
    "影视级静物/空镜",
)

MIN_PROMPT_LEN: dict[str, int] = {
    "character": 120,
    "scene": 100,
    "prop": 70,
    "material": 70,
}

CHARACTER_VISUAL_SYSTEM = """你是短剧美术造型指导，为 Seedream 生图写「视觉形象描述」。

优秀示例（仅作密度与写法参考，勿照抄）：
「男性，二十岁左右，身形清瘦，面容带有山野少年的质朴与英气，肤色健康小麦色。头发用简单木簪束起，身穿以禽羽编织的轻甲，外罩粗麻短褐，腰系兽皮绳，脚踏草编凉鞋。气质机敏幽默，眼神明亮，嘴角常带笑意，像能辨兽语的青年猎手。」

输出要求：
1. 只输出一条简体中文，150–380 字，不要 JSON、不要标题、不要引号、不要「性格：」类字段标签
2. 必须具体可拍：性别年龄、脸型五官、发型、体型、服饰分层（材质/颜色/纹样）、配饰道具、站姿气质、神态
3. 把身份、性格、关系转化为可见视觉特征（如「沉稳」→ 肩背挺直、眼神低垂）
4. 贴合故事类型与项目美学；描述须适配白底角色设定板（正/左侧/背三视图 + 面部大头 + 半身像），勿写构图指令本身
5. 禁止空泛套话（如「五官清晰」「气质出众」），禁止剧情梗概与台词"""

SCENE_VISUAL_SYSTEM = """你是短剧场景美术指导，为 Seedream 生图写「环境空间描述」。

优秀示例（仅作密度参考）：
「上古治水工地临时营帐区，午后偏硬的自然光。前景是泥泞夯土与散落的竹编筐、绳索，中景多顶粗麻营帐错落，帐外竖木桩挂兽皮与羽旗。背景可见疏朗山林与远处河滩反光，空气里有尘土与烟火气，色调偏土黄与灰绿，压抑中透出劳作紧迫感的横屏影视场景。」

输出要求：
1. 只输出一条简体中文，150–380 字，不要 JSON、不要标题、不要引号
2. 须写清：空间类型、时代感、围合与立面要素（门窗/墙面/装修）、功能分区、关键陈设、光影、色调、氛围
3. 以环境为主体，不写人物特写；可写无人痕迹（脚印、余烬、法阵光痕）
4. 描述须适配「平视+俯视合图、左侧多面立面、右侧 2～4 处区域细节」的设计参考图，勿写构图指令本身
5. 结合场戏摘录中的 △ 动作与道具，还原可拍摄的空间
6. 禁止「影视级写实」「构图层次分明」等空泛套话"""

PROP_VISUAL_SYSTEM = """你是短剧道具美术，为 Seedream 写「道具本体视觉描述」。

输出要求：
1. 只输出一条简体中文，100–220 字，不要 JSON、不要标题、不要引号
2. 须写清：物件类型、整体外形与比例、材质分层、颜色、关键结构（开口/机关/铭文/纹样）、磨损做旧、戏剧符号
3. 描述须适配白底道具设定板（正/左侧/背三视图 + 关键局部特写 + 材质结构特写），勿写构图指令本身
4. 以物件为主体，不写人物手持或肖像；禁止空泛套话"""

MATERIAL_VISUAL_SYSTEM = """你是短剧气氛美术，为 Seedream 写空镜/气氛静帧描述。
输出 100–220 字简体中文：景别、构图、光影、色调、氛围情绪、运动暗示（烟/水/光），适合 16:9 横屏。不要人物正脸。不要 JSON。"""


# 是否命中模板套话且整体偏短
def is_generic_template_prompt(text: str) -> bool:
    stripped = (text or "").strip()
    if len(stripped) >= 180:
        return False
    hits = sum(1 for marker in GENERIC_TEMPLATE_MARKERS if marker in stripped)
    return hits >= 1 or (stripped.startswith("场景：") and len(stripped) < 120)


# 判断当前提示词是否过短、占位或模板化
def is_weak_visual_prompt(prompt: str, asset_name: str, kind: str) -> bool:
    text = (prompt or "").strip()
    kind_lower = (kind or "").strip().lower()
    min_len = MIN_PROMPT_LEN.get(kind_lower, 60)
    if len(text) < min_len:
        return True
    name = (asset_name or "").strip()
    if name and text.lower() in {f"{kind_lower} {name}".lower(), name.lower()}:
        return True
    if WEAK_PROMPT_PATTERN.match(text):
        return True
    if is_generic_template_prompt(text):
        return True
    # 角色若只有「身份：」「标签：」字段堆叠而无足够 visualImage 密度
    if kind_lower == "character" and text.count("：") >= 3 and len(text) < 160:
        label_hits = sum(1 for label in ("身份：", "定位：", "标签：", "性格：", "背景：") if label in text)
        if label_hits >= 2 and "，" not in text[:40]:
            return True
    return False


# 从资产 params 与摘要拼角色上下文
def build_character_visual_context(
    asset: DramaAsset,
    summary_char: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> str:
    params = asset.params if isinstance(asset.params, dict) else {}
    summary_char = summary_char or {}

    def pick(*keys: str) -> str:
        for key in keys:
            raw = params.get(key)
            if raw is None and summary_char:
                raw = summary_char.get(key)
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
        ("已有外形描述", pick("visualImage", "visualPrompt")),
    ]
    for label, value in mapping:
        if value:
            lines.append(f"{label}：{value}")
    if summary:
        for key, label in (
            ("storyType", "故事类型"),
            ("oneLineStory", "一句话故事"),
            ("coreHook", "核心钩子"),
        ):
            val = str(summary.get(key) or "").strip()
            if val:
                lines.append(f"{label}：{val}")
        syn = str(summary.get("synopsis") or "").strip()
        if syn:
            lines.append(f"故事梗概：{syn[:500]}")
    return "\n".join(lines)


# 从 params + 摘要规则拼接角色生图提示词
def fallback_character_visual_prompt(
    asset: DramaAsset,
    summary_char: dict[str, Any] | None = None,
) -> str:
    params = asset.params if isinstance(asset.params, dict) else {}
    merged = {**(summary_char or {}), **{k: v for k, v in params.items() if v}}
    if asset.name and not merged.get("name"):
        merged["name"] = asset.name
    text = compose_character_visual_text(merged)
    if text:
        return normalize_visual_prompt_text(text)
    name = asset.name or "角色"
    return normalize_visual_prompt_text(
        f"{name}，青年，身形匀称，面容清晰，发型与服饰符合上古神话短剧设定，"
        f"白底全身站立，神态自然，影视定妆照。"
    )


# 从场戏正文提取与场景名相关的摘录
def collect_scene_excerpts(bodies: list[str], scene_name: str, max_chars: int = 3200) -> str:
    target = (scene_name or "").strip()
    if not target:
        return ""
    chunks: list[str] = []
    for body in bodies:
        if target not in body:
            continue
        for block in re.split(r"(?=###\s*场)", body):
            head = block[:280]
            if target in head or target in block[:160]:
                snippet = block.strip()
                if len(snippet) > 40:
                    chunks.append(snippet[:1200])
    if not chunks:
        for body in bodies:
            idx = body.find(target)
            if idx >= 0:
                start = max(0, idx - 200)
                chunks.append(body[start : idx + 600].strip())
    return "\n---\n".join(chunks[:5])[:max_chars]


# 规则拼接场景生图提示词
def fallback_scene_visual_prompt(
    asset: DramaAsset,
    summary: dict[str, Any] | None,
    episode_bodies: list[str] | None = None,
) -> str:
    story_type = str((summary or {}).get("storyType") or "").strip()
    base = build_scene_params(asset.name or "场景", story_type)["visualPrompt"]
    excerpt = collect_scene_excerpts(episode_bodies or [], asset.name or "")
    if excerpt:
        return normalize_visual_prompt_text(f"{base}。场戏环境与动作参考：{excerpt[:400]}")
    return normalize_visual_prompt_text(base)


# 清洗 LLM 输出
def normalize_visual_prompt_text(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^[\"'「『]|[\"'」』]$", "", text).strip()
    text = re.sub(r"^(视觉形象描述|环境描述|道具描述)[:：]\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text[:680]


# 合并规则稿与 LLM 稿，避免过短
def merge_visual_prompts(rule_prompt: str, llm_prompt: str, *, min_len: int = 100) -> str:
    rule = normalize_visual_prompt_text(rule_prompt)
    llm = normalize_visual_prompt_text(llm_prompt)
    if len(llm) >= min_len and not is_generic_template_prompt(llm):
        return llm
    if rule and llm:
        merged = normalize_visual_prompt_text(f"{llm}。{rule}" if len(llm) < len(rule) else f"{rule}。{llm}")
        if len(merged) >= min_len:
            return merged
    return llm or rule


async def _llm_visual_prompt(
    system: str,
    user: str,
    *,
    min_len: int = 80,
    db: AsyncSession | None = None,
    user_id: int | None = None,
    drama_project_id: int | None = None,
) -> str:
    raw = await drama_chat_text(system, user, temperature=0.6, max_tokens=1024)
    prompt = normalize_visual_prompt_text(raw)
    if db is not None and user_id is not None:
        await record_llm_chat_line(
            db,
            user_id=user_id,
            domain="drama",
            drama_project_id=drama_project_id,
        )
    return prompt if len(prompt) >= min_len else ""


async def resolve_visual_prompt_for_asset(
    asset: DramaAsset,
    project: DramaProject,
    incoming_prompt: str | None = None,
    *,
    force_refresh: bool = False,
    strict_llm: bool = False,
    db: AsyncSession | None = None,
) -> str:
    """解析资产生图用的用户描述（过短/模板化则规则 + LLM 补全）。"""
    kind = (asset.type or "character").lower()
    name = asset.name or ""
    params = asset.params if isinstance(asset.params, dict) else {}
    stored = str(
        params.get("visualPrompt") or params.get("visualImage") or incoming_prompt or ""
    ).strip()

    summary: dict[str, Any] | None = None
    if project.script and isinstance(project.script.summary, dict):
        summary = project.script.summary
    bodies = _episode_bodies(project.script.episode_content) if project.script else []

    if not force_refresh and stored and not is_weak_visual_prompt(stored, name, kind):
        return stored

    min_len = MIN_PROMPT_LEN.get(kind, 80)
    llm_bill = {"db": db, "user_id": project.user_id, "drama_project_id": project.id}

    if kind == "character":
        summary_char = find_summary_character(summary, name)
        rule_prompt = fallback_character_visual_prompt(asset, summary_char)

        context = build_character_visual_context(asset, summary_char, summary)
        style_id = str((project.params or {}).get("image_style_id") or "").strip()
        if style_id:
            context += f"\n项目画面风格 ID：{style_id}"
        try:
            llm = await _llm_visual_prompt(
                CHARACTER_VISUAL_SYSTEM,
                f"请为以下角色生成视觉形象描述：\n\n{context}",
                min_len=80,
                **llm_bill,
            )
            prompt = merge_visual_prompts(rule_prompt, llm, min_len=min_len)
            if len(prompt) >= min_len or len(prompt) >= 80:
                return prompt
            if strict_llm:
                raise RuntimeError(f"角色「{name}」AI 提示词过短（{len(prompt)} 字）")
        except LlmUnavailableError:
            raise
        except Exception as exc:
            if strict_llm:
                raise RuntimeError(f"角色「{name}」AI 提示词生成失败") from exc
            logger.exception("角色视觉提示词 LLM 失败 asset_id=%s", asset.id)
        return rule_prompt

    if kind == "scene":
        rule_prompt = fallback_scene_visual_prompt(asset, summary, bodies)

        excerpt = collect_scene_excerpts(bodies, name)
        story_bits = []
        if summary:
            story_bits.append(f"故事类型：{summary.get('storyType') or ''}")
            story_bits.append(f"一句话：{summary.get('oneLineStory') or ''}")
            syn = str(summary.get("synopsis") or "").strip()
            if syn:
                story_bits.append(f"梗概：{syn[:500]}")
        user_msg = "\n".join(
            [
                f"场景名：{name}",
                *story_bits,
                f"场戏摘录：\n{excerpt}" if excerpt else "（暂无场戏摘录，请根据场景名与故事类型合理补全）",
            ]
        )
        try:
            llm = await _llm_visual_prompt(SCENE_VISUAL_SYSTEM, user_msg, min_len=80, **llm_bill)
            prompt = merge_visual_prompts(rule_prompt, llm, min_len=min_len)
            if len(prompt) >= min_len or len(prompt) >= 80:
                return prompt
            if strict_llm:
                raise RuntimeError(f"场景「{name}」AI 提示词过短（{len(prompt)} 字）")
        except LlmUnavailableError:
            raise
        except Exception as exc:
            if strict_llm:
                raise RuntimeError(f"场景「{name}」AI 提示词生成失败") from exc
            logger.exception("场景视觉提示词 LLM 失败 asset_id=%s", asset.id)
        return rule_prompt

    if kind in {"prop", "material", "none"}:
        rule_prompt = stored or normalize_visual_prompt_text(
            f"{name}，{'关键道具' if kind == 'prop' else '气氛空镜'}，"
            f"材质细节清晰，戏剧感强，背景简洁。"
        )

        system = PROP_VISUAL_SYSTEM if kind == "prop" else MATERIAL_VISUAL_SYSTEM
        ctx = f"名称：{name}\n"
        if summary:
            ctx += f"故事类型：{summary.get('storyType') or ''}\n"
        if stored:
            ctx += f"已有描述：{stored}\n"
        excerpt = collect_scene_excerpts(bodies, name)
        if excerpt:
            ctx += f"剧本相关摘录：\n{excerpt[:800]}"
        try:
            llm = await _llm_visual_prompt(system, ctx, min_len=60, **llm_bill)
            prompt = merge_visual_prompts(rule_prompt, llm, min_len=min_len)
            if len(prompt) >= 60:
                return prompt
            if strict_llm:
                raise RuntimeError(f"「{name}」AI 提示词过短（{len(prompt)} 字）")
        except LlmUnavailableError:
            raise
        except Exception as exc:
            if strict_llm:
                raise RuntimeError(f"「{name}」AI 提示词生成失败") from exc
            logger.exception("%s 视觉提示词 LLM 失败 asset_id=%s", kind, asset.id)
        return rule_prompt

    if stored and len(stored) >= min_len:
        return stored
    return normalize_visual_prompt_text(f"{name}，影视级静物/空镜，材质与氛围清晰，构图简洁。")
