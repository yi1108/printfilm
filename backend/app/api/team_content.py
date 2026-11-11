"""团队项目列表、个人项目迁入与团队资产副本接口。"""
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas_drama import DramaAssetOut, DramaProjectCreate, DramaProjectOut
from app.services.drama.asset_reference_views import asset_reference_view
from app.services.teams import content

router = APIRouter(prefix="/teams/{team_id}", tags=["team-content"])
personal_router = APIRouter(prefix="/drama", tags=["drama-assets"])


class TeamProjectCreate(BaseModel):
    """真实项目创意由用户提供，不以占位文本冒充。"""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=512)
    source: str = Field(min_length=20, max_length=100000)
    episode_count: int = Field(default=1, strict=True, ge=1, le=120, description="初始集数，支持 1 至 120 集，后续可在项目中增加分集")
    workflow: Literal["script", "canvas"] = "script"


class TeamAssetCopy(BaseModel):
    """只接收目标项目，源内容和来源标记完全由数据库取得。"""
    model_config = ConfigDict(extra="forbid")
    project_id: int = Field(strict=True, gt=0)


@router.get(
    "/projects",
    summary="分页查询团队漫剧项目",
    description="需要登录且为团队有效成员，按标题或描述关键词、项目状态筛选当前团队项目，返回项目卡片、协作者、编辑占用和分页信息。",
    response_description="团队项目卡片及分页信息",
)
async def list_projects(team_id: int, page: int = Query(1, ge=1, description="页码，从 1 开始"), page_size: int = Query(20, ge=1, le=100, description="每页返回的记录数"), q: str = Query("", max_length=200, description="项目标题或描述搜索关键词"), status: Literal["draft", "producing", "completed"] | None = None, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """需要登录且为团队有效成员，按标题或描述关键词、项目状态筛选当前团队项目，返回项目卡片、协作者、编辑占用和分页信息。"""
    return await content.list_projects(db, team_id, user.id, page, page_size, q, status)


@router.get(
    "/assets",
    summary="分页查询团队资产",
    description="需要登录且为团队有效成员，分页查询本团队可访问项目中的角色、场景、道具和音色，支持名称、资产类型及项目筛选。",
    response_description="团队资产及分页信息",
)
async def list_assets(team_id: int, page: int = Query(1, ge=1, description="页码，从 1 开始"), page_size: int = Query(20, ge=1, le=100, description="每页返回的记录数"), q: str = Query("", max_length=200, description="资产名称搜索关键词"), type: Literal["character", "scene", "prop", "voice"] | None = None, project_id: int | None = Query(None, gt=0, description="项目编号"), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """需要登录且为团队有效成员，分页查询本团队可访问项目中的角色、场景、道具和音色，支持名称、资产类型及项目筛选。"""
    return await content.list_assets(db, team_id, user.id, page, page_size, q, type, project_id)


@router.post(
    "/projects",
    response_model=DramaProjectOut,
    status_code=201,
    summary="创建团队漫剧项目",
    description="需要登录且为团队有效成员，根据用户提供的真实创意创建绑定团队的漫剧项目，支持剧本或画布工作流。创建时不自动提交收费生成任务。",
    response_description="新建团队漫剧项目",
)
async def create_project(team_id: int, body: TeamProjectCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> DramaProjectOut:
    """需要登录且为团队有效成员，根据用户提供的真实创意创建绑定团队的漫剧项目，支持剧本或画布工作流。创建时不自动提交收费生成任务。"""
    from app.api.drama.projects import create_project as create_drama_project
    return await create_drama_project(DramaProjectCreate(team_id=team_id, **body.model_dump()), db=db, user=user, scope_team_id=team_id)


@router.get(
    "/transferable-projects",
    summary="查询可迁入团队的个人项目",
    description="需要登录且为团队有效成员，分页列出本人的个人漫剧项目及可迁入标志；存在生成任务或编辑占用时返回不可迁入原因。",
    response_description="个人项目及迁入可用性",
)
async def transferable_projects(team_id: int, page: int = Query(1, ge=1, description="页码，从 1 开始"), page_size: int = Query(20, ge=1, le=100, description="每页返回的记录数"), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """需要登录且为团队有效成员，分页列出本人的个人漫剧项目及可迁入标志；存在生成任务或编辑占用时返回不可迁入原因。"""
    return await content.transferable_projects(db, team_id, user.id, page, page_size)


@router.post(
    "/projects/{project_id}/transfer",
    response_model=DramaProjectOut,
    summary="迁入个人漫剧项目",
    description=(
        "需要登录且为团队有效成员，将本人无活动任务、无有效编辑占用的个人项目整体迁入指定团队。"
        "保留项目编号与历史计费归属；已在同一团队时可重复请求，其他团队项目不可迁入。"
    ),
    response_description="迁入后的漫剧项目详情",
)
async def transfer_project(team_id: int, project_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> DramaProjectOut:
    """需要登录且为团队有效成员，将本人无活动任务、无有效编辑占用的个人项目整体迁入指定团队。保留项目编号与历史计费归属；已在同一团队时可重复请求，其他团队项目不可迁入。"""
    from app.api.drama.projects import get_project
    project, copier = await content.transfer_project(db, team_id, user.id, project_id)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        if copier:
            copier.cleanup()
        raise
    return await get_project(project.id, db=db, user=user)


@router.post(
    "/assets/{asset_id}/copy",
    response_model=DramaAssetOut,
    status_code=201,
    summary="复制团队资产到项目",
    description=(
        "需要登录且为团队有效成员，源资产和目标项目必须属于当前团队。"
        "需提供目标项目 asset:0 的编辑租约请求头 X-Edit-Session、X-Edit-Token、X-Edit-Version，创建资产和媒体的独立副本，保留来源标记。"
    ),
    response_description="新建的独立资产副本",
)
async def copy_asset(team_id: int, asset_id: int, body: TeamAssetCopy, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> DramaAssetOut:
    """需要登录且为团队有效成员，源资产和目标项目必须属于当前团队。需提供目标项目 asset:0 的编辑租约请求头 X-Edit-Session、X-Edit-Token、X-Edit-Version，创建资产和媒体的独立副本，保留来源标记。"""
    from fastapi import HTTPException
    try:
        version = int(request.headers.get("X-Edit-Version", "0"))
    except ValueError as exc:
        raise HTTPException(422, "无效的编辑版本") from exc
    asset, copier = await content.copy_asset(db, team_id, user.id, asset_id, body.project_id, request.headers.get("X-Edit-Session", ""), request.headers.get("X-Edit-Token", ""), version)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        copier.cleanup()
        raise
    return await asset_reference_view(db, asset, user_id=user.id)


@personal_router.post(
    "/assets/{asset_id}/copy",
    response_model=DramaAssetOut,
    status_code=201,
    summary="复制个人空间资产",
    description=(
        "需要登录，将可访问资产复制到指定目标项目。个人空间只允许复制本人的资产；"
        "目标为团队项目时，源目标必须同队且需提供目标 asset:0 的 X-Edit-Session、X-Edit-Token、X-Edit-Version 租约请求头。"
    ),
    response_description="新建的独立资产副本",
)
async def copy_owned_asset(asset_id: int, body: TeamAssetCopy, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> DramaAssetOut:
    """需要登录，将可访问资产复制到指定目标项目。个人空间只允许复制本人的资产；目标为团队项目时，源目标必须同队且需提供目标 asset:0 的 X-Edit-Session、X-Edit-Token、X-Edit-Version 租约请求头。"""
    from fastapi import HTTPException
    from app.models_drama import DramaProject

    target = await db.get(DramaProject, body.project_id)
    if not target:
        raise HTTPException(404, "目标项目不存在")
    if target.user_id != user.id or target.team_id is not None:
        raise HTTPException(404, "目标项目不存在")
    return await copy_asset(None, asset_id, body, request, db=db, user=user)
