"""带 Skill 注入的 Agent LLM 调用。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.compose import compose_task_skills, with_skill_system
from app.services.drama.llm import drama_chat_json, drama_chat_text


async def run_task_json(
    db: AsyncSession | None,
    user_id: int | None,
    *,
    task: str,
    system: str,
    user: str,
    temperature: float = 0.6,
    max_tokens: int | None = None,
    skill_ids: list[int] | None = None,
) -> Any:
    """按任务注入启用 Skill 后调用 JSON LLM。"""
    skill_block = await compose_task_skills(db, user_id, task, skill_ids=skill_ids)
    kwargs: dict[str, Any] = {"temperature": temperature}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return await drama_chat_json(with_skill_system(system, skill_block), user, **kwargs)


async def run_task_text(
    db: AsyncSession | None,
    user_id: int | None,
    *,
    task: str,
    system: str,
    user: str,
    temperature: float = 0.6,
    max_tokens: int = 8192,
    skill_ids: list[int] | None = None,
) -> str:
    """按任务注入启用 Skill 后调用文本 LLM。"""
    skill_block = await compose_task_skills(db, user_id, task, skill_ids=skill_ids)
    return await drama_chat_text(
        with_skill_system(system, skill_block),
        user,
        temperature=temperature,
        max_tokens=max_tokens,
    )
