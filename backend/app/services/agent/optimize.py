"""按勾选 Skill 改写用户提示词，并保留 @asset 引用。"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.runner import run_task_text

# ASSET_TOKEN_RE 画布/分镜里的资产引用
ASSET_TOKEN_RE = re.compile(r"@asset:\d+")

VIDEO_OPTIMIZE_SYSTEM = """你是 Seedance 视频提示词导演。根据已启用的 Agent Skill，把用户提示词改写成更适合生成视频的中文画面描述。

硬性规则：
1. 只输出优化后的提示词正文，不要标题、解释、markdown 代码块、引号包裹。
2. 必须原样保留用户提示词里每一个 `@asset:数字` 引用，不得删除、改写、翻译或拆开。
3. 不要编造未出现的角色名或场景名；用 @asset 引用代替重复人名。
4. 保留用户原意（谁、在哪、做什么），按 Skill 补全第一帧、站位、视线、光位、镜头运动与物理接触。
5. 语言具体、可拍、简体中文。
"""

IMAGE_OPTIMIZE_SYSTEM = """你是画面提示词导演。根据已启用的 Agent Skill，把用户提示词改写成更适合生成静帧的中文画面描述。

硬性规则：
1. 只输出优化后的提示词正文，不要标题、解释、markdown 代码块、引号包裹。
2. 必须原样保留用户提示词里每一个 `@asset:数字` 引用，不得删除、改写、翻译或拆开。
3. 不要编造未出现的角色名或场景名；用 @asset 引用代替重复人名。
4. 保留用户原意，按 Skill 补全构图、光位、站位与视线。
5. 语言具体、可拍、简体中文。
"""


def extract_asset_tokens(prompt: str) -> list[str]:
    # 按出现顺序去重提取 @asset:id
    seen: set[str] = set()
    tokens: list[str] = []
    for match in ASSET_TOKEN_RE.finditer(prompt or ""):
        token = match.group(0)
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def strip_optimize_fences(text: str) -> str:
    # 去掉模型偶尔包上的代码块
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip().strip('"').strip("“”")


def restore_asset_tokens(original: str, rewritten: str) -> str:
    # 模型漏掉的 @asset 引用补回文末
    text = strip_optimize_fences(rewritten)
    missing = [token for token in extract_asset_tokens(original) if token not in text]
    if missing:
        text = f"{text.rstrip()} {' '.join(missing)}".strip()
    return text


def system_prompt_for_task(task: str) -> str:
    # 按任务选优化系统提示
    if task == "image_prompt":
        return IMAGE_OPTIMIZE_SYSTEM
    return VIDEO_OPTIMIZE_SYSTEM


async def optimize_prompt_with_skills(
    db: AsyncSession,
    user_id: int,
    *,
    prompt: str,
    skill_ids: list[int],
    task: str = "video_prompt",
) -> str:
    """用勾选 Skill 改写提示词；空 skill 时原样返回。"""
    source = (prompt or "").strip()
    if not source:
        return ""
    if not skill_ids:
        return source
    rewritten = await run_task_text(
        db,
        user_id,
        task=task,
        system=system_prompt_for_task(task),
        user=source,
        temperature=0.4,
        max_tokens=2048,
        skill_ids=skill_ids,
    )
    return restore_asset_tokens(source, rewritten)
