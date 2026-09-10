from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    SCRIPTING = "SCRIPTING"
    SCRIPT_READY = "SCRIPT_READY"
    IMAGING = "IMAGING"
    IMAGE_READY = "IMAGE_READY"
    VIDEOING = "VIDEOING"
    VIDEO_READY = "VIDEO_READY"
    AUDIOING = "AUDIOING"
    COMPOSING = "COMPOSING"
    AUDITING = "AUDITING"
    DONE = "DONE"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ShotStatus(StrEnum):
    PENDING = "PENDING"
    IMAGE_READY = "IMAGE_READY"
    VIDEO_READY = "VIDEO_READY"
    AUDIO_READY = "AUDIO_READY"
    FAILED = "FAILED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="创作者")
    hashed_password: Mapped[str] = mapped_column(String(255))
    # Legacy field; prefer balance_fen for billing
    quota_left: Mapped[int] = mapped_column(Integer, default=5)
    balance_fen: Mapped[int] = mapped_column(Integer, default=0)
    frozen_fen: Mapped[int] = mapped_column(Integer, default=0)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    # user | admin
    role: Mapped[str] = mapped_column(String(16), default="user")
    avatar_url: Mapped[str] = mapped_column(String(512), default="")
    # 联系手机，仅记录，不走短信验证
    phone: Mapped[str] = mapped_column(String(32), default="")
    # 用户消费里程碑告警：上次已提醒的累计扣费档位（分）
    billing_alert_last_milestone_fen: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")


class BillingAlertNotification(Base):
    """待展示的用户额度告警（弹窗）。"""

    __tablename__ = "billing_alert_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="user_milestone")
    title: Mapped[str] = mapped_column(String(128), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    milestone_fen: Mapped[int] = mapped_column(Integer, default=0)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[list] = mapped_column(JSON, default=list)
    preview_cover: Mapped[str] = mapped_column(String(512), default="")
    style_prefix: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    default_ratio: Mapped[str] = mapped_column(String(16), default="16:9")
    shot_duration_min: Mapped[int] = mapped_column(Integer, default=3)
    shot_duration_max: Mapped[int] = mapped_column(Integer, default=8)
    llm_system_addon: Mapped[str] = mapped_column(Text, default="")
    seedream_config: Mapped[dict] = mapped_column(JSON, default=dict)
    seedance_config: Mapped[dict] = mapped_column(JSON, default=dict)
    audio_config: Mapped[dict] = mapped_column(JSON, default=dict)
    subtitle_config: Mapped[dict] = mapped_column(JSON, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="未命名作品")
    source_type: Mapped[str] = mapped_column(String(16), default="theme")  # theme | script
    source_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=ProjectStatus.DRAFT)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    final_video_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    resolution_mode: Mapped[str] = mapped_column(String(16), default="preview")  # preview | hd
    # full = 图→视频→配音→合成；image_text = 静图+叠字+配音+Ken Burns（跳过 AI 视频）
    # 由用户选择，不由模板锁定
    pipeline_mode: Mapped[str] = mapped_column(String(32), default="full")
    # 输出画幅，如 16:9 / 9:16；空则回退模板 default_ratio
    output_ratio: Mapped[str] = mapped_column(String(16), default="")
    # TTS voice id (openspeech speaker or preset alias); empty → template default
    voice_id: Mapped[str] = mapped_column(String(128), default="")
    # Canonical cast/look description for Seedream consistency across shots
    character_bible: Mapped[str] = mapped_column(Text, default="")
    # Project-level BGM mood lock (same across shots)
    bgm_lock: Mapped[str] = mapped_column(Text, default="")
    # User overrides from studio (optional)
    style_prompt: Mapped[str] = mapped_column(Text, default="")
    character_prompt: Mapped[str] = mapped_column(Text, default="")
    extra_prompt: Mapped[str] = mapped_column(Text, default="")
    ref_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="projects")
    template: Mapped["Template"] = relationship()
    shots: Mapped[list["Shot"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[list["PipelineJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    shot_no: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float] = mapped_column(Float, default=4.0)
    narration: Mapped[str] = mapped_column(Text, default="")  # TTS 旁白
    overlay_title: Mapped[str] = mapped_column(String(128), default="")  # 图文顶部大标题
    overlay_subtitle: Mapped[str] = mapped_column(String(256), default="")  # 图文顶部副标题（叠字）
    img_prompt: Mapped[str] = mapped_column(Text, default="")
    video_prompt: Mapped[str] = mapped_column(Text, default="")
    # Manju-style timed segment script (@duration + production cues)
    segment_script: Mapped[str] = mapped_column(Text, default="")
    camera: Mapped[str] = mapped_column(String(64), default="slow pan")
    bgm_mood: Mapped[str] = mapped_column(String(64), default="neutral")
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_ark_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=ShotStatus.PENDING)
    version: Mapped[int] = mapped_column(Integer, default=1)

    project: Mapped["Project"] = relationship(back_populates="shots")


class PipelineJob(Base):
    __tablename__ = "pipeline_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="jobs")


class Work(Base):
    __tablename__ = "works"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    video_url: Mapped[str] = mapped_column(String(1024))
    visibility: Mapped[str] = mapped_column(String(16), default="public")
    audit_status: Mapped[str] = mapped_column(String(16), default="passed")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageEvent(Base):
    """One upstream model/TTS call for token billing."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Drama module billing ref (mutually exclusive with kepu project_id when set)
    drama_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    task_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    capability: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    shot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="ark")
    billing_key: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    charge_fen: Mapped[int] = mapped_column(Integer, default=0)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    settled: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UpstreamUsageDaily(Base):
    """方舟官方日用量快照，用于与本地 usage_events 对照。"""

    __tablename__ = "upstream_usage_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    official_tokens: Mapped[int] = mapped_column(Integer, default=0)
    official_cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    local_cost_fen: Mapped[int] = mapped_column(Integer, default=0)
    local_tokens: Mapped[int] = mapped_column(Integer, default=0)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WalletLedger(Base):
    __tablename__ = "wallet_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    delta_fen: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(32))  # topup|grant|freeze|unfreeze|settle|refund
    ref_type: Mapped[str] = mapped_column(String(32), default="")
    ref_id: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sku_id: Mapped[str] = mapped_column(String(64))
    amount_fen: Mapped[int] = mapped_column(Integer)
    credit_fen: Mapped[int] = mapped_column(Integer)
    pay_type: Mapped[str] = mapped_column(String(16))  # alipay | wxpay
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|paid|closed
    trade_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolRun(Base):
    """独立创作工具一次生成记录，供个人中心回看。"""

    __tablename__ = "tool_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tool_id: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="image")
    status: Mapped[str] = mapped_column(String(16), default="succeeded", index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    preview_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
