"""独立创作工具请求 / 响应。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolRunOut(BaseModel):
    kind: str = Field(description="image | video | images")
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


class ToolRunListOut(BaseModel):
    items: list[ToolRunRecordOut]
    total: int
    page: int
    page_size: int
