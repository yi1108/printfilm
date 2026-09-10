"""Agent Skill 存储：内置导演手册 + 用户上传的 markdown skill。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentSkill(Base):
    """一条可注入 LLM 的 Agent Skill（规划镜头、生视频提示词等）。"""

    __tablename__ = "agent_skills"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_agent_skill_user_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # slug 短名，如 cinedance-seedance
    slug: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(1024), default="")
    # body 完整 markdown 正文（不含 YAML 头）
    body: Mapped[str] = mapped_column(Text, default="")
    # tasks 适用任务：shot_plan / video_prompt / all
    tasks: Mapped[list] = mapped_column(JSON, default=list)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # user_id 为空表示系统内置；用户上传则绑定所有者
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
