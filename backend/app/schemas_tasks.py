"""Pydantic schemas for the unified task platform."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas_common import PageMeta


class TaskTargetBind(BaseModel):
    """A target entity bound to one task."""

    target_type: str = Field(description="project | shot | drama_project | script | episode | fragment | asset")
    target_id: int = Field(ge=1)
    sort_order: int = 0
    metadata_json: dict[str, Any] | None = None


class TaskCreateRequest(BaseModel):
    """Create a platform task run."""

    domain: str = Field(default="drama", description="drama | kepu | tools | api | studio")
    task_type: str = Field(min_length=1, max_length=64)
    priority: int = Field(default=100, ge=0, le=1000)
    client_request_id: str | None = Field(default=None, max_length=128)
    dedupe_key: str | None = Field(default=None, max_length=128)
    batch_key: str | None = Field(default=None, max_length=128)
    provider_task_id: str | None = Field(default=None, max_length=128)
    cancelable: bool = True
    scheduled_at: datetime | None = None
    defer_activation: bool = Field(
        default=False,
        description="True 时 next_action_at 留空，等待同 batch 前置任务完成后激活",
    )
    payload: dict[str, Any] | None = None
    result_payload: dict[str, Any] | None = None
    project_id: int | None = Field(default=None, ge=1)
    drama_project_id: int | None = Field(default=None, ge=1)
    script_id: int | None = Field(default=None, ge=1)
    episode_id: int | None = Field(default=None, ge=1)
    fragment_id: int | None = Field(default=None, ge=1)
    asset_id: int | None = Field(default=None, ge=1)
    shot_id: int | None = Field(default=None, ge=1)
    targets: list[TaskTargetBind] = Field(default_factory=list)


class TaskUpdateRequest(BaseModel):
    """Update internal task lifecycle state."""

    status: str | None = Field(default=None, max_length=32)
    current_step_key: str | None = Field(default=None, max_length=64)
    current_step_status: str | None = Field(default=None, max_length=32)
    provider_task_id: str | None = Field(default=None, max_length=128)
    scheduled_at: datetime | None = None
    next_action_at: datetime | None = None
    lease_token: str | None = Field(default=None, max_length=64)
    lease_until: datetime | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = None
    payload: dict[str, Any] | None = None
    result_payload: dict[str, Any] | None = None


class TaskEventCreate(BaseModel):
    """Append a task event entry."""

    event_type: str = Field(min_length=1, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    phase: str | None = Field(default=None, max_length=64)
    message: str | None = None
    payload: dict[str, Any] | None = None


class TaskStepCreate(BaseModel):
    """Create a planned step for a task run."""

    step_key: str = Field(min_length=1, max_length=64)
    step_type: str = Field(default="job", max_length=64)
    provider_name: str | None = Field(default=None, max_length=64)
    input_payload: dict[str, Any] | None = None


class TaskStepOut(BaseModel):
    """Task step output model."""

    id: int
    step_key: str
    step_type: str
    status: str
    attempt_count: int = 0
    provider_name: str | None = None
    provider_task_id: str | None = None
    input_payload: dict | None = None
    output_payload: dict | None = None
    error_code: str | None = None
    error_message: str | None = None
    next_poll_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class TaskTargetOut(BaseModel):
    """Task target output model."""

    id: int
    target_type: str
    target_id: int
    sort_order: int
    metadata_json: dict | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TaskEventOut(BaseModel):
    """Task event output model."""

    id: int
    event_type: str
    status: str | None = None
    phase: str | None = None
    message: str | None = None
    payload: dict | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TaskRunBriefOut(BaseModel):
    """Compact task summary embedded in business responses."""

    id: int
    domain: str
    task_type: str
    status: str
    current_step_key: str | None = None
    current_step_status: str | None = None
    progress_percent: int = 0
    cancel_requested: bool = False
    provider_task_id: str | None = None
    error_message: str | None = None
    project_id: int | None = None
    drama_project_id: int | None = None
    episode_id: int | None = None
    fragment_id: int | None = None
    asset_id: int | None = None
    shot_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class TaskRunOut(BaseModel):
    """Unified task output model."""

    id: int
    domain: str
    task_type: str
    status: str
    priority: int
    requested_by: int
    client_request_id: str | None = None
    dedupe_key: str | None = None
    batch_key: str | None = None
    provider_task_id: str | None = None
    cancel_requested: bool = False
    cancelable: bool = True
    current_step_key: str | None = None
    current_step_status: str | None = None
    scheduled_at: datetime | None = None
    next_action_at: datetime | None = None
    lease_token: str | None = None
    lease_until: datetime | None = None
    progress_percent: int = 0
    error_code: str | None = None
    error_message: str | None = None
    payload: dict | None = None
    result_payload: dict | None = None
    project_id: int | None = None
    drama_project_id: int | None = None
    script_id: int | None = None
    episode_id: int | None = None
    fragment_id: int | None = None
    asset_id: int | None = None
    shot_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    billing_estimate_fen: int = 0
    billing_charged_fen: int = 0
    billing_refunded_fen: int = 0
    billing_status: str = "none"
    steps: list[TaskStepOut] = Field(default_factory=list)
    targets: list[TaskTargetOut] = Field(default_factory=list)
    events: list[TaskEventOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TaskListOut(BaseModel):
    """Paginated unified task list."""

    items: list[TaskRunOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class MockDelayTaskRequest(BaseModel):
    """Create one mock delayed task for runtime testing."""

    delay_seconds: int = Field(default=10, ge=1, le=600)
    succeed: bool = True
    result_payload: dict[str, Any] | None = None
    error_message: str | None = Field(default=None, max_length=500)
    dedupe_key: str | None = Field(default=None, max_length=128)


class AdminTaskRunOut(TaskRunOut):
    """Admin task view with requester email."""

    user_email: str | None = None
    usage_lines: list["AdminUsageEventBriefOut"] = Field(default_factory=list)


class AdminUsageEventBriefOut(BaseModel):
    """Compact usage line for task billing tab."""

    id: int
    billing_key: str
    capability: str | None = None
    model: str = ""
    total_tokens: int = 0
    charge_fen: int = 0
    cost_fen: int = 0
    estimated: bool = False
    billing_basis: str = "estimate"
    billing_basis_label: str = "估算"
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class AdminUsageEventOut(BaseModel):
    """Admin usage event list row."""

    id: int
    user_id: int
    user_email: str | None = None
    task_run_id: int | None = None
    project_id: int | None = None
    drama_project_id: int | None = None
    domain: str | None = None
    capability: str | None = None
    billing_key: str
    model: str = ""
    provider: str | None = None
    total_tokens: int = 0
    charge_fen: int = 0
    cost_fen: int = 0
    estimated: bool = False
    billing_basis: str = "estimate"
    billing_basis_label: str = "估算"
    created_at: datetime | None = None
    task_domain: str | None = None
    task_type: str | None = None
    task_status: str | None = None


class AdminUsageEventListOut(BaseModel):
    """Paginated admin usage events."""

    items: list[AdminUsageEventOut] = Field(default_factory=list)
    meta: PageMeta


class AdminTaskListOut(BaseModel):
    """Paginated admin task list."""

    items: list[AdminTaskRunOut] = Field(default_factory=list)
    meta: PageMeta


class AdminTaskDomainStatsOut(BaseModel):
    """Per-domain task counts for admin dashboard."""

    domain: str
    pending: int = 0
    active: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0


class AdminTaskStatsOut(BaseModel):
    """Task platform aggregate stats for admin monitoring."""

    pending_count: int = 0
    active_count: int = 0
    leased_count: int = 0
    running_count: int = 0
    awaiting_poll_count: int = 0
    cancel_requested_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    scheduler_running_jobs: int = 0
    max_concurrency: int = 0
    scheduler: str = "stopped"
    poller: str = "stopped"
    watchdog: str = "stopped"
    runtime_healthy: bool = False
    domains: list[AdminTaskDomainStatsOut] = Field(default_factory=list)
    fetched_at: datetime | None = None
