"""Independent video, image and audio generation and task history."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from PIL import Image
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import ToolRun, User
from app.models_tasks import TaskRun
from app.models_drama import DramaAsset, DramaProject
from app.schemas_tools import ToolEstimateRequest, ToolReferenceAssetOut, ToolRunListOut, ToolRunOut, ToolRunRecordOut, ToolTaskOut, ToolTaskQueryOut, ToolTaskQueryRequest
from app.services.billing import settle_deferred_video_poll
from app.services.billing.http import http_exception_for_value_error
from app.services.studio_generation import enqueue_generation, sync_generation_record, validate_generation
from app.services.studio_tools import get_tool_run, poll_image_tool_task, poll_video_task, save_upload, update_tool_run_task
from app.services.studio_references import (
    MAX_UPLOAD_BYTES, ROLE_KIND, asset_kind_expression, parse_references,
    personal_asset_filters, reference_params, validate_reference_mode, validate_upload,
)

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get(
    "/config",
    summary="获取独立生成工具模型配置",
    description="需要登录，返回视频、图像和音频工具当前配置的默认模型。",
    response_description="工具默认模型配置",
)
async def generation_config(user: User = Depends(get_current_user)) -> dict:
    from app.config import get_settings
    settings = get_settings()
    return {"models": {"video": settings.model_video, "image": settings.model_image,
                       "audio": settings.model_audio}}


@router.get(
    "/reference-assets",
    summary="分页查询个人参考资产",
    description="需要登录，分页读取本人个人空间可用的图片、视频和音频参考资产，支持媒体类型与名称关键词筛选。",
    response_description="参考资产及分页信息",
)
async def list_reference_assets(
    kind: Literal["image", "video", "audio"] | None = None,
    q: str = Query("", max_length=200, description="参考资产名称搜索关键词"), page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(24, ge=1, le=50, description="每页返回的记录数"),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    media_kind = asset_kind_expression()
    filters = [*personal_asset_filters(user.id), media_kind.in_(["image", "video", "audio"])]
    if kind:
        filters.append(media_kind == kind)
    if q.strip():
        filters.append(DramaAsset.name.ilike(f"%{q.strip()}%"))
    query = select(DramaAsset, media_kind).join(DramaProject, DramaProject.id == DramaAsset.project_id).where(*filters)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(DramaAsset.updated_at.desc(), DramaAsset.id.desc())
                            .offset((page - 1) * page_size).limit(page_size))).all()
    return {"items": [ToolReferenceAssetOut.model_validate({**asset.__dict__, "media_kind": media}) for asset, media in rows],
            "total": total or 0, "page": page, "page_size": page_size}


@router.post(
    "/estimate",
    summary="估算独立视频生成费用",
    description="需要登录，校验视频生成参数和参考素材，按当前计费配置返回估算费用、计费模式及价格版本；不会提交生成任务。金额提供分和元两种单位。",
    response_description="生成费用估算与价格信息",
)
async def estimate_generation(
    body: ToolEstimateRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    from app.services.billing.estimates import estimate_task_fen
    from app.services.billing.settlement import billing_active
    from app.services.media_models.planning import prepare_task_media
    params = body.model_dump(exclude={"tool_id", "prompt"})
    params["references"] = parse_references(params["references"])
    try:
        validate_reference_mode(body.video_mode, params["references"])
        params.update(await reference_params(db, user, params["references"]))
        validate_generation(body.tool_id, body.prompt, params, 0, quote=True)
        payload = {**params, "tool_id": body.tool_id, "duration": int(str(body.duration).removesuffix("s")),
                   "generate_audio": params["generate_audio"]}
        task = TaskRun(domain="studio", task_type="tool_video", requested_by=user.id, payload=payload)
        await prepare_task_media(db, task)
        enabled = billing_active(user)
        estimate = await estimate_task_fen(db, task) if enabled else 0
    except ValueError as exc:
        raise http_exception_for_value_error(exc) from exc
    snapshot = task.billing_snapshot or {}
    return {"estimate_fen": estimate, "estimate_yuan": round(estimate / 100, 2), "billing_enabled": enabled,
            "billing_mode": snapshot.get("mode", "legacy"), "price_version": snapshot.get("price_version"),
            "items": [{key: value for key, value in item.items() if key != "route"} for item in snapshot.get("items", [])]}


@router.post(
    "/run",
    response_model=ToolRunOut,
    summary="提交独立媒体生成任务",
    description=(
        "需要登录，通过 multipart/form-data 提交图片、视频或音频生成参数及参考文件，校验通过后加入后台队列。"
        "单个参考文件最大 40 MB；参考素材使用 JSON references 配置。"
        "返回当前记录，生成结果通过任务查询获取。"
    ),
    response_description="已提交的工具生成记录",
)
async def run_tool(
    tool_id: str = Form(..., max_length=16, description="工具标识：t2i 文生图、i2i 图生图、i2p 商品图、ecom 电商图片、t2v 文生视频、v2v 参考视频、audio 配音"), prompt: str = Form("", max_length=7000, description="生成提示词或音频朗读文本"),
    negative: str = Form("", max_length=2000, description="反向提示词，用于描述需要避免的内容"), ratio: str = Form("", max_length=16, description="输出画面比例，按所选模型支持的值填写"),
    strength: str = Form("", max_length=16, description="图生图参考相似度：低允许较大变化，高尽量保留参考图；其他值使用中等强度"), mode: str = Form("", max_length=32, description="商品图模式，如白底图、详情长图或场景图"),
    pack: str = Form("", max_length=32, description="电商图片组合方式：主图拼接、详情排版或卖点海报"), duration: str = Form("", max_length=16, description="生成视频的时长，如 5s；支持范围取决于所选模型"),
    motion: str = Form("", max_length=16, description="视频运动幅度：弱、强，其他值使用中等运动"), voice: str = Form("narrator_calm", max_length=64, description="配音音色：narrator_calm、warm_storyteller 或 teacher_clear"),
    model_id: str = Form("", max_length=128, description="生成模型标识；留空时使用工具默认模型"), resolution: str = Form("", max_length=16, description="输出分辨率，按所选模型支持的值填写"),
    generate_audio: bool | None = Form(default=None, description="生成声音；留空按模型能力默认开启"),
    node_id: str = Form("", max_length=128, description="画布节点编号，供批量轮询按 node_id 回写"),
    video_mode: str = Form("", max_length=32, description="视频模式：text_to_video 文生视频、first_last_frame 首尾帧、omni_reference 全能参考；留空兼容旧流程"), references: str = Form("[]", max_length=8000, description="最多 12 项的 JSON 数组；每项包含 role，并且仅提供 file_index 上传文件索引或 asset_id 个人资产编号之一"),
    price_version: int | None = Form(default=None, ge=0, description="客户端确认的价格版本；传入有效版本时用于价格一致性校验"),
    files: list[UploadFile] | None = File(default=None, description="参考图片、视频或音频文件；单个文件最大 40 MB，格式由工具及素材角色决定"),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> ToolRunOut:
    tid = tool_id.strip()
    params = dict(negative=negative, ratio=ratio, strength=strength, mode=mode, pack=pack,
                  duration=duration, motion=motion, voice=voice, model_id=model_id, resolution=resolution, generate_audio=generate_audio)
    if node_id.strip():
        params["node_id"] = node_id.strip()
    saved = []
    try:
        if video_mode:
            if tid not in {"t2v", "v2v"}:
                raise ValueError("video_mode: 仅视频生成可使用此模式")
            refs = parse_references(references)
            validate_reference_mode(video_mode, refs, len(files or []))
            params.update(video_mode=video_mode, references=refs)
            params.update(await reference_params(db, user, refs))
        elif references != "[]":
            raise ValueError("references: 请先选择视频生成模式")
        if price_version:
            params["price_version"] = price_version
        validate_generation(tid, prompt, params, len(files or []))
        upload_kinds = {ref["file_index"]: ROLE_KIND[ref["role"]] for ref in params.get("references", []) if "file_index" in ref}
        for index, item in enumerate(files or []):
            raw = await item.read(MAX_UPLOAD_BYTES + 1)
            if not raw or len(raw) > MAX_UPLOAD_BYTES:
                raise ValueError("文件不能为空，且单个文件不能超过 40MB")
            name = item.filename or "upload.png"
            suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if suffix not in {"jpg", "jpeg", "png", "webp", "mp4", "mov", "webm"}:
                mime = (item.content_type or "").split(";", 1)[0].lower()
                sniffed = "png" if raw.startswith(b"\x89PNG") or mime == "image/png" else "webp" if (len(raw) >= 12 and raw[8:12] == b"WEBP") or mime == "image/webp" else "jpg" if raw.startswith(b"\xff\xd8") or mime in {"image/jpeg", "image/jpg"} else ""
                if sniffed:
                    name = f"{name}.{sniffed}"
                    suffix = sniffed
            if video_mode:
                validate_upload(raw, name, upload_kinds[index], item.content_type)
            elif suffix in {"mp4", "mov", "webm"} and tid == "v2v":
                pass
            elif suffix in {"jpg", "jpeg", "png", "webp"} and tid != "audio":
                try:
                    with Image.open(BytesIO(raw)) as image:
                        image.verify()
                except Exception as exc:
                    raise ValueError("参考图文件无效") from exc
            else:
                raise ValueError("请上传 JPG、PNG、WebP 图片，视频参考支持 MP4、MOV、WebM")
            saved.append(save_upload(user.id, raw, name))
        if video_mode:
            params.update(await reference_params(db, user, params["references"], files=saved))
        data = await enqueue_generation(db, user, tool_id=tid, prompt=prompt, params=params, files=saved, drama_project_id=db.info.get('printfilm_studio_project_id'))
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        for path in saved:
            path.unlink(missing_ok=True)
        raise http_exception_for_value_error(exc) from exc
    except Exception:
        await db.rollback()
        for path in saved:
            path.unlink(missing_ok=True)
        raise
    return ToolRunOut.model_validate(data)


def _canvas_task_status(status: str) -> str:
    """把平台状态收成画布轮询使用的 running / succeeded / failed。"""
    if status in {"pending", "leased", "queued", "running", "awaiting_poll"}:
        return "running"
    if status == "succeeded":
        return "succeeded"
    return status or "running"


def _canvas_task_item(row: ToolRun, user: User) -> dict:
    """把一条生成记录整理成批量查询项。"""
    params = row.params or {}
    status = _canvas_task_status(row.status)
    urls = [str(item) for item in (row.urls or []) if item]
    created = row.created_at.timestamp() if row.created_at else 0
    return {
        "id": row.task_id or "",
        "status": status,
        "result": {"urls": urls, "preview_url": row.preview_url} if status == "succeeded" and urls else None,
        "error": row.error,
        "user_id": str(user.id),
        "node_id": str(params.get("node_id") or ""),
        "created_at": created,
        "spec": {
            "prompt": row.prompt or "",
            "model": str(params.get("model_id") or ""),
            "size": str(params.get("ratio") or "auto"),
            "count": int(str(params.get("pack") or "1") or 1) if str(params.get("pack") or "1").isdigit() else 1,
            "references": params.get("references") if isinstance(params.get("references"), list) else [],
            "image_options": {},
            "mask": "",
        },
        "kind": row.kind or "image",
    }


@router.post(
    "/tasks/query",
    response_model=ToolTaskQueryOut,
    summary="按编号批量查询画布生成任务",
    description="需要登录。一次传入最多 50 个任务编号，返回状态、结果和所属节点；查不到的编号放在 missing_ids。",
    response_description="任务状态列表",
)
async def query_tool_tasks(body: ToolTaskQueryRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> ToolTaskQueryOut:
    wanted = []
    for raw in body.ids:
        task_id = str(raw or "").strip()
        if task_id and task_id not in wanted:
            wanted.append(task_id)
    if not wanted:
        return ToolTaskQueryOut()
    rows = list((await db.execute(
        select(ToolRun).where(ToolRun.user_id == user.id, ToolRun.task_id.in_(wanted))
    )).scalars().all())
    data = []
    found = set()
    for row in rows:
        task = await sync_generation_record(db, row)
        if task and task.result_payload and task.result_payload.get("urls") and not row.urls:
            row.urls = list(task.result_payload["urls"])
        item = _canvas_task_item(row, user)
        if item["id"]:
            found.add(item["id"])
            data.append(item)
    await db.commit()
    return ToolTaskQueryOut(data=data, missing_ids=[task_id for task_id in wanted if task_id not in found])


@router.get(
    "/tasks/{task_id}",
    response_model=ToolTaskOut,
    summary="查询独立生成任务状态",
    description="需要登录，仅可查询本人的工具任务。返回当前状态、媒体地址和错误信息；兼容旧任务时可能查询供应商并同步结算，新任务由服务端后台轮询。",
    response_description="工具任务当前状态与结果",
)
async def get_tool_task(task_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> ToolTaskOut:
    row = (await db.execute(select(ToolRun).where(ToolRun.user_id == user.id, ToolRun.task_id == task_id).limit(1))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = await sync_generation_record(db, row)
    if task:
        data = dict(status=row.status, kind=row.kind, urls=list(row.urls or []), error=row.error,
                    platform_task_id=task.id, provider_task_id=task.provider_task_id,
                    queue_type=task.queue_type, preview_url=row.preview_url)
    elif row.status in {"succeeded", "failed", "cancelled"}:
        data = dict(status=row.status, kind=row.kind, urls=list(row.urls or []), error=row.error)
    elif row.kind == "image":
        data = await poll_image_tool_task(db, user, task_id)
    else:
        # Compatibility for pre-migration provider IDs; new tasks are polled by the server.
        data = await poll_video_task(user, task_id)
        await settle_deferred_video_poll(db, user, provider_task_id=task_id, poll_status=data["status"],
            error=data.get("error"), billing_task_id=(row.params or {}).get("billing_task_id"),
            usage_tokens=int((data.get("usage") or {}).get("total_tokens") or 0),
            completion_tokens=int((data.get("usage") or {}).get("completion_tokens") or 0), raw_usage=data.get("raw_usage"))
        await update_tool_run_task(db, user.id, task_id, data)
    await db.commit()
    return ToolTaskOut.model_validate(data)


def _record_out(row: ToolRun, task: TaskRun | None = None) -> ToolRunRecordOut:
    private = {"file_paths"}
    if (row.params or {}).get("video_mode"):
        private.update({"first_frame", "last_frame", "reference_images", "reference_videos", "reference_audios"})
    params = {key: value for key, value in (row.params or {}).items() if key not in private}
    result = (task.result_payload or {}) if task else {}
    status = {"pending": "queued", "leased": "queued", "awaiting_poll": "running"}.get(task.status, task.status) if task else row.status
    return ToolRunRecordOut(
        id=row.id, tool_id=row.tool_id, kind=row.kind, status=status, prompt=row.prompt or "",
        preview_url=row.preview_url, urls=list(result.get("urls") or row.urls or []), task_id=row.task_id,
        params=params, error=task.error_message if task else row.error,
        created_at=row.created_at.isoformat() if row.created_at else "",
        platform_task_id=task.id if task else None, provider_task_id=task.provider_task_id if task else params.get("provider_task_id"),
        queue_type=task.queue_type if task else None, provider_name=task.provider_name if task else None,
        provider_status=task.provider_status if task else None,
        started_at=task.started_at if task else None, finished_at=task.finished_at if task else None,
        billing_charged_fen=task.billing_charged_fen if task else 0,
    )


@router.get(
    "/runs",
    response_model=ToolRunListOut,
    summary="分页查询独立生成历史",
    description="需要登录，分页返回本人的工具生成历史，支持媒体类型、状态、任务标识和创建时间筛选，并返回各状态数量统计。",
    response_description="工具生成记录、分页与状态统计",
)
async def list_runs(
    page: int = Query(1, ge=1, description="页码，从 1 开始"), page_size: int = Query(8, ge=1, le=50, description="每页返回的记录数"),
    kind: str | None = Query(None, pattern="^(video|image|audio)$", description="媒体类型：video 视频、image 图片、audio 音频"),
    status: str | None = Query(None, pattern="^(processing|succeeded|failed|cancelled)$", description="记录状态：processing 处理中、succeeded 成功、failed 失败、cancelled 已取消"),
    task_id: str | None = Query(None, max_length=128, description="任务标识，可匹配工具、平台或供应商任务编号"),
    q: str | None = Query(None, max_length=200, description="搜索提示词"),
    created_from: datetime | None = None, created_to: datetime | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> ToolRunListOut:
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=400, detail="开始时间不能晚于结束时间")
    task_ref = func.coalesce(ToolRun.params["platform_task_id"].as_integer(), ToolRun.params["billing_task_id"].as_integer())
    join = (TaskRun.id == task_ref) & (TaskRun.requested_by == ToolRun.user_id)
    filters = [ToolRun.user_id == user.id]
    if isinstance(q, str) and q.strip():
        filters.append(ToolRun.prompt.icontains(q.strip(), autoescape=True))
    if kind:
        filters.append(ToolRun.kind == kind)
    if task_id:
        value = task_id.strip()
        filters.append(or_(ToolRun.task_id == value, TaskRun.provider_task_id == value,
                           cast(TaskRun.id, String) == value, cast(ToolRun.id, String) == value))
    if created_from:
        filters.append(ToolRun.created_at >= created_from)
    if created_to:
        filters.append(ToolRun.created_at <= created_to)
    effective = func.coalesce(TaskRun.status, ToolRun.status)
    bucket = case((effective.in_(["succeeded", "failed", "cancelled"]), effective), else_="processing")
    counts = dict((await db.execute(select(bucket, func.count()).select_from(ToolRun).outerjoin(TaskRun, join)
                                   .where(*filters).group_by(bucket))).all())
    total = counts.get(status, 0) if status else sum(counts.values())
    if status:
        filters.append(bucket == status)
    rows = (await db.execute(select(ToolRun, TaskRun).outerjoin(TaskRun, join).where(*filters)
                            .order_by(ToolRun.id.desc()).offset((page - 1) * page_size).limit(page_size))).all()
    return ToolRunListOut(items=[_record_out(row, task) for row, task in rows], total=total,
                          page=page, page_size=page_size, counts={**counts, "all": sum(counts.values())})


@router.get(
    "/runs/{run_id}",
    response_model=ToolRunRecordOut,
    summary="获取独立生成记录详情",
    description="需要登录，仅可读取本人的工具运行记录，先同步关联平台任务状态后返回结果；记录不存在返回 404。",
    response_description="工具生成记录详情",
)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> ToolRunRecordOut:
    row = await get_tool_run(db, user.id, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    task = await sync_generation_record(db, row)
    await db.commit()
    return _record_out(row, task)
