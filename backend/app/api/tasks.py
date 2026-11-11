"""Unified task platform API: /api/tasks/*."""

from __future__ import annotations
import asyncio
import re
from datetime import datetime

from app.config import get_settings
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas_tasks import MockDelayTaskRequest, TaskCreateRequest, TaskListOut, TaskRunOut
from app.schemas_generation_history import GenerationListOut, GenerationRecordOut
from app.services.tasks.generation_history import get_generation, list_generations
from app.services.billing.http import http_exception_for_value_error
from app.services.tasks.service import (
    TaskAccessContext,
    cancel_task_for_user,
    count_active_tasks_for_user,
    create_task,
    get_task_for_user,
    list_tasks_for_user,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
_mock_delay_create_lock = asyncio.Lock()


_MONEY_KEYS = frozenset({"billing", "ledger", "money", "cost", "price", "charge", "charged", "refund", "refunded", "amount", "balance", "frozen", "spent", "reserved", "budget", "fee", "quota"})
_MONEY_MESSAGE = re.compile(r"[¥￥]|\b(?:charge|charged|cost|refund|amount|billing|balance|quota)\b|余额|费用|金额|扣费|退款|额度", re.IGNORECASE)


def _without_money(value):
    """Remove nested monetary metadata without mutating persisted lifecycle events."""
    if isinstance(value, dict):
        return {
            key: _without_money(item)
            for key, item in value.items()
            if not (
                bool(set(re.sub(r"([a-z])([A-Z])", r"\1_\2", str(key)).lower().split("_")) & _MONEY_KEYS)
                or str(key).lower().endswith(("_fen", "_yuan", "_cents"))
                or str(key).lower().startswith("billing_")
            )
        }
    if isinstance(value, list):
        return [_without_money(item) for item in value]
    return value


def _owner_id(task, viewer: User, context: TaskAccessContext) -> int | None:
    access = context.get((task.team_id, int(viewer.id))) if task.team_id is not None else None
    return int(access[0].owner_user_id) if access is not None else None


def public_task(task, *, viewer: User | None = None, owner_user_id: int | None = None) -> TaskRunOut:
    """Team collaborators receive progress and results without internal upstream traces."""
    output = TaskRunOut.model_validate(task)
    if output.team_id is not None:
        output.events = [event for event in output.events if not event.event_type.startswith("upstream.")]
        output.lease_token = None
        for step in output.steps:
            step.input_payload = None
            step.output_payload = None
        can_view_money = viewer is not None and (
            int(viewer.id) == output.requested_by or int(viewer.id) == owner_user_id
        )
        if not can_view_money:
            output.billing_estimate_fen = None
            output.billing_charged_fen = None
            output.billing_refunded_fen = None
            for event in output.events:
                event.payload = _without_money(event.payload)
                if event.message and _MONEY_MESSAGE.search(event.message):
                    event.message = "任务状态已更新"
    return output


# 创建一个延时完成的模拟任务，便于联调任务平台。
@router.post(
    "/mock-delay",
    response_model=TaskRunOut,
    summary="创建模拟延时任务",
    description=(
        "需要登录，仅在模拟模式或管理员身份下可用，否则返回 404。"
        "创建由后台延时完成的测试任务，每个用户最多同时存在 3 个活动模拟任务，超出返回 429。"
    ),
    response_description="新建模拟任务的当前状态",
)
async def create_mock_delay_task(
    body: MockDelayTaskRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskRunOut:
    settings = get_settings()
    if not settings.ark_mock and str(user.role or "") != "admin":
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        async with _mock_delay_create_lock:
            active_count = await count_active_tasks_for_user(
                db,
                user,
                domain="tools",
                task_type="mock_delay",
            )
            if active_count >= 3:
                raise HTTPException(status_code=429, detail="模拟延时任务最多同时运行 3 个")
            task = await create_task(
                db,
                user,
                TaskCreateRequest(
                    domain="tools",
                    task_type="mock_delay",
                    dedupe_key=body.dedupe_key,
                    payload={
                        "delay_seconds": body.delay_seconds,
                        "succeed": body.succeed,
                        "result_payload": body.result_payload,
                        "error_message": body.error_message,
                    },
                ),
            )
    except ValueError as exc:
        raise http_exception_for_value_error(exc) from exc
    return public_task(task, viewer=user)


def _generation_workspace(team_id: int | None, workspace_team_id: int | None) -> int | None:
    if team_id is not None or workspace_team_id is not None:
        raise HTTPException(status_code=410, detail="独立团队已停用，请按画布项目查看生成记录")
    return None


@router.get(
    "/generations",
    response_model=GenerationListOut,
    summary="分页查询生成记录",
    description=(
        "需要登录，按媒体类型、状态、任务标识和创建时间查询生成历史。"
        "可通过 team_id 或 X-Team-Id 选择团队空间，两者同时传入必须一致；"
        "团队数据按访问权限返回。"
    ),
    response_description="生成记录与分页统计",
)
async def list_generation_history(
    page: int = Query(1, ge=1, description="页码，从 1 开始"), page_size: int = Query(20, ge=1, le=100, description="每页返回的记录数"),
    kind: str | None = Query(None, pattern="^(video|image|audio|text)$", description="生成内容类型：video 视频、image 图片、audio 音频、text 文本"),
    status: str | None = Query(None, pattern="^(processing|succeeded|failed|cancelled)$", description="记录状态：processing 处理中、succeeded 成功、failed 失败、cancelled 已取消"),
    task_id: str | None = Query(None, max_length=128, description="任务标识，可匹配工具、平台或供应商任务编号"),
    created_from: datetime | None = None, created_to: datetime | None = None,
    team_id: int | None = Query(None, ge=1, description="团队空间编号；不传时使用个人空间"),
    workspace_team_id: int | None = Header(None, alias="X-Team-Id", ge=1, description="团队空间编号；与查询参数 team_id 同时传入时必须一致"),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> GenerationListOut:
    if created_from and created_to:
        from datetime import UTC
        start = created_from.replace(tzinfo=UTC) if created_from.tzinfo is None else created_from
        end = created_to.replace(tzinfo=UTC) if created_to.tzinfo is None else created_to
        if start > end:
            raise HTTPException(status_code=400, detail="开始时间不能晚于结束时间")
    return await list_generations(db, user, page=page, page_size=page_size, kind=kind, status=status,
        task_id=task_id, created_from=created_from, created_to=created_to,
        team_id=_generation_workspace(team_id, workspace_team_id))


@router.get(
    "/generations/{task_id}",
    response_model=GenerationRecordOut,
    summary="获取生成记录详情",
    description=(
        "需要登录，按平台任务编号获取可访问的生成记录。可通过 team_id 或 X-Team-Id 选择团队空间，两者同时传入必须一致；"
        "不存在或无权访问时返回 404。"
    ),
    response_description="生成记录详情",
)
async def get_generation_history(
    task_id: int, team_id: int | None = Query(None, ge=1, description="团队空间编号；不传时使用个人空间"),
    workspace_team_id: int | None = Header(None, alias="X-Team-Id", ge=1, description="团队空间编号；与查询参数 team_id 同时传入时必须一致"),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> GenerationRecordOut:
    try:
        return await get_generation(db, user, task_id, team_id=_generation_workspace(team_id, workspace_team_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


# 查询单个任务详情（含 steps/targets/events）
@router.get(
    "/{task_id}",
    response_model=TaskRunOut,
    summary="获取统一任务详情",
    description=(
        "需要登录，返回可访问任务的状态、步骤、目标和事件。"
        "团队任务会隐藏上游内部事件及租约凭证，费用信息仅对任务发起人或团队所有者可见；"
        "不可访问任务返回 404。"
    ),
    response_description="按访问权限裁剪后的任务详情",
)
async def get_task_run(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskRunOut:
    access: TaskAccessContext = {}
    try:
        task = await get_task_for_user(db, user, task_id, access_context=access)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return public_task(task, viewer=user, owner_user_id=_owner_id(task, user, access))


# 当前用户的统一任务列表，支持 domain/target/project 维度筛选
@router.get(
    "",
    response_model=TaskListOut,
    summary="分页查询统一任务",
    description=(
        "需要登录，支持业务域、任务状态、任务类型、队列、目标及项目筛选。"
        "可通过 team_id 或 X-Team-Id 选择团队空间，两者同时传入必须一致；"
        "团队任务按权限隐藏内部和财务信息。"
    ),
    response_description="任务列表与分页信息",
)
async def list_task_runs(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页返回的记录数"),
    domain: str | None = Query(default=None, description="任务所属业务域，例如 kepu、drama 或 studio"),
    status: str | None = Query(default=None, description="平台任务状态，例如 pending、running、succeeded、failed、cancelled"),
    task_type: str | None = Query(default=None, description="任务类型标识"),
    queue_type: str | None = Query(default=None, pattern="^(text|image|video)$", description="任务队列类型：text 文本、image 图片、video 视频"),
    target_type: str | None = Query(default=None, description="任务关联的目标资源类型"),
    target_id: int | None = Query(default=None, ge=1, description="任务关联的目标资源编号"),
    project_id: int | None = Query(default=None, ge=1, description="项目编号"),
    drama_project_id: int | None = Query(default=None, ge=1, description="漫剧项目编号"),
    team_id: int | None = Query(default=None, ge=1, description="团队空间编号；不传时使用个人空间"),
    workspace_team_id: int | None = Header(default=None, alias="X-Team-Id", ge=1, description="团队空间编号；与查询参数 team_id 同时传入时必须一致"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskListOut:
    selected_team_id = _generation_workspace(team_id, workspace_team_id)
    access: TaskAccessContext = {}
    rows, total = await list_tasks_for_user(
        db,
        user,
        page=page,
        page_size=page_size,
        domain=domain,
        status=status,
        task_type=task_type,
        queue_type=queue_type,
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        drama_project_id=drama_project_id,
        team_id=selected_team_id,
        access_context=access,
    )
    return TaskListOut(
        items=[public_task(item, viewer=user, owner_user_id=_owner_id(item, user, access)) for item in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# 统一取消入口：标记 cancel_requested 并等待运行时协作收敛
@router.post(
    "/{task_id}/cancel",
    response_model=TaskRunOut,
    summary="请求取消统一任务",
    description=(
        "需要登录，对有权限操作的任务标记取消请求，后台运行时协作终止；"
        "返回任务当前状态，不能视为任务已经结束。任务不存在或不可访问返回 404。"
    ),
    response_description="取消请求后的任务详情",
)
async def cancel_task_run(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskRunOut:
    access: TaskAccessContext = {}
    try:
        task = await cancel_task_for_user(db, user, task_id, access_context=access)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise http_exception_for_value_error(exc) from exc
    return public_task(task, viewer=user, owner_user_id=_owner_id(task, user, access))




