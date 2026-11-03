"""下游请求契约；完整更新配合版本号防止审核竞态。"""
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Version(Input):
    version: int = Field(ge=1)


class WorkInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    category: str = Field(default="其他", min_length=1, max_length=60)
    category_code: str | None = Field(default=None, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    tags: list[str] = Field(default_factory=list, max_length=10)
    price_fen: int = Field(ge=0, le=100_000_000)
    sale_type: Literal["free", "copyright_contact", "platform_unlock"] = "copyright_contact"
    unlock_price_fen: int = Field(default=0, ge=0, le=100_000_000)
    share_bps: int | None = Field(default=None, ge=0, le=10000)
    asset_id: int | None = Field(default=None, gt=0)
    cover_asset_id: int | None = Field(default=None, gt=0)
    source: Literal["printfilm", "external", "original", "ai", "authorized"] = "original"
    license_scope: str = Field(default="", max_length=3000)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        """限制标签长度，避免无界公开字段。"""
        if any(not tag.strip() or len(tag) > 30 for tag in value):
            raise ValueError("标签应为1至30字")
        return list(dict.fromkeys(tag.strip() for tag in value))

    @field_validator("unlock_price_fen")
    @classmethod
    def validate_unlock_price(cls, value, info):
        sale_type = info.data.get("sale_type", "copyright_contact")
        if sale_type == "platform_unlock" and value <= 0:
            raise ValueError("平台投放作品必须设置单独的解锁价")
        if sale_type != "platform_unlock" and value:
            raise ValueError("只有平台投放作品可以设置解锁价")
        return value


class WorkUpdate(WorkInput, Version):
    pass


class RightsDetails(Input):
    author: str = Field(default="", max_length=200)
    holder: str = Field(default="", max_length=200)
    relationship: str = Field(default="", max_length=1000)
    acquisition: Literal["original", "transferred", "authorized"] = "original"
    source: Literal["printfilm", "external", "original", "ai", "authorized"] = "external"
    scope: str = Field(default="", max_length=3000)
    third_party: str = Field(default="", max_length=3000)
    institution: str = Field(default="", max_length=200)
    certificate_number: str = Field(default="", max_length=200)
    ai_platform_license: str = Field(default="", max_length=3000)
    ai_generation_record: str = Field(default="", max_length=3000)
    human_contribution: str = Field(default="", max_length=3000)
    dispute_ack: bool = False


class RightsInput(Input):
    version: int = Field(default=0, ge=0)
    details: RightsDetails
    certificate_asset_id: int | None = Field(default=None, gt=0)
    evidence_ids: list[int] = Field(default_factory=list, max_length=20)
    valid_until: AwareDatetime | None = None


class CaseInput(Input):
    version: int = Field(default=0, ge=0)
    route: Literal["existing", "self_service", "assisted"]
    official_reference: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=3000)


class RecruitInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    category: str = Field(default="其他", min_length=1, max_length=60)
    category_code: str | None = Field(default=None, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    budget_fen: int = Field(gt=0, le=100_000_000)
    wanted_count: int = Field(ge=1, le=10000)
    requirements: str = Field(min_length=1, max_length=3000)
    license_scope: str = Field(min_length=1, max_length=3000)
    image_ids: list[int] = Field(default_factory=list, max_length=6)
    deadline_at: AwareDatetime


class RecruitUpdate(RecruitInput, Version):
    pass


class SubmissionInput(Input):
    asset_id: int = Field(gt=0)
    quote_fen: int = Field(gt=0, le=100_000_000)
    description: str = Field(default="", max_length=3000)
    rights_accepted: Literal[True]


class SelectionInput(Input):
    selection: Literal["to_review", "candidate", "not_selected"]


class UploadInput(Input):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    kind: Literal["video", "image", "document", "qr"]


class ReviewInput(Version):
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=3000)
    checks: list[str] = Field(default_factory=list, max_length=12)


class BlockInput(Input):
    blocked: bool
    reason: str = Field(min_length=1, max_length=3000)


class CaseReview(Version):
    status: Literal["pending_materials", "reviewing", "supplement", "applying", "certificated", "rejected", "cancelled"]
    note: str = Field(min_length=1, max_length=3000)


class SupportInput(Input):
    name: str = Field(min_length=1, max_length=80)
    name_en: str = Field(default="", max_length=160)
    wechat: str = Field(default="", max_length=100)
    hours: str = Field(default="", max_length=100)
    hours_en: str = Field(default="", max_length=200)
    qr_asset_id: int | None = Field(default=None, gt=0)
    enabled: bool = False


class CategoryEntryInput(Input):
    """分类固定标识只创建一次，显示名称可编辑。"""
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    name_zh: str = Field(min_length=1, max_length=60)
    name_en: str = Field(default="", max_length=120)
    enabled: bool = True


class CategoryInput(Input):
    version: int = Field(ge=0)
    names: list[str] | None = Field(default=None, min_length=1, max_length=30)
    items: list[CategoryEntryInput] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("names")
    @classmethod
    def validate_names(cls, value):
        if value is None:
            return value
        names = [name.strip() for name in value]
        if any(not name or len(name) > 60 for name in names) or len(set(names)) != len(names):
            raise ValueError("分类名称须为1至60字，且不能重复")
        return names

    @model_validator(mode="after")
    def validate_entries(self):
        """只接受一种管理契约，限制启用分类数量并防止重复代码。"""
        if (self.names is None) == (self.items is None):
            raise ValueError("请提交分类名称或双语分类列表")
        if self.items is not None:
            if len({item.code for item in self.items}) != len(self.items) or len({item.name_zh for item in self.items}) != len(self.items):
                raise ValueError("分类代码与中文名称不能重复")
            if not 1 <= sum(item.enabled for item in self.items) <= 30:
                raise ValueError("请启用1至30个分类")
        return self


class Target(Input):
    target_type: Literal["work", "recruit", "submission", "series_episode", "case"]
    target_id: int = Field(gt=0)


class ReportInput(Target):
    statement: str = Field(min_length=10, max_length=5000)
    contact: str = Field(min_length=1, max_length=200)
    evidence_ids: list[int] = Field(default_factory=list, max_length=10)


class ResolutionInput(Input):
    resolution: str = Field(min_length=1, max_length=3000)


class SeriesInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    category: str = Field(default="其他", min_length=1, max_length=60)
    category_code: str | None = Field(default=None, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    tags: list[str] = Field(default_factory=list, max_length=10)
    cover_asset_id: int | None = Field(default=None, gt=0)
    sale_type: Literal["free", "copyright_contact", "platform_unlock"] = "copyright_contact"
    copyright_price_fen: int = Field(default=0, ge=0, le=100_000_000)
    free_episode_count: int = Field(default=0, ge=0, le=10000)
    share_bps: int | None = Field(default=None, ge=0, le=10000)


class SeriesUpdate(SeriesInput, Version):
    pass


class EpisodeInput(Input):
    episode_no: int = Field(ge=1, le=10000)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    asset_id: int | None = Field(default=None, gt=0)
    cover_asset_id: int | None = Field(default=None, gt=0)
    copyright_price_fen: int = Field(default=0, ge=0, le=100_000_000)
    unlock_price_fen: int = Field(default=0, ge=0, le=100_000_000)
    share_bps: int | None = Field(default=None, ge=0, le=10000)
    source: Literal["printfilm", "external", "original", "ai", "authorized"] = "external"


class EpisodeUpdate(EpisodeInput, Version):
    pass


class ImportEpisodesInput(Input):
    drama_project_id: int = Field(gt=0)
    episode_ids: list[int] = Field(min_length=1, max_length=100)


class PrintfilmWorkInput(Input):
    project_id: int = Field(gt=0)
    source_type: Literal["project_final"] = "project_final"
    idempotency_key: str = Field(default="", max_length=120)


class PrintfilmEpisodeInput(Input):
    """漫剧分集或一部科普成片，二选一。客户端不能提交视频地址。"""
    drama_project_id: int | None = Field(default=None, gt=0)
    episode_ids: list[int] = Field(default_factory=list, max_length=100)
    project_id: int | None = Field(default=None, gt=0)
    idempotency_key: str = Field(default="", max_length=80)
    update_episode_ids: list[int] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def choose_source(self):
        has_drama = self.drama_project_id is not None and bool(self.episode_ids)
        has_project = self.project_id is not None
        if has_drama == has_project:
            raise ValueError("请选择漫剧分集或一部科普成片")
        if any(item <= 0 for item in self.episode_ids):
            raise ValueError("分集编号无效")
        return self


class DramaPublishEpisode(Input):
    episode_id: int = Field(gt=0)
    source_version: str = Field(min_length=1, max_length=80)
    update: bool = False


class DramaPublishInput(Input):
    episodes: list[DramaPublishEpisode] = Field(min_length=1, max_length=100)
    series_id: int | None = Field(default=None, gt=0)
    series_version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=120)

    @model_validator(mode="after")
    def distinct_episodes(self):
        if len({item.episode_id for item in self.episodes}) != len(self.episodes):
            raise ValueError("不能重复选择同一分集")
        return self


class RevenueConfigInput(Input):
    version: int = Field(ge=0)
    platform_share_bps: int = Field(ge=0, le=10000)
    enabled: bool = True


class ContentOrderInput(Input):
    publication_id: int = Field(gt=0)
    pay_type: Literal["alipay", "wxpay"]
    idempotency_key: str = Field(min_length=8, max_length=128)


class PayoutInput(Input):
    owner_id: int = Field(gt=0)
    amount_fen: int = Field(gt=0, le=100_000_000_000)
    status: Literal["pending", "paid", "failed"] = "pending"
    note: str = Field(default="", max_length=3000)
