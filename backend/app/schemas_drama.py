"""Pydantic schemas for the drama module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas_tasks import TaskRunBriefOut


class DramaProjectCreate(BaseModel):
    title: str = Field(default="未命名漫剧", max_length=200)
    description: str | None = None
    source: str = Field(default="", description="原始创意文案")
    episode_count: int = Field(default=12, ge=1, le=120)
    image_style_id: str = Field(default="")
    # script=大纲分集流程；canvas=自由画布
    workflow: str = Field(default="script", description="script | canvas")
    params: dict[str, Any] | None = None


class DramaProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    content: dict | list | None = None
    params: dict[str, Any] | None = None


class DramaScriptOut(BaseModel):
    id: int
    name: str
    source: str | None = None
    summary: dict | None = None
    episode_content: dict | list | None = None
    params: dict | None = None
    project_id: int

    model_config = {"from_attributes": True}


class DramaAssetOut(BaseModel):
    id: int
    type: str
    asset_type: str
    name: str | None = None
    cover: str | None = None
    url: str | None = None
    params: dict | None = None
    derive_id: str | None = None
    project_id: int

    model_config = {"from_attributes": True}


class DramaProjectUsageStats(BaseModel):
    """单部漫剧累计用量：费用与生图/生视频次数。"""

    charge_fen: int = 0
    charge_yuan: float = 0.0
    cost_fen: int = 0
    cost_yuan: float = 0.0
    tokens: int = 0
    calls: int = 0
    image_gens: int = 0
    video_gens: int = 0


class SeedAssetsFromScriptOut(BaseModel):
    """从剧本抽取/刷新资产的结果统计。"""

    assets: list[DramaAssetOut] = Field(default_factory=list)
    created_count: int = 0
    prompts_refreshed: int = 0
    props_updated: int = 0
    llm_errors: list[str] = Field(default_factory=list)
    status: str = "done"
    message: str | None = None


class DramaFragmentOut(BaseModel):
    id: int
    episode_id: int
    sort_order: int
    content: str
    cover: str = ""
    video: str = ""
    duration_sec: int | None = None
    params: dict | None = None
    asset_ids: list[int] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DramaEpisodeOut(BaseModel):
    id: int
    name: str
    params: dict | None = None
    project_id: int
    fragments: list[DramaFragmentOut] = Field(default_factory=list)
    active_tasks: list[TaskRunBriefOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DramaEpisodeUpdate(BaseModel):
    name: str | None = None
    params: dict | None = None


class DramaProjectOut(BaseModel):
    id: int
    user_id: int
    title: str
    description: str | None = None
    content: dict | list | None = None
    params: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    script: DramaScriptOut | None = None
    asset_count: int = 0
    episode_count: int = 0
    # script | canvas
    workflow: str = "script"
    usage: DramaProjectUsageStats = Field(default_factory=lambda: DramaProjectUsageStats())
    active_tasks: list[TaskRunBriefOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DramaProjectListItem(BaseModel):
    id: int
    title: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    episode_count: int = 0
    asset_count: int = 0
    has_script: bool = False
    cover_url: str | None = None
    cover_pending: bool = False
    # script | canvas
    workflow: str = "script"
    usage: DramaProjectUsageStats = Field(default_factory=lambda: DramaProjectUsageStats())
    active_tasks: list[TaskRunBriefOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DramaScriptSummaryRequest(BaseModel):
    project_id: int
    creative: str | None = None
    episode_count: int | None = None
    image_style_id: str | None = None


class DramaEpisodeScriptRequest(BaseModel):
    project_id: int
    # 与原项目一致：默认逐集生成，降低超时/截断导致「只出一半」的风险
    batch_size: int = Field(default=1, ge=1, le=12)
    # 强制重写：清空已有正文（保留集名），再按新提示词生成
    force: bool = False


class DramaAssetCreate(BaseModel):
    project_id: int
    type: str = "none"
    asset_type: str = "image"
    name: str | None = None
    cover: str | None = None
    url: str | None = None
    params: dict | None = None


class DramaAssetUpdate(BaseModel):
    type: str | None = None
    asset_type: str | None = None
    name: str | None = None
    cover: str | None = None
    url: str | None = None
    params: dict | None = None


class DramaImageGenerateRequest(BaseModel):
    project_id: int
    asset_id: int | None = None
    prompt: str
    name: str | None = None
    asset_type_kind: str = "character"
    # 内置风格 ID（可缺省，回退项目/剧本 params.image_style_id）
    image_style_id: str | None = None
    # 前端模型 ID：seedream-5.0 / seedream-4.5
    model_id: str | None = None
    # 输出比例，角色默认 3:4
    aspect_ratio: str | None = None
    # 清晰度 3K / 4K
    resolution: str | None = None


class DramaVideoGenerateRequest(BaseModel):
    project_id: int
    asset_id: int
    prompt: str
    # 前端短名 seedance-2.5 / seedance-1.5，或完整接入点
    model_id: str | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    duration_sec: int | None = None
    image_style_id: str | None = None
    # 画布连线带入的参考资产（与正文 @asset:id 合并）
    reference_asset_ids: list[int] = Field(default_factory=list)


class DramaVoicePromptRequest(BaseModel):
    project_id: int
    asset_id: int


class DramaVoiceGenerateRequest(BaseModel):
    project_id: int
    asset_id: int | None = None
    name: str | None = None
    voice_prompt: str = Field(description="音色描述，用于 TTS 试听与 Seedance reference_audio")
    sample_text: str | None = Field(default=None, description="试听台词，缺省自动生成")
    speaker: str | None = Field(default=None, description="可选 TTS speaker 覆盖")
    character_asset_id: int | None = Field(
        default=None,
        description="关联角色资产 ID，用于 voice_design image_prompt",
    )


class DramaFragmentSaveItem(BaseModel):
    id: int | None = None
    sort_order: int = 0
    content: str = ""
    cover: str = ""
    video: str = ""
    duration_sec: int | None = None
    params: dict | None = None
    asset_ids: list[int] = Field(default_factory=list)


class DramaSaveFragmentsRequest(BaseModel):
    fragments: list[DramaFragmentSaveItem]


class DramaGenerateRequest(BaseModel):
    fragment_ids: list[int] | None = None


class DramaComposeEpisodeRequest(BaseModel):
    # fragment_ids 仅拼接指定分镜；None 表示本集全部已有视频的分镜
    fragment_ids: list[int] | None = None


class DramaPlanFragmentsRequest(BaseModel):
    # force 是否覆盖已有视频/手改分镜（单集 AI 重切默认 true）
    force: bool = True
    # fallback_rules LLM 失败时是否回退规则切分
    fallback_rules: bool = True
    # skill_ids 本次注入的 Agent Skill；None 表示全部启用，[] 表示不注入
    skill_ids: list[int] | None = None
    # subtitle_enabled 是否为本次分镜注入字幕提示；None 表示沿用分集当前设置
    subtitle_enabled: bool | None = None


class DramaActivateVideoVersionRequest(BaseModel):
    # version_id 历史成片版本 id（params.video_versions[].id）
    version_id: str = Field(..., min_length=1, max_length=128)


class DramaCanvasSaveRequest(BaseModel):
    project_id: int
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class DramaChatRequest(BaseModel):
    message: str
    project_id: int | None = None


class DramaRouteRequest(BaseModel):
    message: str
