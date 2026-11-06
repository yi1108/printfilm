"""独立 metadata 和 marketplace_ 表；不对原表做 DDL。"""
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class MarketBase(DeclarativeBase):
    """下游专用 metadata；用户 ID 只引用现有身份，不修改原表。"""


class Record:
    """业务记录公共字段；时间由数据库生成。"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Authorization(Record, MarketBase):
    """账号授权函不可变存档；逐件权属档案引用签署记录。"""
    __tablename__ = "marketplace_authorizations"
    __table_args__ = (UniqueConstraint("owner_id", "template_version"),)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    template_version: Mapped[str] = mapped_column(String(60))
    signer_name: Mapped[str] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(Text)
    body_hash: Mapped[str] = mapped_column(String(64))
    letter_key: Mapped[str] = mapped_column(String(512))
    signature_key: Mapped[str] = mapped_column(String(512))
    client_ip: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str] = mapped_column(String(512))


class Asset(Record, MarketBase):
    __tablename__ = "marketplace_assets"
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(24))  # video / image / document / qr
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="uploading", index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    duration_seconds: Mapped[float | None]
    display_width: Mapped[int | None] = mapped_column(Integer)
    display_height: Mapped[int | None] = mapped_column(Integer)
    cover_key: Mapped[str | None] = mapped_column(String(512))
    preview_key: Mapped[str | None] = mapped_column(String(512))
    review_key: Mapped[str | None] = mapped_column(String(512))
    error: Mapped[str] = mapped_column(Text, default="")


class Upload(Record, MarketBase):
    __tablename__ = "marketplace_uploads"
    asset_id: Mapped[int] = mapped_column(ForeignKey("marketplace_assets.id"), unique=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    remote_id: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(24), default="uploading")
    part_size: Mapped[int] = mapped_column(Integer)
    parts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Rights(Record, MarketBase):
    __tablename__ = "marketplace_rights"
    asset_id: Mapped[int] = mapped_column(ForeignKey("marketplace_assets.id"), unique=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    basic_status: Mapped[str] = mapped_column(String(24), default="draft")
    full_status: Mapped[str] = mapped_column(String(24), default="draft")
    certificate_asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    evidence_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")


class Work(Record, MarketBase):
    __tablename__ = "marketplace_works"
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    cover_asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60), default="其他")
    category_code: Mapped[str | None] = mapped_column(String(80), index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    price_fen: Mapped[int] = mapped_column(BigInteger)
    sale_type: Mapped[str] = mapped_column(String(24), default="copyright_contact", index=True)
    unlock_price_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    share_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="original")
    license_scope: Mapped[str] = mapped_column(Text, default="")
    audit_status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    listed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RegistrationCase(Record, MarketBase):
    __tablename__ = "marketplace_registration_cases"
    rights_id: Mapped[int] = mapped_column(ForeignKey("marketplace_rights.id"), unique=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    route: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(30), default="pending_materials")
    official_reference: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")


class Recruit(Record, MarketBase):
    __tablename__ = "marketplace_recruits"
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60), default="其他")
    category_code: Mapped[str | None] = mapped_column(String(80), index=True)
    budget_fen: Mapped[int] = mapped_column(BigInteger)
    wanted_count: Mapped[int] = mapped_column(Integer)
    requirements: Mapped[str] = mapped_column(Text)
    license_scope: Mapped[str] = mapped_column(Text)
    image_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    audit_status: Mapped[str] = mapped_column(String(24), default="draft")
    state: Mapped[str] = mapped_column(String(24), default="draft")
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")


class Submission(Record, MarketBase):
    __tablename__ = "marketplace_submissions"
    recruit_id: Mapped[int] = mapped_column(ForeignKey("marketplace_recruits.id"), index=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("marketplace_assets.id"))
    quote_fen: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(Text, default="")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    selection: Mapped[str] = mapped_column(String(24), default="to_review")
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index("marketplace_one_active_submission", "recruit_id", "owner_id", unique=True,
                             postgresql_where=text("withdrawn = false")),)


class MediaJob(Record, MarketBase):
    __tablename__ = "marketplace_media_jobs"
    asset_id: Mapped[int] = mapped_column(ForeignKey("marketplace_assets.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(Text, default="")


class Handoff(Record, MarketBase):
    """PrintFilm 成片转存到市场；同一版本幂等，不改已发布的旧资产。"""
    __tablename__ = "marketplace_handoffs"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key"),)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    source_kind: Mapped[str] = mapped_column(String(24))
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    source_version: Mapped[str] = mapped_column(String(80), default="")
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    target_kind: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    series_id: Mapped[int | None] = mapped_column(Integer)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DramaPublishBatch(Record, MarketBase):
    """一次明确的漫剧发布请求；原子创建系列，重试不能产生空壳或重复系列。"""
    __tablename__ = "marketplace_drama_publish_batches"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key"),)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    series_id: Mapped[int] = mapped_column(ForeignKey("marketplace_series.id"))
    episode_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    handoff_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class WorkPreview(Record, MarketBase):
    """作品专用试看任务，不复用投稿审片或旧资产预览。"""
    __tablename__ = "marketplace_work_previews"
    __table_args__ = (UniqueConstraint("work_id", "asset_id"),)
    work_id: Mapped[int] = mapped_column(ForeignKey("marketplace_works.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("marketplace_assets.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    object_key: Mapped[str | None] = mapped_column(String(512))
    error: Mapped[str] = mapped_column(Text, default="")


class Series(Record, MarketBase):
    """市场短剧系列；与原 drama_* 项目保持数据和生命周期隔离。"""
    __tablename__ = "marketplace_series"
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60), default="其他")
    category_code: Mapped[str | None] = mapped_column(String(80), index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    cover_asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    sale_type: Mapped[str] = mapped_column(String(24), default="copyright_contact", index=True)
    copyright_price_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    free_episode_count: Mapped[int] = mapped_column(Integer, default=0)
    share_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audit_status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    listed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SeriesEpisode(Record, MarketBase):
    """市场剧集分集；每集有独立媒体、价格、权属和购买权益。"""
    __tablename__ = "marketplace_series_episodes"
    __table_args__ = (UniqueConstraint("series_id", "episode_no"),)
    series_id: Mapped[int] = mapped_column(ForeignKey("marketplace_series.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    episode_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    cover_asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    copyright_price_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    unlock_price_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    share_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="external")
    source_type: Mapped[str] = mapped_column(String(24), default="upload")
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    audit_status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    listed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    preview_status: Mapped[str] = mapped_column(String(24), default="none", index=True)
    preview_key: Mapped[str | None] = mapped_column(String(512))
    preview_attempts: Mapped[int] = mapped_column(Integer, default=0)
    playback_status: Mapped[str] = mapped_column(String(24), default="none", index=True)
    playback_manifest_key: Mapped[str | None] = mapped_column(String(512))
    playback_attempts: Mapped[int] = mapped_column(Integer, default=0)


class Publication(Record, MarketBase):
    """提交审核时的不可变发布快照，订单和播放权益始终绑定此版本。"""
    __tablename__ = "marketplace_publications"
    __table_args__ = (UniqueConstraint("content_type", "content_id", "version"),)
    content_type: Mapped[str] = mapped_column(String(24), index=True)
    content_id: Mapped[int] = mapped_column(Integer, index=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer)
    asset_id: Mapped[int] = mapped_column(ForeignKey("marketplace_assets.id"))
    cover_asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    sale_type: Mapped[str] = mapped_column(String(24), index=True)
    copyright_price_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    unlock_price_fen: Mapped[int] = mapped_column(BigInteger, default=0)
    share_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rights_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preview_key: Mapped[str | None] = mapped_column(String(512))
    playback_manifest_key: Mapped[str | None] = mapped_column(String(512))
    preview_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    preview_attempts: Mapped[int] = mapped_column(Integer, default=0)
    preview_error: Mapped[str] = mapped_column(Text, default="")
    playback_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    playback_attempts: Mapped[int] = mapped_column(Integer, default=0)
    playback_error: Mapped[str] = mapped_column(Text, default="")
    audit_status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    listed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reason: Mapped[str] = mapped_column(Text, default="")


class EpisodePreview(Record, MarketBase):
    __tablename__ = "marketplace_episode_previews"
    __table_args__ = (UniqueConstraint("episode_id", "asset_id", "version"),)
    episode_id: Mapped[int] = mapped_column(ForeignKey("marketplace_series_episodes.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("marketplace_assets.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    object_key: Mapped[str | None] = mapped_column(String(512))
    error: Mapped[str] = mapped_column(Text, default="")


class PlaybackJob(Record, MarketBase):
    __tablename__ = "marketplace_playback_jobs"
    __table_args__ = (UniqueConstraint("publication_id"),)
    publication_id: Mapped[int] = mapped_column(ForeignKey("marketplace_publications.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(Text, default="")


class RevenueConfig(MarketBase):
    __tablename__ = "marketplace_revenue_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    platform_share_bps: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ContentOrder(Record, MarketBase):
    __tablename__ = "marketplace_content_orders"
    __table_args__ = (UniqueConstraint("out_trade_no"),)
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("marketplace_publications.id"), index=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_series_episodes.id"), index=True)
    amount_fen: Mapped[int] = mapped_column(BigInteger)
    pay_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    trade_no: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Entitlement(Record, MarketBase):
    __tablename__ = "marketplace_entitlements"
    __table_args__ = (UniqueConstraint("user_id", "publication_id"),)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("marketplace_publications.id"), index=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_series_episodes.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_content_orders.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class RevenueLedger(Record, MarketBase):
    __tablename__ = "marketplace_revenue_ledger"
    order_id: Mapped[int] = mapped_column(ForeignKey("marketplace_content_orders.id"), unique=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("marketplace_publications.id"), index=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    gross_fen: Mapped[int] = mapped_column(BigInteger)
    platform_fen: Mapped[int] = mapped_column(BigInteger)
    creator_fen: Mapped[int] = mapped_column(BigInteger)
    share_bps: Mapped[int] = mapped_column(Integer)
    settlement_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)


class Payout(Record, MarketBase):
    __tablename__ = "marketplace_payouts"
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    amount_fen: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_id: Mapped[int | None] = mapped_column(Integer)


class Event(Record, MarketBase):
    __tablename__ = "marketplace_events"
    actor_id: Mapped[int] = mapped_column(Integer, index=True)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(50))
    version: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")


class Notification(Record, MarketBase):
    __tablename__ = "marketplace_notifications"
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    message: Mapped[str] = mapped_column(Text)
    template_code: Mapped[str] = mapped_column(String(100), default="")
    message_params: Mapped[dict] = mapped_column(JSON, default=dict)
    link: Mapped[str] = mapped_column(String(300))
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class Report(Record, MarketBase):
    __tablename__ = "marketplace_reports"
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    contact: Mapped[str] = mapped_column(String(200))
    evidence_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    resolution: Mapped[str] = mapped_column(Text, default="")


class CategoryConfig(MarketBase):
    __tablename__ = "marketplace_category_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    names: Mapped[list[str]] = mapped_column(JSON)
    items: Mapped[list[dict]] = mapped_column(JSON, default=list)


class Support(MarketBase):
    __tablename__ = "marketplace_support"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(80), default="平台客服")
    name_en: Mapped[str] = mapped_column(String(160), default="")
    wechat: Mapped[str] = mapped_column(String(100), default="")
    hours: Mapped[str] = mapped_column(String(100), default="")
    hours_en: Mapped[str] = mapped_column(String(200), default="")
    qr_asset_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_assets.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
