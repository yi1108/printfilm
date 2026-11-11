"""分镜语言只由原始素材决定；在后处理前校验所有自然语言字段。"""

import re
from typing import Any

from app.services.content_expansion import topic_language


def storyboard_language_rule(source_text: str) -> str:
    """模板仅提供视觉风格，不能覆盖原始素材的输出语言。"""
    language = "English" if topic_language(source_text) == "en" else "Simplified Chinese"
    return (
        f"\nMANDATORY OUTPUT LANGUAGE: {language}, determined ONLY by original source_text. "
        "This rule overrides ALL language instructions in templates, style hints and system addons. "
        "Every natural-language value (title, subtitle, text, character_bible, bgm_lock, "
        "img_prompt, video_prompt, camera, bgm, and every segments[].text) must use this language. "
        "Keep JSON keys and kind enum values unchanged. Translate visual hints into the required language. "
        "English titles use complete words (typically 2-8 words), never Chinese character limits. "
        "English narration timing uses about 2.5 words/second; Chinese uses about 5 characters/second.\n"
    )


def validate_storyboard_language(data: Any, source_text: str) -> None:
    """拒绝错语言而非悄悄以中文回退；允许中文内容中的英文专有名词。"""
    language = topic_language(source_text)

    def check(value: Any, path: str) -> None:
        """逐字段检查，避免英文标题掩盖中文旁白或画面。"""
        if not isinstance(value, str) or not value.strip():
            return
        # 中文协议 cue 不是内容，兼容历史 video_prompt/segments 格式。
        body = re.sub(r"【(?:旁白|对白|画面|空镜)[·：:][^】]*】|@duration:\d+", "", value)
        han = len(re.findall(r"[\u3400-\u9fff]", body))
        words = re.findall(r"[A-Za-z]+", body)
        if (language == "en" and han) or (language == "zh" and not han and words):
            raise RuntimeError(f"分镜输出语言与原始素材不一致（{path}），请重试")

    def shot(item: Any, path: str) -> None:
        """覆盖新旧字段别名和所有段落。"""
        if not isinstance(item, dict):
            return
        for key in ("title", "overlay_title", "subtitle", "overlay_subtitle", "text", "audio_text",
                    "img_prompt", "visual", "video_prompt", "camera", "bgm", "bgm_mood"):
            check(item.get(key), f"{path}.{key}")
        for index, segment in enumerate(item.get("segments") or []):
            if isinstance(segment, dict):
                check(segment.get("text") or segment.get("content"), f"{path}.segments[{index}]")

    items = data
    if isinstance(data, dict):
        for key in ("character_bible", "characters", "cast", "bgm_lock", "bgm"):
            check(data.get(key), key)
        items = data.get("shots") or data.get("storyboard") or data.get("scenes") or []
    if isinstance(items, list):
        for index, item in enumerate(items):
            shot(item, f"shots[{index}]")
