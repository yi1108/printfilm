"""对外 REST API：生图 / 生视频 / Seedance 转发。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_api_user
from app.models import User
from app.schemas_api import (
    V1GenerationOut,
    V1ImageGenerateRequest,
    V1SeedanceTaskRequest,
    V1VideoGenerateRequest,
)
from app.services.ark import get_ark
from app.services.billing import (
    run_billed_ephemeral,
    run_billed_ephemeral_deferred,
    settle_deferred_video_poll,
)
from app.services.drama.billing_util import record_seedream_image_usage
from app.services.studio_tools import poll_video_task, ratio_to_size
from app.services import storage

router = APIRouter(prefix="/v1", tags=["public-api"])


async def _resolve_api_user(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> User:
    from fastapi.security import HTTPAuthorizationCredentials

    creds = None
    if authorization and authorization.lower().startswith("bearer "):
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=authorization[7:].strip())
    return await get_api_user(creds=creds, db=db, x_api_key=x_api_key)


@router.post("/images/generations", response_model=V1GenerationOut)
async def generate_image(
    body: V1ImageGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_resolve_api_user),
) -> V1GenerationOut:
    """文生图 / 图生图（Seedream）。"""

    async def _exec() -> str:
        ark = get_ark()
        refs: list[str] | None = None
        prompt = body.prompt.strip()
        if body.image_url:
            refs = [body.image_url.strip()]
            prompt = f"{prompt}。在保持主体可识别的前提下适度改变风格"
        size = ratio_to_size(body.ratio)
        try:
            result = await ark.gen_image(
                prompt,
                body.negative,
                refs,
                project_id=0,
                shot_no=user.id,
                size=size,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)[:400]) from exc

        await record_seedream_image_usage(
            db,
            user_id=user.id,
            model=get_settings().model_image,
            domain="api",
            image_result=result,
            extra_raw={"source": "api_v1_image"},
        )
        url = result.local_url or result.remote_url or ""
        if url:
            url = storage.republish_url(url, sync=True) or url
        return url

    try:
        task, url = await run_billed_ephemeral(
            db,
            user,
            domain="api",
            task_type="v1_image",
            executor=_exec,
            payload={"prompt_len": len(body.prompt or "")},
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    return V1GenerationOut(
        status="succeeded",
        kind="image",
        urls=[url] if url else [],
        task_id=str(task.id),
    )


@router.post("/videos/generations", response_model=V1GenerationOut)
async def generate_video(
    body: V1VideoGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_resolve_api_user),
) -> V1GenerationOut:
    """首帧图 + 文案 → Seedance 图生视频，返回 task_id。"""

    async def _exec() -> str:
        ark = get_ark()
        try:
            upstream_id = await ark.gen_video_i2v(
                body.image_url.strip(),
                body.prompt.strip(),
                body.duration,
                resolution=body.resolution,
                generate_audio=body.generate_audio,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)[:400]) from exc

        return upstream_id

    try:
        task, upstream_id = await run_billed_ephemeral_deferred(
            db,
            user,
            domain="api",
            task_type="v1_video",
            executor=_exec,
            payload={"duration": body.duration},
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    return V1GenerationOut(
        status="queued",
        kind="video",
        task_id=upstream_id,
        preview_url=body.image_url,
        urls=[],
    )


@router.post("/seedance/tasks", response_model=V1GenerationOut)
async def forward_seedance(
    body: V1SeedanceTaskRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_resolve_api_user),
) -> V1GenerationOut:
    """转发 Seedance 多模态 body 到火山方舟。"""
    if not body.content:
        raise HTTPException(status_code=400, detail="content 不能为空")
    settings = get_settings()
    payload: dict = {
        "model": settings.model_video,
        "content": body.content,
        "resolution": body.resolution,
        "watermark": body.watermark,
        "generate_audio": body.generate_audio,
        "return_last_frame": body.return_last_frame,
    }
    if body.duration is not None:
        payload["duration"] = body.duration
    if body.ratio:
        payload["ratio"] = body.ratio

    async def _exec() -> str:
        ark = get_ark()
        try:
            upstream_id = await ark.gen_video_seedance_body(payload, project_id=0)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)[:400]) from exc

        return upstream_id

    try:
        task, upstream_id = await run_billed_ephemeral_deferred(
            db,
            user,
            domain="api",
            task_type="v1_seedance",
            executor=_exec,
            payload={"duration": body.duration},
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    return V1GenerationOut(status="queued", kind="video", task_id=upstream_id, urls=[])


@router.get("/tasks/{task_id}", response_model=V1GenerationOut)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_resolve_api_user),
) -> V1GenerationOut:
    """查询 Seedance 视频任务状态。"""
    if not task_id.strip():
        raise HTTPException(status_code=400, detail="缺少 task_id")
    tid = task_id.strip()
    data = await poll_video_task(user, tid)
    await settle_deferred_video_poll(
        db,
        user,
        provider_task_id=tid,
        poll_status=str(data.get("status") or ""),
        error=str(data.get("error") or "") or None,
        usage_tokens=int((data.get("usage") or {}).get("total_tokens") or 0),
        completion_tokens=int((data.get("usage") or {}).get("completion_tokens") or 0),
        raw_usage=data.get("raw_usage") if isinstance(data.get("raw_usage"), dict) else None,
    )
    await db.commit()
    return V1GenerationOut(
        status=str(data.get("status") or "running"),
        kind="video",
        urls=list(data.get("urls") or []),
        task_id=task_id.strip(),
        error=data.get("error"),
    )
