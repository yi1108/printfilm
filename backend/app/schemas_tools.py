"""独立创作工具请求 / 响应。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas_drama import DramaAssetOut


VideoMode = Literal["text_to_video", "first_last_frame", "omni_reference"]
ReferenceRole = Literal["first_frame", "last_frame", "reference_image", "reference_video", "reference_audio"]


class ToolReference(BaseModel):
    model_config = {"extra": "forbid"}

    role: ReferenceRole
    file_index: int | None = Field(default=None, ge=0, le=11, strict=True)
    asset_id: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def exactly_one_source(self):
        if (self.file_index is None) == (self.asset_id is None):
            raise ValueError("每个参考资料须选择一个上传文件或资产")
        return self


class ToolEstimateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    tool_id: Literal["t2v", "v2v"] = "t2v"
    prompt: str = Field(default="", max_length=7000)
    model_id: str = Field(default="", max_length=128)
    video_mode: VideoMode
    generate_audio: bool | None = None
    ratio: str = Field(default="9:16", max_length=16)
    resolution: str = Field(default="480p", max_length=16)
    duration: str | int = "5s"
    references: list[ToolReference] = Field(default_factory=list, max_length=12)


class ToolReferenceAssetOut(DramaAssetOut):
    media_kind: Literal["image", "video", "audio"]


class ToolRunOut(BaseModel):
    kind: str = Field(description="image | video | audio")
    run_id: int | None = None
    platform_task_id: int | None = None
    urls: list[str] = Field(default_factory=list)
    task_id: str | None = None
    status: str = "succeeded"
    preview_url: str | None = None
    message: str | None = None


class ToolTaskOut(BaseModel):
    status: str
    kind: str = "video"
    urls: list[str] = Field(default_factory=list)
    error: str | None = None
    platform_task_id: int | None = None
    provider_task_id: str | None = None
    queue_type: str | None = None
    preview_url: str | None = None


class ToolTaskQueryRequest(BaseModel):
    """按任务编号批量查询画布生成状态。"""

    ids: list[str] = Field(default_factory=list, max_length=50)


class ToolTaskQueryItem(BaseModel):
    """单条生成任务，字段对齐画布批量轮询。"""

    id: str
    status: str
    result: dict | None = None
    error: str | None = None
    user_id: str
    node_id: str = ""
    created_at: float = 0
    spec: dict = Field(default_factory=dict)
    kind: str = "image"


class ToolTaskQueryOut(BaseModel):
    data: list[ToolTaskQueryItem] = Field(default_factory=list)
    missing_ids: list[str] = Field(default_factory=list)


class ToolRunRecordOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    tool_id: str
    kind: str
    status: str
    prompt: str = ""
    preview_url: str | None = None
    urls: list[str] = Field(default_factory=list)
    task_id: str | None = None
    params: dict | None = None
    error: str | None = None
    created_at: str
    platform_task_id: int | None = None
    provider_task_id: str | None = None
    provider_name: str | None = None
    provider_status: str | None = None
    queue_type: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    billing_charged_fen: int = 0


class ToolRunListOut(BaseModel):
    items: list[ToolRunRecordOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int] = Field(default_factory=dict)
