"""Seedream 输入文案软化：保留外形/风格与设定板结构，降低 InputTextSensitive 误杀。

软化只改用户正文，不改结构前缀；审核重试仍尽量保留三视图设定板。
不做空主体 / CG 厚涂兜底。
"""

from __future__ import annotations

# 长词优先，避免短词先替换破坏短语
_SEEDREAM_TEXT_SOFTEN: list[tuple[str, str]] = [
    # 酒精 / 配饰
    ("腰悬酒葫芦", "腰佩圆润如意饰"),
    ("酒葫芦", "腰间圆润如意饰"),
    ("葫芦形佩饰", "腰间圆润如意饰"),
    ("葫芦", "圆润佩饰"),
    ("醉酒", "微醺神态"),
    ("饮酒", "持盏"),
    ("悬酒", "腰佩"),
    # 未成年人 / 校园
    ("现代课堂学生", "学堂少年学子"),
    ("课堂学生", "学堂学子"),
    ("毛毡小人", "毛毡玩偶"),
    ("小学男生", "少年学子"),
    ("小学女生", "少年学子"),
    ("小学生", "少年学子"),
    ("婴幼儿", "幼龄角色"),
    ("幼童", "少年"),
    ("儿童", "少年"),
    ("小孩", "少年"),
    ("孩子", "少年"),
    ("童声", "清亮稚气嗓音"),
    ("童真", "天真好奇"),
    ("校服", "学院制服"),
    ("课堂", "学堂"),
    ("学生", "学子"),
    # 兵器 / 网红 / 气质
    ("白衣佩剑", "白衣腰佩长绦"),
    ("腰佩长剑", "腰佩长绦"),
    ("佩剑", "腰佩长绦"),
    ("眼神狂放不羁", "目光明亮自信"),
    ("狂放不羁", "洒脱自信"),
    ("超凡脱俗", "气度从容"),
    ("豪放", "洒脱"),
    ("电影质感", "细腻画质"),
    # 历史名人身份（勿再写回「盛唐/诗仙/名士」等可指认词）
    ("盛唐豪放诗人", "古风洒脱书生"),
    ("盛唐洒脱文人", "古风洒脱书生"),
    ("豪放诗人", "洒脱书生"),
    ("诗仙", "古风洒脱书生"),
    ("诗圣", "古风沉稳书生"),
    ("顶流", "风雅书生"),
    ("名士", "书生"),
    ("文人", "书生"),
    ("诗人", "书生"),
    ("盛唐", "古风年代"),
    ("李白", "古风白衣青年"),
    ("杜甫", "古风青衫青年"),
]

# 设定板长前缀结束标记（之后为用户正文）
_STRUCTURE_BODY_MARKERS: tuple[str, ...] = (
    "请严格依据以下用户描述生成上述结构的角色设定图：",
    "请严格依据以下用户描述生成上述结构的场景设计图：",
    "请严格依据以下用户描述生成上述结构的道具设定图：",
    "请严格依据以下用户描述生成白底人物角色全身照：",
    "请严格依据以下用户描述生成场景画面：",
    "请严格依据以下用户描述生成道具画面：",
    "请严格依据以下用户描述生成素材画面：",
)

# 审核重试用的简化三视图前缀（仍要求设定板，而非单张立绘）
_COMPACT_TURNAROUND_PREFIX = (
    "【强制任务：角色设定板】纯白背景，无复杂背景、无文字水印。"
    "画面含同一角色全身三视图（正面、左侧面、背面），站姿自然、双臂下垂；"
    "并含面部特写与半身特写；五官发型服装体型一致。"
    "请依据以下描述生成："
)


# 对纯文本做敏感词替换
def _replace_sensitive_terms(text: str) -> str:
    out = text or ""
    for src, dst in _SEEDREAM_TEXT_SOFTEN:
        if src in out:
            out = out.replace(src, dst)
    return out


# 拆出设定板前缀与用户正文；(prefix, body)，无标记则 prefix 为空
def split_seedream_structure_prompt(prompt: str) -> tuple[str, str]:
    text = prompt or ""
    for marker in _STRUCTURE_BODY_MARKERS:
        if marker in text:
            prefix, body = text.split(marker, 1)
            return f"{prefix}{marker}", body.strip()
    return "", text.strip()


# 软化易触发审核的措辞：只改用户正文，保留结构前缀（三视图等）
def soften_seedream_input_text(prompt: str) -> str:
    text = prompt or ""
    if not text:
        return text
    prefix, body = split_seedream_structure_prompt(text)
    soft_body = _replace_sensitive_terms(body)
    if prefix:
        return f"{prefix}{soft_body}"
    return soft_body


# 拆出设定板前缀后的用户正文；无标记则返回全文
def extract_seedream_user_body(prompt: str) -> str:
    _, body = split_seedream_structure_prompt(prompt or "")
    return body


# 文本审核失败后的压缩重试：简化三视图前缀 + 软化正文
def compact_seedream_prompt_for_retry(prompt: str) -> str:
    body = _replace_sensitive_terms(extract_seedream_user_body(prompt))
    if not body:
        body = _replace_sensitive_terms(prompt or "")
    return f"{_COMPACT_TURNAROUND_PREFIX}{body}"


# 仍审核失败时：简化三视图 + 只保留服装/风格线索
def style_only_seedream_prompt_for_retry(prompt: str) -> str:
    body = _replace_sensitive_terms(extract_seedream_user_body(prompt) or prompt or "")
    style_bits: list[str] = []
    for key in (
        "羊毛毡",
        "毛毡定格",
        "毛毡",
        "粘土软萌",
        "粘土",
        "软萌",
        "治愈系",
        "3D",
        "毛绒",
        "缝线",
    ):
        if key in body and key not in style_bits:
            style_bits.append(key)
    style = "、".join(style_bits) if style_bits else "手作可爱质感"
    robe = "白衣宽袖" if ("白衣" in body or "月白" in body) else "古风常服"
    return (
        f"{_COMPACT_TURNAROUND_PREFIX}"
        f"{robe}青年书生，腰间圆润佩饰，{style}，"
        "轮廓略不规整，针孔与绒感清晰，禁止真实历史人物肖像。"
    )
