"""Agent Skill 仓库：种子内置手册、列出可注入项、用户上传。"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_agent import AgentSkill
from app.services.agent.parse import SkillParseError, parse_skill_markdown

logger = logging.getLogger(__name__)

# BUILTIN_SKILLS_DIR 内置 SKILL.md 目录
BUILTIN_SKILLS_DIR = Path(__file__).resolve().parents[2] / "data" / "agent_skills"
# MAX_UPLOAD_CHARS 用户上传正文上限
MAX_UPLOAD_CHARS = 80000
# MAX_USER_SKILLS 每用户自定义 skill 上限
MAX_USER_SKILLS = 20


def builtin_skill_files(root: Path | None = None) -> list[Path]:
    # 扫描内置目录下各 skill 的 SKILL.md
    base = root or BUILTIN_SKILLS_DIR
    if not base.exists():
        return []
    return sorted(base.glob("*/SKILL.md"))


async def seed_builtin_skills(db: AsyncSession, root: Path | None = None) -> int:
    """把内置 SKILL.md 同步进数据库（按 slug upsert，不覆盖用户改过的启用开关）。"""
    upserted = 0
    for path in builtin_skill_files(root):
        try:
            parsed = parse_skill_markdown(path.read_text(encoding="utf-8"))
        except (OSError, SkillParseError) as exc:
            logger.warning("跳过损坏的内置 skill path=%s err=%s", path, exc)
            continue
        slug = parsed["slug"]
        result = await db.execute(
            select(AgentSkill).where(AgentSkill.is_builtin.is_(True), AgentSkill.slug == slug)
        )
        row = result.scalar_one_or_none()
        if row is None:
            db.add(
                AgentSkill(
                    slug=slug,
                    name=parsed["name"],
                    description=parsed["description"],
                    body=parsed["body"],
                    tasks=parsed["tasks"],
                    is_builtin=True,
                    is_active=True,
                    user_id=None,
                )
            )
            upserted += 1
            continue
        row.name = parsed["name"]
        row.description = parsed["description"]
        row.body = parsed["body"]
        row.tasks = parsed["tasks"]
        upserted += 1
    if upserted:
        await db.commit()
        logger.info("已同步内置 Agent Skill count=%s", upserted)
    return upserted


async def list_injectable_skills(db: AsyncSession, user_id: int | None) -> list[AgentSkill]:
    # 启用中的内置 + 当前用户自己的 skill
    clauses = [AgentSkill.is_builtin.is_(True)]
    if user_id is not None:
        clauses.append(AgentSkill.user_id == int(user_id))
    result = await db.execute(
        select(AgentSkill).where(or_(*clauses), AgentSkill.is_active.is_(True)).order_by(
            AgentSkill.is_builtin.desc(),
            AgentSkill.id.asc(),
        )
    )
    return list(result.scalars().all())


async def list_visible_skills(db: AsyncSession, user_id: int) -> list[AgentSkill]:
    # 设置页：内置全部 + 自己上传的（含停用）
    result = await db.execute(
        select(AgentSkill)
        .where(or_(AgentSkill.is_builtin.is_(True), AgentSkill.user_id == int(user_id)))
        .order_by(AgentSkill.is_builtin.desc(), AgentSkill.id.asc())
    )
    return list(result.scalars().all())


async def list_skills_by_ids(
    db: AsyncSession,
    user_id: int | None,
    skill_ids: list[int],
) -> list[AgentSkill]:
    # 按用户勾选的 id 取可见 skill（显式选择时不要求 is_active）
    wanted: list[int] = []
    seen: set[int] = set()
    for item in skill_ids:
        try:
            skill_id = int(item)
        except (TypeError, ValueError):
            continue
        if skill_id <= 0 or skill_id in seen:
            continue
        seen.add(skill_id)
        wanted.append(skill_id)
    if not wanted:
        return []
    clauses = [AgentSkill.is_builtin.is_(True)]
    if user_id is not None:
        clauses.append(AgentSkill.user_id == int(user_id))
    result = await db.execute(
        select(AgentSkill)
        .where(or_(*clauses), AgentSkill.id.in_(wanted))
        .order_by(AgentSkill.is_builtin.desc(), AgentSkill.id.asc())
    )
    return list(result.scalars().all())


async def get_visible_skill(db: AsyncSession, user_id: int, skill_id: int) -> AgentSkill | None:
    # 仅能看内置或自己的
    result = await db.execute(select(AgentSkill).where(AgentSkill.id == int(skill_id)))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.is_builtin or row.user_id == int(user_id):
        return row
    return None


async def count_user_skills(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(AgentSkill).where(AgentSkill.user_id == int(user_id), AgentSkill.is_builtin.is_(False))
    )
    return len(list(result.scalars().all()))


async def create_user_skill(db: AsyncSession, user_id: int, markdown: str) -> AgentSkill:
    """用户上传 markdown skill。"""
    text = (markdown or "").strip()
    if len(text) > MAX_UPLOAD_CHARS:
        raise SkillParseError(f"Skill 不能超过 {MAX_UPLOAD_CHARS} 字")
    parsed = parse_skill_markdown(text)
    if await count_user_skills(db, user_id) >= MAX_USER_SKILLS:
        raise SkillParseError(f"最多上传 {MAX_USER_SKILLS} 条自定义 Skill")
    existing = await db.execute(
        select(AgentSkill).where(AgentSkill.user_id == int(user_id), AgentSkill.slug == parsed["slug"])
    )
    if existing.scalar_one_or_none() is not None:
        raise SkillParseError("已有同名 Skill，请换 name 或先删除旧的")
    row = AgentSkill(
        slug=parsed["slug"],
        name=parsed["name"],
        description=parsed["description"],
        body=parsed["body"],
        tasks=parsed["tasks"],
        is_builtin=False,
        is_active=True,
        user_id=int(user_id),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_user_skill(
    db: AsyncSession,
    row: AgentSkill,
    *,
    markdown: str | None = None,
    is_active: bool | None = None,
) -> AgentSkill:
    # 内置只允许改启用开关；用户 skill 可改正文
    if is_active is not None:
        row.is_active = bool(is_active)
    if markdown is not None:
        if row.is_builtin:
            raise SkillParseError("系统内置 Skill 不能改正文")
        parsed = parse_skill_markdown(markdown)
        if len(parsed["body"]) > MAX_UPLOAD_CHARS:
            raise SkillParseError(f"Skill 不能超过 {MAX_UPLOAD_CHARS} 字")
        row.slug = parsed["slug"]
        row.name = parsed["name"]
        row.description = parsed["description"]
        row.body = parsed["body"]
        row.tasks = parsed["tasks"]
    await db.commit()
    await db.refresh(row)
    return row


async def delete_user_skill(db: AsyncSession, row: AgentSkill) -> None:
    if row.is_builtin:
        raise SkillParseError("系统内置 Skill 不能删除")
    await db.delete(row)
    await db.commit()
