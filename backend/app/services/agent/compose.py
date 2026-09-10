"""把启用的 Skill 拼进 LLM 系统提示。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models_agent import AgentSkill
from app.services.agent.store import list_injectable_skills, list_skills_by_ids

# MAX_SKILL_INJECT_CHARS 单次注入上限，避免撑爆上下文
MAX_SKILL_INJECT_CHARS = 14000
SKILL_HEADER = "\n\n## 已启用 Agent Skill（必须遵守，不要复述本段标题）\n"


def skill_matches_task(skill: AgentSkill, task: str) -> bool:
    # 任务标签匹配：all 或精确任务名
    tasks = skill.tasks if isinstance(skill.tasks, list) else []
    labels = {str(item).strip() for item in tasks if str(item).strip()}
    if not labels or "all" in labels:
        return True
    return task in labels


def render_skill_block(skills: list[AgentSkill], *, max_chars: int = MAX_SKILL_INJECT_CHARS) -> str:
    # 按内置优先、再按名称拼接；超出上限截断靠后的 skill
    if not skills:
        return ""
    chunks: list[str] = [SKILL_HEADER]
    used = len(SKILL_HEADER)
    for skill in skills:
        title = (skill.name or skill.slug or "未命名").strip()
        body = (skill.body or "").strip()
        piece = f"\n### {title}\n\n{body}\n"
        if used + len(piece) > max_chars:
            remain = max_chars - used - 24
            if remain < 200:
                break
            piece = f"\n### {title}\n\n{body[:remain].rstrip()}\n…（后续已截断）\n"
        chunks.append(piece)
        used += len(piece)
    return "".join(chunks) if len(chunks) > 1 else ""


def parse_skill_ids(raw: Any) -> list[int] | None:
    # None 表示未指定（用全部启用）；[] 表示本次不注入
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    out: list[int] = []
    seen: set[int] = set()
    for item in raw:
        try:
            skill_id = int(item)
        except (TypeError, ValueError):
            continue
        if skill_id <= 0 or skill_id in seen:
            continue
        seen.add(skill_id)
        out.append(skill_id)
    return out


async def compose_task_skills(
    db: AsyncSession | None,
    user_id: int | None,
    task: str,
    skill_ids: list[int] | None = None,
) -> str:
    """加载 skill 拼成系统提示附录。

    skill_ids 为 None：全部启用且匹配任务；为 []：不注入；为 id 列表：按勾选注入。
    """
    if db is None:
        return ""
    if skill_ids is not None:
        rows = await list_skills_by_ids(db, user_id, skill_ids)
        return render_skill_block(rows)
    rows = await list_injectable_skills(db, user_id)
    matched = [row for row in rows if skill_matches_task(row, task)]
    return render_skill_block(matched)


def with_skill_system(base_system: str, skill_block: str) -> str:
    # 基础系统提示 + skill 附录
    extra = (skill_block or "").strip()
    if not extra:
        return base_system
    return f"{base_system.rstrip()}\n{extra}"


def skill_to_public_dict(skill: AgentSkill) -> dict[str, Any]:
    # API 列表/详情字段
    return {
        "id": skill.id,
        "slug": skill.slug,
        "name": skill.name,
        "description": skill.description or "",
        "tasks": list(skill.tasks or []),
        "is_builtin": bool(skill.is_builtin),
        "is_active": bool(skill.is_active),
        "user_id": skill.user_id,
        "body": skill.body or "",
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }
