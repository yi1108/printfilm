from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(default="默认 Key", max_length=64)


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiKeyCreatedOut(ApiKeyOut):
    secret: str


class V1ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    negative: str = Field(default="", max_length=2000)
    ratio: str = Field(default="1:1", description="1:1 | 16:9 | 9:16")
    image_url: str | None = Field(default=None, description="参考图 URL，传入则为图生图")


class V1VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    image_url: str = Field(min_length=8, description="首帧图公网 URL")
    duration: int = Field(default=5, ge=4, le=15)
    resolution: str = Field(default="480p")
    generate_audio: bool = False


class V1SeedanceTaskRequest(BaseModel):
    """接近火山 Seedance 的任务体，服务端补全 model 并转发。"""

    content: list[dict]
    duration: int | None = Field(default=None, ge=4, le=30)
    resolution: str = Field(default="480p")
    ratio: str | None = None
    generate_audio: bool = False
    return_last_frame: bool = True
    watermark: bool = False


class V1GenerationOut(BaseModel):
    status: str
    kind: str
    urls: list[str] = Field(default_factory=list)
    task_id: str | None = None
    preview_url: str | None = None
    error: str | None = None
