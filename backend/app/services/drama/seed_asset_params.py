"""从剧本抽取资产时组装 params（对齐 manju seedAssetsFromScript）。"""

from __future__ import annotations

from typing import Any

# DEFAULT_APPEARANCE_NAME 从剧本抽取角色时的默认形象名
DEFAULT_APPEARANCE_NAME = "基础形象"

# DEFAULT_IMAGE_GENERATION 默认生图参数（与前端 Seedream 默认对齐）
DEFAULT_IMAGE_GENERATION = {
    "modelId": "seedream-5.0",
    "aspectRatio": "3:4",
    "resolution": "3K",
}


# 组装道具/素材等命名图片资产 params（对齐 manju buildNamedImageParams）
def build_named_image_params(prompt: str, aspect_ratio: str, *, kind: str = "prop") -> dict[str, Any]:
    text = (prompt or "").strip()
    return {
        "visualPrompt": text,
        "visualImage": text,
        "kind": kind,
        "canvas": {
            "generation": {
                "prompt": text,
                "modelId": DEFAULT_IMAGE_GENERATION["modelId"],
                "aspectRatio": aspect_ratio,
                "resolution": DEFAULT_IMAGE_GENERATION["resolution"],
            },
            "seededFromScript": True,
        },
    }


# 按 manju buildCharacterParams 规则拼接角色生图 prompt
def manju_join_character_prompt(character: dict[str, Any]) -> str:
    visual = str(character.get("visualImage") or "").strip()
    title = str(character.get("title") or "").strip()
    role_type = str(character.get("roleType") or "").strip()
    core_tags = str(character.get("coreTags") or "").strip()
    personality = str(character.get("personality") or "").strip()
    parts = [
        visual,
        f"身份：{title}" if title else "",
        f"定位：{role_type}" if role_type else "",
        f"标签：{core_tags}" if core_tags else "",
        f"性格：{personality}" if personality else "",
    ]
    return "。".join(part for part in parts if part)


# 从摘要人物 dict 拼角色生图提示词正文（refresh/fallback 时可叙事化扩展）
def compose_character_visual_text(character: dict[str, Any]) -> str:
    visual = str(character.get("visualImage") or character.get("visualPrompt") or "").strip()
    if len(visual) >= 120:
        return manju_join_character_prompt(character) if manju_join_character_prompt(character) != visual else visual

    segments: list[str] = []
    joined = manju_join_character_prompt(character)
    if joined:
        segments.append(joined)
    identity = str(character.get("identityBackground") or "").strip()
    growth = str(character.get("growthExperience") or "").strip()
    relationships = str(character.get("relationships") or "").strip()
    if identity and identity not in joined:
        segments.append(identity)
    if growth and growth not in joined:
        segments.append(growth)
    if relationships and relationships not in joined:
        segments.append(relationships)
    return "。".join(s for s in segments if s)


# 组装角色资产 params（形象名 + 生图提示词，对齐 manju buildCharacterParams）
def build_character_params(character: dict[str, Any]) -> dict[str, Any]:
    prompt = manju_join_character_prompt(character)
    visual = str(character.get("visualImage") or "").strip() or prompt
    return {
        "visualImage": visual,
        "visualPrompt": prompt,
        "roleType": character.get("roleType"),
        "title": character.get("title"),
        "coreTags": character.get("coreTags"),
        "identityBackground": character.get("identityBackground"),
        "growthExperience": character.get("growthExperience"),
        "personality": character.get("personality"),
        "relationships": character.get("relationships"),
        "growthArc": character.get("growthArc"),
        "canvas": {
            "appearanceName": DEFAULT_APPEARANCE_NAME,
            "generation": {
                "prompt": prompt,
                **DEFAULT_IMAGE_GENERATION,
            },
            "seededFromScript": True,
        },
    }


# 组装场景资产 params（对齐 manju buildSceneParams）
def build_scene_params(scene_name: str, story_type: str = "") -> dict[str, Any]:
    _ = story_type  # manju 场景 seed 未使用 storyType，保留参数供 refresh 扩展
    prompt = f"场景：{scene_name.strip()}，影视级写实场景，构图清晰，适合短剧拍摄"
    return build_named_image_params(prompt, "16:9", kind="scene")
