"""Selectable TTS voice presets (豆包 openspeech + template aliases)."""

from __future__ import annotations

import hashlib
from typing import Any

# id used in API / project.voice_id; speaker is openspeech speaker id
VOICE_PRESETS: list[dict[str, Any]] = [
    {
        "id": "zh_female_cancan_uranus_bigtts",
        "label": "灿灿 · 女声旁白",
        "gender": "female",
        "speaker": "zh_female_cancan_uranus_bigtts",
    },
    {
        "id": "zh_female_tianmeixiaoyuan_uranus_bigtts",
        "label": "甜美女声 · 故事",
        "gender": "female",
        "speaker": "zh_female_tianmeixiaoyuan_uranus_bigtts",
    },
    {
        "id": "zh_female_shuangkuaisisi_uranus_bigtts",
        "label": "爽快女声 · 都市",
        "gender": "female",
        "speaker": "zh_female_shuangkuaisisi_uranus_bigtts",
    },
    {
        "id": "zh_female_vv_uranus_bigtts",
        "label": "Vivi · 国风女声",
        "gender": "female",
        "speaker": "zh_female_vv_uranus_bigtts",
    },
    {
        "id": "zh_female_xiaohe_uranus_bigtts",
        "label": "小何 · 通用女声",
        "gender": "female",
        "speaker": "zh_female_xiaohe_uranus_bigtts",
    },
    {
        "id": "zh_male_shaonianzixin_uranus_bigtts",
        "label": "少年梓辛 · 男声",
        "gender": "male",
        "speaker": "zh_male_shaonianzixin_uranus_bigtts",
    },
    {
        "id": "zh_male_m191_uranus_bigtts",
        "label": "云舟 · 稳重男声",
        "gender": "male",
        "speaker": "zh_male_m191_uranus_bigtts",
    },
    {
        "id": "zh_male_taocheng_uranus_bigtts",
        "label": "小天 · 年轻男声",
        "gender": "male",
        "speaker": "zh_male_taocheng_uranus_bigtts",
    },
    {
        "id": "zh_male_ruyayichen_uranus_bigtts",
        "label": "儒雅逸辰 · 男声",
        "gender": "male",
        "speaker": "zh_male_ruyayichen_uranus_bigtts",
    },
    {
        "id": "zh_male_baqiqingshu_uranus_bigtts",
        "label": "霸气青叔 · 男声",
        "gender": "male",
        "speaker": "zh_male_baqiqingshu_uranus_bigtts",
    },
]

# 漫剧角色音色：按关键词为不同角色匹配不同 speaker（避免全员同一声线）
DRAMA_SPEAKER_RULES: list[dict[str, Any]] = [
    {
        "speaker": "zh_male_baqiqingshu_uranus_bigtts",
        "gender": "male",
        "keywords": ("老", "翁", "族老", "长者", "首领", "青叔", "大叔", "沉稳", "威严", "苍", "应龙"),
    },
    {
        "speaker": "zh_male_m191_uranus_bigtts",
        "gender": "male",
        "keywords": ("领袖", "帝王", "君主", "大王", "治水", "禹", "庄重", "浑厚", "史诗", "统帅"),
    },
    {
        "speaker": "zh_male_ruyayichen_uranus_bigtts",
        "gender": "male",
        "keywords": ("儒雅", "书生", "谋士", "伯益", "文士", "智", "温和", "清朗", "参谋"),
    },
    {
        "speaker": "zh_male_shaonianzixin_uranus_bigtts",
        "gender": "male",
        "keywords": ("少年", "青年", "青壮", "小伙", "活力", "清亮", "少年音", "梓辛"),
    },
    {
        "speaker": "zh_male_taocheng_uranus_bigtts",
        "gender": "male",
        "keywords": ("年轻", "小哥", "明快", "阳光", "清爽"),
    },
    {
        "speaker": "zh_female_vv_uranus_bigtts",
        "gender": "female",
        "keywords": ("国风", "古风", "神话", "御姐", "女王", "仙", "神女"),
    },
    {
        "speaker": "zh_female_shuangkuaisisi_uranus_bigtts",
        "gender": "female",
        "keywords": ("爽快", "利落", "都市", "干练", "清脆"),
    },
    {
        "speaker": "zh_female_tianmeixiaoyuan_uranus_bigtts",
        "gender": "female",
        "keywords": ("温柔", "甜美", "柔和", "亲和", "少女", "姑娘"),
    },
    {
        "speaker": "zh_female_xiaohe_uranus_bigtts",
        "gender": "female",
        "keywords": ("通用", "百姓", "群众", "平民", "村妇", "妇人"),
    },
    {
        "speaker": "zh_female_cancan_uranus_bigtts",
        "gender": "female",
        "keywords": ("旁白", "解说", "叙述", "播报"),
    },
]

MALE_HINTS = ("男", "少年", "青年男", "老年男", "公子", "王爷", "少年音", "大叔", "青壮", "将", "伯", "公")
FEMALE_HINTS = ("女", "少女", "女声", "御姐", "小姐", "娘娘", "萝莉", "姑娘", "妇人", "村妇")

# Template audio_config.voice_preset aliases → speaker
VOICE_ALIASES: dict[str, str] = {
    "narrator_calm": "zh_female_cancan_uranus_bigtts",
    "warm_storyteller": "zh_female_tianmeixiaoyuan_uranus_bigtts",
    "teacher_clear": "zh_male_shaonianzixin_uranus_bigtts",
    "urban_editorial": "zh_female_shuangkuaisisi_uranus_bigtts",
    "retro_host": "zh_male_shaonianzixin_uranus_bigtts",
    "guqin_narrator": "zh_female_vv_uranus_bigtts",
}


def list_voices() -> list[dict[str, Any]]:
    return list(VOICE_PRESETS)


def resolve_speaker(voice_id: str | None, *, template_preset: str | None = None) -> str:
    """Map UI voice id / template alias to openspeech speaker."""
    raw = (voice_id or "").strip() or (template_preset or "").strip()
    if not raw:
        return "zh_female_cancan_uranus_bigtts"
    if raw in VOICE_ALIASES:
        return VOICE_ALIASES[raw]
    for preset in VOICE_PRESETS:
        if preset["id"] == raw or preset["speaker"] == raw:
            return str(preset["speaker"])
    # Pass-through custom speaker ids
    return raw


# 推断漫剧角色应使用的 TTS speaker（多声线 + 稳定哈希打散同分候选）
def infer_drama_speaker_from_prompt(
    voice_prompt: str,
    *,
    character_name: str = "",
    asset_id: int = 0,
) -> str:
    prompt = f"{character_name} {voice_prompt or ''}"
    male_score = sum(1 for k in MALE_HINTS if k in prompt)
    female_score = sum(1 for k in FEMALE_HINTS if k in prompt)
    if male_score > female_score:
        gender = "male"
    elif female_score > male_score:
        gender = "female"
    else:
        gender = "male" if asset_id % 2 else "female"

    scored: list[tuple[int, str]] = []
    for rule in DRAMA_SPEAKER_RULES:
        if rule["gender"] != gender:
            continue
        score = sum(1 for kw in rule["keywords"] if kw in prompt)
        if score > 0:
            scored.append((score, str(rule["speaker"])))

    if not scored:
        pool = [str(r["speaker"]) for r in DRAMA_SPEAKER_RULES if r["gender"] == gender]
        if not pool:
            return "zh_female_cancan_uranus_bigtts"
        digest = hashlib.md5(f"{asset_id}:{character_name}:{voice_prompt}".encode()).hexdigest()
        return pool[int(digest[:8], 16) % len(pool)]

    max_score = max(s for s, _ in scored)
    top = [speaker for s, speaker in scored if s == max_score]
    if len(top) == 1:
        return top[0]
    digest = hashlib.md5(f"{asset_id}:{character_name}".encode()).hexdigest()
    return top[int(digest[:8], 16) % len(top)]


# 兼容旧调用
def infer_speaker_from_voice_prompt(voice_prompt: str, *, character_name: str = "", asset_id: int = 0) -> str:
    return infer_drama_speaker_from_prompt(voice_prompt, character_name=character_name, asset_id=asset_id)


PREVIEW_TEXT = "大家好，这是当前音色的试听效果，适合科普短视频旁白讲解。"


async def ensure_voice_preview(voice_id: str) -> str:
    """Generate (or reuse cached) short TTS sample; return public URL."""
    import hashlib
    from pathlib import Path

    from app.services import storage
    from app.services.ark import get_ark

    speaker = resolve_speaker(voice_id)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in speaker)[:80]
    cache_dir = Path(__file__).resolve().parents[2] / "static" / "voice_previews"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{safe}.mp3"
    if dest.exists() and dest.stat().st_size > 2000:
        return storage.publish_local(dest)

    ark = get_ark()
    shot_no = int(hashlib.md5(speaker.encode()).hexdigest()[:4], 16) % 800 + 100
    url = await ark.tts(PREVIEW_TEXT, speaker, project_id=0, shot_no=shot_no)
    src = storage.local_path_from_url(url)
    if src and src.exists():
        dest.write_bytes(src.read_bytes())
        return storage.publish_local(dest)
    if dest.exists() and dest.stat().st_size > 2000:
        return storage.publish_local(dest)
    return url
