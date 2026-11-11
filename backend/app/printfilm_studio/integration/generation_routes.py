"""Project-scoped admission around the existing multipart generation service."""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.api.tools import run_tool, _canvas_task_item
from app.database import get_db
from app.deps import get_current_user
from app.models import User, ToolRun
from app.models_drama import DramaAsset
from app.models_tasks import TaskRun
from app.schemas_tools import ToolRunOut, ToolTaskQueryRequest
from app.printfilm_studio import ensure_enabled
from app.printfilm_studio.canvas.routes import writable_project
from app.printfilm_studio.canvas.service import get_project
from app.services.studio_generation import sync_generation_record

router = APIRouter(prefix='/printfilm-studio', tags=['printfilm-studio-generation'])


class ImageEstimateRequest(BaseModel):
    model_id: str = Field(max_length=128)
    resolution: str = Field(default='2K', max_length=16)
    ratio: str = Field(default='2:3', max_length=16)
    count: int = Field(default=1, ge=1, le=4)


@router.post('/projects/{project_id}/image/estimate')
async def estimate_image(project_id: int, body: ImageEstimateRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    await get_project(db, project_id, user)
    from app.services.billing.estimates import estimate_task_fen
    from app.services.billing.settlement import billing_active
    from app.services.media_models.planning import prepare_task_media
    from app.services.studio_generation import validate_generation
    params = {'tool_id': 't2i', 'model_id': body.model_id, 'resolution': body.resolution, 'ratio': body.ratio, 'pack': str(body.count)}
    try:
        validate_generation('t2i', '', params, 0, quote=True)
        task = TaskRun(domain='studio', task_type='tool_image', requested_by=user.id, payload=params)
        await prepare_task_media(db, task)
        enabled = billing_active(user)
        estimate = await estimate_task_fen(db, task) if enabled else 0
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'estimate_fen': estimate, 'estimate_yuan': round(estimate / 100, 2), 'billing_enabled': enabled}


@router.get('/projects/{project_id}/audio/estimate')
async def estimate_audio(project_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    await get_project(db, project_id, user)
    from app.services.billing.estimates import estimate_task_fen
    from app.services.billing.settlement import billing_active
    enabled = billing_active(user)
    task = TaskRun(domain='studio', task_type='tool_audio', requested_by=user.id, payload={})
    estimate = await estimate_task_fen(db, task) if enabled else 0
    return {'estimate_fen': estimate, 'estimate_yuan': round(estimate / 100, 2), 'billing_enabled': enabled}


async def admit_generation(project=Depends(writable_project), db: AsyncSession = Depends(get_db), edit_session_id: str | None = Header(default=None, alias='X-Edit-Session'), edit_lock_token: str | None = Header(default=None, alias='X-Edit-Token'), edit_lock_version: int | None = Header(default=None, alias='X-Edit-Version')):
    db.info['printfilm_studio_project_id'] = project.id


# Route dependencies run before multipart submission, so denial cannot create a task.
router.add_api_route('/projects/{project_id}/generations', run_tool, methods=['POST'], response_model=ToolRunOut, dependencies=[Depends(admit_generation)])


@router.post('/projects/{project_id}/generations/{task_id}/cancel')
async def cancel_generation(task_id: str, project=Depends(writable_project), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.api.tasks import cancel_task_run
    task = await db.scalar(select(TaskRun).join(ToolRun, TaskRun.id == ToolRun.params['platform_task_id'].as_integer()).where(ToolRun.task_id == task_id, TaskRun.drama_project_id == project.id).with_for_update(of=TaskRun))
    if not task:
        raise HTTPException(404, '当前项目中未找到此生成任务')
    if task.requested_by != user.id:
        raise HTTPException(403, '只能取消由自己发起的生成任务')
    if task.status != 'pending':
        raise HTTPException(409, '任务已开始执行，当前模型不支持中途取消')
    task.cancelable = True
    await cancel_task_run(task.id, db, user)
    return {'ok': True, 'message': '已请求取消，等待服务确认'}


async def materialize_results(db, project_id, task, row):
    """Caller holds the task row lock; repeated polling creates no duplicate assets."""
    if task.status != 'succeeded':
        return None
    urls = list((task.result_payload or {}).get('urls') or row.urls or [])[:16]
    first = None
    for index, url in enumerate(urls):
        asset = await db.scalar(select(DramaAsset).where(DramaAsset.project_id == project_id, DramaAsset.params['studio_task_id'].as_integer() == task.id, DramaAsset.params['output_index'].as_integer() == index))
        if asset is None:
            asset = DramaAsset(project_id=project_id, name=(row.prompt or '生成素材')[:100], type='material', asset_type=row.kind, url=url, cover=url if row.kind == 'image' else None, params={'studio_task_id': task.id, 'output_index': index, 'source': 'generation', 'prompt': row.prompt})
            db.add(asset)
            await db.flush()
        if index == 0:
            first = asset.id
    return first


@router.post('/projects/{project_id}/tasks/query')
async def project_tasks(project_id: int, body: ToolTaskQueryRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    await get_project(db, project_id, user)
    task_ref = ToolRun.params['platform_task_id'].as_integer()
    # Old unscoped Studio tasks remain readable only to their original user.
    rows = (await db.execute(select(ToolRun, TaskRun).join(TaskRun, TaskRun.id == task_ref).where(ToolRun.task_id.in_(body.ids), or_(TaskRun.drama_project_id == project_id, and_(TaskRun.drama_project_id.is_(None), ToolRun.user_id == user.id))).with_for_update(of=TaskRun))).all()
    result = []
    for row, task in rows:
        await sync_generation_record(db, row)
        asset_id = await materialize_results(db, project_id, task, row)
        result.append({**_canvas_task_item(row, user), 'user_id': str(row.user_id), 'asset_id': asset_id, 'can_cancel': task.status == 'pending' and task.requested_by == user.id, 'generation_stage': 'transferring' if task.provider_status == 'transferring' else 'queued' if task.status == 'pending' or task.provider_status == 'queued' else 'generating'})
    await db.commit()
    found = {item['id'] for item in result}
    return {'data': result, 'missing_ids': [item for item in body.ids if item not in found]}
