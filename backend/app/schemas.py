from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas_common import PageMeta
from app.schemas_tasks import TaskRunBriefOut


# ---- Auth ----
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=64)
    nickname: str = Field(default="创作者", max_length=64)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: EmailStr
    nickname: str
    quota_left: int
    balance_fen: int = 0
    frozen_fen: int = 0
    plan: str = "free"
    role: str = "user"
    avatar_url: str = ""
    phone: str = ""

    model_config = {"from_attributes": True}

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, value: Any) -> str:
        return str(value or "")


class ProfileUpdateRequest(BaseModel):
    nickname: str = Field(max_length=64)
    email: str = Field(max_length=255)
    phone: str = Field(default="", max_length=32)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=6, max_length=64)


# ---- Templates ----
class TemplateOut(BaseModel):
    id: str
    name: str
    description: str
    category: list[str]
    preview_cover: str
    default_ratio: str
    shot_duration_min: int
    shot_duration_max: int
    is_premium: bool
    sort_order: int

    model_config = {"from_attributes": True}


class TemplateDetailOut(TemplateOut):
    style_prefix: str
    negative_prompt: str
    llm_system_addon: str
    seedream_config: dict
    seedance_config: dict
    audio_config: dict
    subtitle_config: dict


# ---- Shots / Projects ----
class ShotOut(BaseModel):
    id: int
    shot_no: int
    duration: float
    narration: str
    overlay_title: str = ""
    overlay_subtitle: str = ""
    img_prompt: str
    video_prompt: str
    segment_script: str = ""
    camera: str
    bgm_mood: str
    image_url: str | None
    video_url: str | None
    audio_url: str | None
    status: str
    version: int

    model_config = {"from_attributes": True}


class ShotUpdate(BaseModel):
    narration: str | None = None
    overlay_title: str | None = None
    overlay_subtitle: str | None = None
    img_prompt: str | None = None
    video_prompt: str | None = None
    segment_script: str | None = None
    duration: float | None = Field(default=None, ge=1, le=30)
    camera: str | None = None
    bgm_mood: str | None = None


class ProjectCreate(BaseModel):
    template_id: str
    title: str = "未命名作品"
    source_type: str = Field(default="theme", pattern="^(theme|script)$")
    source_text: str = Field(min_length=2, max_length=20000)
    resolution_mode: str = Field(default="preview", pattern="^(preview|hd)$")
    pipeline_mode: str = Field(default="full", pattern="^(full|image_text)$")
    output_ratio: str | None = Field(
        default=None,
        pattern=r"^(16:9|9:16|1:1|4:3|21:9)?$",
        max_length=16,
    )
    voice_id: str | None = Field(default=None, max_length=128)
    style_prompt: str | None = Field(default=None, max_length=2000)
    character_prompt: str | None = Field(default=None, max_length=2000)
    extra_prompt: str | None = Field(default=None, max_length=2000)
    ref_image_url: str | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    source_type: str | None = Field(default=None, pattern="^(theme|script)$")
    source_text: str | None = Field(default=None, min_length=2, max_length=20000)
    template_id: str | None = None
    pipeline_mode: str | None = Field(default=None, pattern="^(full|image_text)$")
    output_ratio: str | None = Field(
        default=None,
        pattern=r"^(16:9|9:16|1:1|4:3|21:9)$",
        max_length=16,
    )
    resolution_mode: str | None = Field(default=None, pattern="^(preview|hd)$")
    voice_id: str | None = Field(default=None, max_length=128)
    style_prompt: str | None = Field(default=None, max_length=2000)
    character_prompt: str | None = Field(default=None, max_length=2000)
    extra_prompt: str | None = Field(default=None, max_length=2000)
    ref_image_url: str | None = None
    cover_url: str | None = Field(default=None, max_length=1024)


class ProjectOut(BaseModel):
    id: int
    template_id: str
    title: str
    source_type: str
    source_text: str
    status: str
    progress: int
    error_msg: str | None
    cover_url: str | None
    final_video_url: str | None
    resolution_mode: str
    pipeline_mode: str = "full"
    output_ratio: str = ""
    voice_id: str = ""
    character_bible: str = ""
    bgm_lock: str = ""
    style_prompt: str = ""
    character_prompt: str = ""
    extra_prompt: str = ""
    ref_image_url: str | None
    created_at: datetime
    updated_at: datetime
    shots: list[ShotOut] = []
    active_tasks: list[TaskRunBriefOut] = []

    model_config = {"from_attributes": True}


class ProjectListItem(BaseModel):
    id: int
    title: str
    template_id: str
    status: str
    progress: int
    cover_url: str | None
    final_video_url: str | None = None
    error_msg: str | None = None
    pipeline_mode: str = "full"
    output_ratio: str = ""
    published: bool = False
    created_at: datetime
    updated_at: datetime | None = None
    active_tasks: list[TaskRunBriefOut] = []

    model_config = {"from_attributes": True}


class ProjectDownloadRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, min_length=1, max_length=50)


class ContentExpandRequest(BaseModel):
    topic: str = Field(default="", max_length=2000)
    mode: str = Field(default="theme", pattern="^(theme|script)$")


class ContentExpandOut(BaseModel):
    title: str
    content: str
    task_id: int | None = None


class VoicePreviewRequest(BaseModel):
    voice_id: str = Field(min_length=1, max_length=128)


class VoicePreviewOut(BaseModel):
    url: str
    voice_id: str


class WorkOut(BaseModel):
    id: int
    project_id: int
    user_id: int
    title: str
    cover_url: str | None
    video_url: str
    visibility: str
    published_at: datetime

    model_config = {"from_attributes": True}


class ProgressEvent(BaseModel):
    event: str
    stage: str | None = None
    shot: int | None = None
    total: int | None = None
    percent: int | None = None
    message: str | None = None
    video_url: str | None = None
    retryable: bool | None = None
    code: str | None = None


# ---- Admin ----
class ProjectListStats(BaseModel):
    total: int = 0
    generating: int = 0
    done: int = 0
    published: int = 0


class ProjectListOut(BaseModel):
    items: list[ProjectListItem]
    meta: PageMeta
    stats: ProjectListStats


class AdminUsageBucketOut(BaseModel):
    """按 capability / domain 聚合桶。"""

    key: str
    calls: int = 0
    charge_fen: int = 0
    cost_fen: int = 0


class AdminDailyUsageOut(BaseModel):
    date: str
    calls: int = 0
    charge_fen: int = 0
    cost_fen: int = 0


class AdminTopUserOut(BaseModel):
    user_id: int
    email: str | None = None
    calls: int = 0
    charge_fen: int = 0
    cost_fen: int = 0


class AdminUpstreamUsageDayOut(BaseModel):
    """官方与本地上游成本对照（单日）。"""

    date: str
    local_cost_fen: int = 0
    local_tokens: int = 0
    official_tokens: int = 0
    official_cost_fen: int = 0
    delta_fen: int = 0
    delta_pct: float | None = None


class AdminUpstreamUsageOut(BaseModel):
    configured: bool = False
    days: int = 30
    last_sync_at: str | None = None
    series: list[AdminUpstreamUsageDayOut] = Field(default_factory=list)


class AdminUpstreamUsageSyncOut(BaseModel):
    configured: bool = False
    synced: int = 0
    skipped: int = 0
    last_sync_at: str | None = None


class AdminFinanceDailyRowOut(BaseModel):
    """单日财务对照行。"""

    date: str
    charge_fen: int = 0
    cost_fen: int = 0
    tokens: int = 0
    actual_cost_fen: int = 0
    profit_fen: int = 0
    profit_pct: float | None = None


class AdminFinanceDailyTotalsOut(BaseModel):
    charge_fen: int = 0
    cost_fen: int = 0
    tokens: int = 0
    actual_cost_fen: int = 0
    profit_fen: int = 0
    profit_pct: float | None = None


class AdminFinanceDailyOut(BaseModel):
    configured: bool = False
    days: int = 30
    last_sync_at: str | None = None
    totals: AdminFinanceDailyTotalsOut = Field(default_factory=AdminFinanceDailyTotalsOut)
    series: list[AdminFinanceDailyRowOut] = Field(default_factory=list)


class AdminProjectUsageOut(BaseModel):
    """项目级用量摘要。"""

    charge_fen: int = 0
    cost_fen: int = 0
    tokens: int = 0
    calls: int = 0
    image_gens: int = 0
    video_gens: int = 0
    llm_calls: int = 0
    tts_gens: int = 0


class AdminTaskBriefOut(BaseModel):
    """关联任务简要行。"""

    id: int
    domain: str
    task_type: str
    status: str
    progress_percent: int = 0
    billing_charged_fen: int = 0
    billing_estimate_fen: int = 0
    error_message: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class AdminShotBriefOut(BaseModel):
    id: int
    shot_no: int
    status: str
    has_image: bool = False
    has_video: bool = False
    has_audio: bool = False
    duration: float = 0


class AdminStatsOut(BaseModel):
    user_count: int
    order_paid_total_fen: int
    order_paid_today_fen: int
    project_status_counts: dict[str, int]
    drama_project_count: int = 0
    usage_calls_today: int = 0
    usage_calls_month: int = 0
    usage_calls_total: int = 0
    usage_charge_today_fen: int = 0
    usage_charge_month_fen: int = 0
    usage_charge_total_fen: int = 0
    usage_cost_today_fen: int = 0
    usage_cost_month_fen: int = 0
    usage_cost_total_fen: int = 0
    usage_by_capability: list[AdminUsageBucketOut] = Field(default_factory=list)
    usage_by_domain: list[AdminUsageBucketOut] = Field(default_factory=list)
    daily_usage: list[AdminDailyUsageOut] = Field(default_factory=list)
    top_users_by_charge: list[AdminTopUserOut] = Field(default_factory=list)


class AdminQueueTaskOut(BaseModel):
    task_id: str
    task_name: str
    label: str
    args_repr: str
    queue: str
    state: str
    started_at: float | None = None
    ref_id: int | None = None
    position: int | None = None


class AdminQueueSummaryOut(BaseModel):
    name: str
    label: str
    pending: int
    sample: list[AdminQueueTaskOut]


class AdminQueuesOut(BaseModel):
    ok: bool
    redis_ok: bool
    unacked: int
    total_pending: int
    active_count: int
    reserved_count: int
    queues: list[AdminQueueSummaryOut]
    pending_tasks: list[AdminQueueTaskOut]
    active_tasks: list[AdminQueueTaskOut]
    reserved_tasks: list[AdminQueueTaskOut]
    runtime: dict[str, float | int | str]
    fetched_at: str


class AdminUserOut(BaseModel):
    id: int
    email: EmailStr
    nickname: str
    quota_left: int
    balance_fen: int
    frozen_fen: int
    plan: str
    role: str
    phone: str = ""
    created_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone(cls, value: Any) -> str:
        return str(value or "")


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    meta: PageMeta


class AdminUserPatch(BaseModel):
    plan: str | None = None
    role: str | None = None
    # Absolute target balance in fen; when set, write ledger delta
    balance_fen: int | None = None
    balance_note: str | None = None


class AdminOrderOut(BaseModel):
    id: int
    out_trade_no: str
    user_id: int
    user_email: str | None = None
    sku_id: str
    amount_fen: int
    credit_fen: int
    pay_type: str
    status: str
    trade_no: str | None
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminOrderListOut(BaseModel):
    items: list[AdminOrderOut]
    meta: PageMeta


class AdminLedgerOut(BaseModel):
    id: int
    user_id: int
    user_email: str | None = None
    delta_fen: int
    balance_after: int
    kind: str
    ref_type: str
    ref_id: str
    note: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminLedgerListOut(BaseModel):
    items: list[AdminLedgerOut]
    meta: PageMeta


class AdminProjectOut(BaseModel):
    id: int
    user_id: int
    user_email: str | None = None
    template_id: str
    title: str
    status: str
    progress: int
    error_msg: str | None
    cover_url: str | None
    final_video_url: str | None
    pipeline_mode: str
    created_at: datetime
    updated_at: datetime
    shot_count: int = 0
    charge_fen: int = 0

    model_config = {"from_attributes": True}


class AdminProjectListOut(BaseModel):
    items: list[AdminProjectOut]
    meta: PageMeta


class AdminProjectDetailOut(AdminProjectOut):
    source_type: str
    source_text: str
    resolution_mode: str
    output_ratio: str
    voice_id: str
    usage: AdminProjectUsageOut = Field(default_factory=AdminProjectUsageOut)
    shots: list[AdminShotBriefOut] = Field(default_factory=list)
    recent_tasks: list[AdminTaskBriefOut] = Field(default_factory=list)


class AdminWorkOut(BaseModel):
    id: int
    project_id: int | None = None
    user_id: int
    user_email: str | None = None
    title: str
    cover_url: str | None
    video_url: str
    visibility: str
    audit_status: str
    published_at: datetime

    model_config = {"from_attributes": True}


class AdminWorkListOut(BaseModel):
    items: list[AdminWorkOut]
    meta: PageMeta


class AdminWorkPatch(BaseModel):
    visibility: str | None = None
    audit_status: str | None = None


class AdminTemplateOut(BaseModel):
    id: str
    name: str
    description: str
    category: list
    preview_cover: str
    style_prefix: str
    negative_prompt: str
    default_ratio: str
    shot_duration_min: int
    shot_duration_max: int
    llm_system_addon: str
    seedream_config: dict
    seedance_config: dict
    audio_config: dict
    subtitle_config: dict
    sort_order: int
    is_active: bool
    is_premium: bool

    model_config = {"from_attributes": True}


class AdminTemplateListOut(BaseModel):
    items: list[AdminTemplateOut]
    meta: PageMeta


class AdminTemplateCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    category: list[str] = Field(default_factory=list)
    preview_cover: str = ""
    style_prefix: str = ""
    negative_prompt: str = ""
    default_ratio: str = "16:9"
    shot_duration_min: int = 3
    shot_duration_max: int = 8
    llm_system_addon: str = ""
    seedream_config: dict = Field(default_factory=dict)
    seedance_config: dict = Field(default_factory=dict)
    audio_config: dict = Field(default_factory=dict)
    subtitle_config: dict = Field(default_factory=dict)
    sort_order: int = 0
    is_active: bool = True
    is_premium: bool = False


class AdminTemplatePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    category: list[str] | None = None
    preview_cover: str | None = None
    style_prefix: str | None = None
    negative_prompt: str | None = None
    default_ratio: str | None = None
    shot_duration_min: int | None = None
    shot_duration_max: int | None = None
    llm_system_addon: str | None = None
    seedream_config: dict | None = None
    seedance_config: dict | None = None
    audio_config: dict | None = None
    subtitle_config: dict | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    is_premium: bool | None = None
