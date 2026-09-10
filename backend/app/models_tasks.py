"""Unified task platform ORM models shared by drama and kepu flows."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TaskRun(Base):
    """Cross-domain long-running task record."""

    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), index=True, default="drama")
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    client_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    batch_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    cancelable: Mapped[bool] = mapped_column(Boolean, default=True)
    current_step_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_step_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    drama_project_id: Mapped[int | None] = mapped_column(
        ForeignKey("drama_projects.id"), nullable=True, index=True
    )
    script_id: Mapped[int | None] = mapped_column(ForeignKey("drama_scripts.id"), nullable=True, index=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("drama_episodes.id"), nullable=True, index=True)
    fragment_id: Mapped[int | None] = mapped_column(
        ForeignKey("drama_episode_fragments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("drama_assets.id"), nullable=True, index=True)
    shot_id: Mapped[int | None] = mapped_column(ForeignKey("shots.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    billing_estimate_fen: Mapped[int] = mapped_column(Integer, default=0)
    billing_charged_fen: Mapped[int] = mapped_column(Integer, default=0)
    billing_refunded_fen: Mapped[int] = mapped_column(Integer, default=0)
    billing_status: Mapped[str] = mapped_column(String(16), default="none", index=True)

    targets: Mapped[list["TaskTarget"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskStep(Base):
    """One concrete execution step inside a task run."""

    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"), index=True)
    step_key: Mapped[str] = mapped_column(String(64), index=True)
    step_type: Mapped[str] = mapped_column(String(64), default="job")
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    input_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task: Mapped["TaskRun"] = relationship(back_populates="steps")


class TaskTarget(Base):
    """Target entity bindings for a task."""

    __tablename__ = "task_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["TaskRun"] = relationship(back_populates="targets")


class TaskEvent(Base):
    """Append-only task lifecycle event log."""

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped["TaskRun"] = relationship(back_populates="events")
