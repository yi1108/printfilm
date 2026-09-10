"""Force visual style + character consistency across storyboard shots."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Terms that cause 真人 / 动漫 / 3D drift across shots (for illustration templates)
_STYLE_DRIFT_ILLUS = re.compile(
    r"(写实照片|照片级真实|真人实拍|真实人脸|真人脸|摄影棚人像|电影真人剧照|"
    r"超写实皮肤|照片质感|live[\s-]?action|photoreal(?:istic)?|"
    r"赛璐璐二次元|日系动漫脸|动漫大眼睛|萌系二次元|3D超写实|CGI写实人像)",
    re.IGNORECASE,
)

# Terms that break photoreal / live-action templates
_STYLE_DRIFT_PHOTO = re.compile(
    r"(卡通简笔画|儿童绘本扁平|赛璐璐二次元|日系动漫脸|萌系二次元|"
    r"剪纸扁平|像素块|水墨写意|贴纸拼贴|Q版三头身)",
    re.IGNORECASE,
)

_EXTRA_NEGATIVE_ILLUS = (
    "写实照片，真人，真实人脸，摄影棚人像，电影真人剧照，照片级皮肤，"
    "风格混杂，镜头间画风跳变，另一套画风，赛璐璐二次元与写实混用"
)

_EXTRA_NEGATIVE_PHOTO = (
    "卡通，动漫，赛璐璐，二次元，扁平插画，剪纸，像素风，水墨写意，"
    "风格混杂，镜头间画风跳变，另一套画风，插画与写实混用"
)

_SCENE_TAG = re.compile(r"【场景】\s*(.+?)(?=\n【|\Z)", re.S)
_LOCK_LINE = re.compile(r"【(?:风格锁定|人物锁定|约束)】[^\n]*")
_PERSON_SETTING = re.compile(r"(?:人物设定|角色设定)[：:][^\n【]{0,400}")


def strip_style_drift(prompt: str, *, photoreal: bool = False) -> str:
    rx = _STYLE_DRIFT_PHOTO if photoreal else _STYLE_DRIFT_ILLUS
    out = rx.sub("", prompt or "")
    out = re.sub(r"[，,]{2,}", "，", out)
    return out.strip("，,。 \n\t")


def strip_lock_blocks(prompt: str) -> str:
    """Remove internal lock wrappers for UI / stored scene prompts."""
    raw = (prompt or "").strip()
    if not raw:
        return ""
    # New tagged format
    m = _SCENE_TAG.search(raw)
    if m:
        return m.group(1).strip("，,。 \n\t")
    # Drop tagged lock lines
    out = _LOCK_LINE.sub("", raw)
    out = _PERSON_SETTING.sub("", out)
    # Legacy: drop comma segments that start with lock tags / boilerplate
    if "【风格锁定】" in raw or "【人物锁定】" in raw:
        kept: list[str] = []
        for part in re.split(r"[，,\n]", raw):
            p = part.strip()
            if not p:
                continue
            if p.startswith(("【风格锁定】", "【人物锁定】", "【约束】", "人物设定", "角色设定")):
                continue
            if p.startswith(("同一画风", "全片必须保持", "凡出现人物", "禁止写实", "禁止换脸", "画面干净无文字")):
                continue
            # Drop mid-lock fragments
            if "禁止镜头间切换" in p or "必须严格沿用以上外形" in p:
                continue
            kept.append(p)
        out = "，".join(kept)
    out = re.sub(r"[，,]{2,}", "，", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip("，,。；; \n\t")


def build_locked_image_prompt(
    style_prefix: str,
    img_prompt: str,
    character_bible: str = "",
    *,
    photoreal: bool = False,
    lock_character: bool = True,
    lock_style: bool = True,
) -> str:
    """Prompt for Seedream. lock_* can be relaxed for diverse / showcase templates."""
    body = strip_lock_blocks(strip_style_drift(img_prompt, photoreal=photoreal))
    if style_prefix and style_prefix in body:
        body = body.replace(style_prefix, "", 1).strip("，, ")
    parts: list[str] = []
    if lock_style and style_prefix:
        if photoreal:
            parts.append(
                f"【风格锁定】{style_prefix}。全片统一此画风，禁止卡通动漫与风格跳变"
            )
        elif lock_character:
            parts.append(
                f"【风格锁定】{style_prefix}。全片统一此画风，禁止写实摄影与风格跳变"
            )
        else:
            parts.append(
                f"【风格提示】{style_prefix}。"
                "配色与界面类型优先服从【场景】描述；禁止无脑套用霓虹蓝赛博大屏"
            )
    if lock_character and (character_bible or "").strip():
        parts.append(
            f"【人物锁定】{(character_bible or '').strip()}。凡出现人物必须严格沿用以上外形，禁止换脸换装"
        )
    if body:
        parts.append(f"【场景】{body}")
    if lock_character:
        parts.append("【约束】同一画风同一人物，画面干净无文字")
    else:
        parts.append("【约束】本镜场景必须独特、与其他镜头构图明显不同，画面干净无文字")
    return "\n".join(parts)


def merge_negative(
    template_negative: str,
    *,
    image_text: bool = False,
    photoreal: bool = False,
) -> str:
    base = (template_negative or "").strip("，, ")
    extra = _EXTRA_NEGATIVE_PHOTO if photoreal else _EXTRA_NEGATIVE_ILLUS
    parts = [p for p in (base, extra) if p]
    merged = "，".join(parts)
    if image_text and "文字" not in merged:
        merged = f"{merged}，画面文字，字幕，水印，标题字"
    return merged


def template_consistency_mode(tpl) -> str:
    """Return character | style | diverse.

    - character: cast lock + shot-to-shot image ref chaining (叙事默认)
    - style: keep style only, no cast lock, no ref chaining
    - diverse: content-driven independent scenes (开源/产品演示)
    """
    if tpl is None:
        return "character"
    cfg = getattr(tpl, "seedream_config", None) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    mode = str(cfg.get("consistency_mode") or "").strip().lower()
    if mode in {"character", "style", "diverse", "none"}:
        return "diverse" if mode == "none" else mode
    for conf in (cfg, getattr(tpl, "seedance_config", None) or {}):
        if isinstance(conf, dict) and "character_consistency" in conf:
            return "character" if conf.get("character_consistency") else "diverse"
    return "character"


def template_is_photoreal(tpl) -> bool:
    """True when template opts into live-action / photoreal style."""
    if tpl is None:
        return False
    cfg = getattr(tpl, "seedream_config", None) or {}
    if isinstance(cfg, dict) and cfg.get("photoreal"):
        return True
    cats = getattr(tpl, "category", None) or []
    return any(c in {"真人感", "写实感"} for c in cats)


def template_prompt_defaults(tpl) -> dict[str, str]:
    """Canonical style / character / extra prompts from a template.

    style ← style_prefix；角色/额外 ← seedream_config。
    """
    if tpl is None:
        return {"style_prompt": "", "character_prompt": "", "extra_prompt": ""}
    cfg = getattr(tpl, "seedream_config", None) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "style_prompt": (getattr(tpl, "style_prefix", None) or "").strip(),
        "character_prompt": str(cfg.get("character_prompt") or "").strip(),
        "extra_prompt": str(cfg.get("extra_prompt") or "").strip(),
    }


def seedream_ref_urls(*candidates: str | None) -> list[str]:
    """Normalize refs for Seedream — **public https only**.

    Skip data: URIs (multi‑MB base64 often hangs Seedream) and LAN/localhost URLs
    (Ark cloud cannot fetch them). Prefer prior shot `image_ark_url` CDN links.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        if not raw:
            continue
        u = raw.strip()
        if not u or u in seen:
            continue
        if not (u.startswith("https://") or u.startswith("http://")):
            continue
        host = (urlparse(u).hostname or "").lower()
        if not host or host in {"localhost", "127.0.0.1", "::1"}:
            continue
        if host.startswith("192.168.") or host.startswith("10."):
            continue
        if re.match(r"^172\.(1[6-9]|2\d|3[0-1])\.", host):
            continue
        out.append(u)
        seen.add(u)
    return out[:2]
