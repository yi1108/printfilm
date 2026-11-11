"""Pydantic schemas for the drama module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas_common import PageMeta
from app.schemas_tasks import TaskRunBriefOut
from app.schemas_media_references import MediaReferenceOut


class DramaProjectCreate(BaseModel):
    """创建项目及初始剧本草稿的配置。"""

    team_id: int | None = Field(default=None, gt=0, description="所属团队编号；省略时沿用当前团队空间，无团队空间时创建个人项目")
    title: str = Field(default="未命名漫剧", max_length=200, description="项目标题，最多 200 字；去除首尾空白后为空时按创意前 40 字生成")
    description: str | None = Field(default=None, description="项目简介，可省略")
    source: str = Field(default="", description="原始创意文案，去除首尾空白后至少 20 字；同时保存为初始剧本的创意来源")
    episode_count: int = Field(default=1, strict=True, ge=1, le=120, description="初始集数，支持 1 至 120 集，后续可在项目中增加分集")
    image_style_id: str = Field(default="", description="图片风格标识，空字符串表示未指定风格")
    # script=大纲分集流程；canvas=自由画布
    workflow: str = Field(default="script", description="工作流：script 为大纲及分集创作，canvas 为自由画布；去除首尾空白并转小写后，其他值回退为 script")
    params: dict[str, Any] | None = Field(default=None, description="项目扩展配置；workflow、episode_count、image_style_id 由专用字段覆盖，其中画布目标集数保存为 0")


class DramaProjectUpdate(BaseModel):
    """项目局部更新；省略或传 null 的字段保持原值。"""

    title: str | None = Field(default=None, description="新标题；去除首尾空白后为空时保留原标题")
    description: str | None = Field(default=None, description="新简介；空字符串可清空简介")
    content: dict | list | None = Field(default=None, description="项目内容，整体替换现有对象或数组，不做增量合并")
    params: dict[str, Any] | None = Field(default=None, description="项目配置，整体替换现有配置；请保留所需的工作流、模型及风格等键，尾帧衔接开关变化会触发排队任务重排")


class DramaScriptOut(BaseModel):
    """项目剧本及摘要、分集正文和生成状态。"""

    id: int = Field(description="剧本编号")
    name: str = Field(description="剧本名称")
    source: str | None = Field(default=None, description="原始创意文案")
    summary: dict | None = Field(default=None, description="结构化剧本摘要，包含剧名、人物设定、目标集数等信息，生成前可为空")
    episode_content: dict | list | None = Field(default=None, description="分集剧本内容，通常为含 episodes 数组的对象，也兼容直接保存的数组")
    params: dict | None = Field(default=None, description="剧本配置与任务状态，如 summary_status、episode_content_status、episode_optimize_status 及团队分集任务 episode_jobs")
    project_id: int = Field(description="所属项目编号")

    model_config = {"from_attributes": True}


class DramaAssetOut(BaseModel):
    id: int
    type: str
    asset_type: str
    name: str | None = None
    cover: str | None = None
    url: str | None = None
    params: dict | None = None
    references: list[MediaReferenceOut] = Field(default_factory=list)
    derive_id: str | None = None
    project_id: int
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

class DramaProjectUsageStats(BaseModel):
    """单部漫剧累计用量：扣费与生图/生视频次数。"""

    charge_fen: int = Field(default=0, description="当前可见用量记录的累计扣费，单位为分")
    charge_yuan: float = Field(default=0.0, description="累计扣费，单位为元，由 charge_fen 除以 100 后保留两位小数")
    tokens: int = Field(default=0, description="当前可见用量记录的累计 Token 数")
    calls: int = Field(default=0, description="当前可见用量记录条数，包含不同计费类型")
    image_gens: int = Field(default=0, description="生图用量记录数，按 billing_key 为 seedream 统计")
    video_gens: int = Field(default=0, description="生视频用量记录数，按 billing_key 以 seedance 开头统计")


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
    """漫剧或自由画布项目详情。"""

    id: int = Field(description="项目编号")
    user_id: int = Field(description="项目原始创建者的用户编号；团队访问权限以当前团队成员关系为准")
    team_id: int | None = Field(default=None, description="所属团队编号，null 表示个人空间")
    title: str = Field(description="项目标题")
    description: str | None = Field(default=None, description="项目简介")
    content: dict | list | None = Field(default=None, description="项目内容或画布数据，未保存时可为空")
    params: dict | None = Field(default=None, description="项目配置，包括工作流、目标集数、图片风格及生成设置等")
    created_at: datetime | None = Field(default=None, description="项目创建时间")
    updated_at: datetime | None = Field(default=None, description="项目最近更新时间")
    script: DramaScriptOut | None = Field(default=None, description="关联剧本及其生成状态，无剧本时为 null")
    asset_count: int = Field(default=0, description="项目下的资产数量")
    episode_count: int = Field(default=0, description="已建立的分集数量，不等于配置的目标集数")
    # script | canvas
    workflow: str = Field(default="script", description="解析后的工作流：script 为剧本分集，canvas 为自由画布，兼容历史项目标记")
    usage: DramaProjectUsageStats = Field(default_factory=lambda: DramaProjectUsageStats(), description="当前空间内可见的项目累计用量；团队所有者可见团队合计，其他成员仅可见本人用量")
    active_tasks: list[TaskRunBriefOut] = Field(default_factory=list, description="活动任务摘要，未附带任务投影时为空数组")

    model_config = {"from_attributes": True}


class DramaProjectListItem(BaseModel):
    is_owner: bool = True
    """项目列表中的概要信息。"""

    id: int = Field(description="项目编号")
    team_id: int | None = Field(default=None, description="所属团队编号，null 表示个人空间")
    title: str = Field(description="项目标题")
    description: str | None = Field(default=None, description="项目简介")
    created_at: datetime | None = Field(default=None, description="项目创建时间")
    updated_at: datetime | None = Field(default=None, description="项目最近更新时间，列表默认按此时间倒序")
    episode_count: int = Field(default=0, description="已建立的分集数量")
    asset_count: int = Field(default=0, description="项目下的资产数量")
    has_script: bool = Field(default=False, description="是否已存在关联剧本记录，不表示正文已生成")
    cover_url: str | None = Field(default=None, description="项目可用的封面地址，尚无可用封面时为 null")
    cover_pending: bool = Field(default=False, description="尚无可用封面且相关生成仍在进行时为 true")
    # script | canvas
    workflow: str = Field(default="script", description="解析后的工作流：script 为剧本分集，canvas 为自由画布")
    usage: DramaProjectUsageStats = Field(default_factory=lambda: DramaProjectUsageStats(), description="当前空间内可见的项目累计用量；团队所有者可见团队合计，其他成员仅可见本人用量")
    active_tasks: list[TaskRunBriefOut] = Field(default_factory=list, description="活动任务摘要，未附带任务投影时为空数组")

    model_config = {"from_attributes": True}


class DramaProjectListOut(BaseModel):
    """漫剧/自由画布项目分页列表。"""

    items: list[DramaProjectListItem] = Field(default_factory=list, description="筛选并分页后的项目概要列表")
    meta: PageMeta = Field(description="分页信息，total 为筛选后的项目总数，page 为服务端修正后的页码")


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
    # 只优化/生成这一集；与 draft 一起用于「粘贴剧本 → AI 优化」
    episode_number: int | None = Field(default=None, ge=1, le=120)
    draft: str | None = Field(default=None, max_length=50000)
    # optimize=草稿优化；summary=创意→摘要；body=创意+摘要→正文；full=一键摘要+正文；brief=正文→创意+摘要
    generate_mode: str | None = Field(default=None, max_length=32)
    # 可选：生成前写入本集创意（并保存）
    creative: str | None = Field(default=None, max_length=20000)
    title: str | None = Field(default=None, max_length=40)


class DramaAddEpisodeRequest(BaseModel):
    project_id: int
    title: str | None = Field(default=None, max_length=40)


class DramaConfirmEpisodeRequest(BaseModel):
    project_id: int
    episode_number: int = Field(ge=1, le=120)


class DramaConfirmEpisodeOut(BaseModel):
    episode: DramaEpisodeOut
    assets_status: str = "done"
    created_count: int = 0


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
        description="关联角色资产 ID",
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
    # 视频模型：后台 TokenFree 目录 id
    model_id: str | None = Field(default=None, max_length=64)


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


class DramaActivateImageVersionRequest(BaseModel):
    # version_id 资产形象历史版本 id（params.image_versions[].id）
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
