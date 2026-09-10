"""Agent Skill API 入出参。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentSkillOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str = ""
    tasks: list[str] = Field(default_factory=list)
    is_builtin: bool = False
    is_active: bool = True
    user_id: int | None = None
    body: str = ""
    created_at: str | None = None
    updated_at: str | None = None


class AgentSkillListOut(BaseModel):
    items: list[AgentSkillOut]


class AgentSkillUploadBody(BaseModel):
    """上传 Skill：完整 markdown（可含 YAML 头）。"""

    markdown: str = Field(min_length=8, max_length=80000)


class AgentSkillUpdateBody(BaseModel):
    markdown: str | None = Field(default=None, max_length=80000)
    is_active: bool | None = None


class AgentSkillOptimizeBody(BaseModel):
    """按勾选 Skill 优化提示词。"""

    prompt: str = Field(min_length=1, max_length=8000)
    skill_ids: list[int] = Field(default_factory=list)
    task: str = Field(default="video_prompt", max_length=64)


class AgentSkillOptimizeOut(BaseModel):
    prompt: str
    task_id: int | None = None
