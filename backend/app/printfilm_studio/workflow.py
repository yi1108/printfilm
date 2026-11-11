"""Server-owned dependency execution. Closing an HTTP subscriber never cancels work."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from copy import deepcopy

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.database import AsyncSessionLocal, get_db
from app.deps import get_current_user
from app.models import ToolRun, User
from app.models_tasks import TaskRun
from app.models_printfilm_studio import PrintfilmStudioWorkflowRun as Run, PrintfilmStudioCanvasDocument as Document
from app.printfilm_studio.canvas.routes import writable_project, _response
from app.printfilm_studio.canvas.service import get_or_create, get_project, save

router = APIRouter(prefix='/printfilm-studio', tags=['printfilm-studio-workflow'])
workers: set[asyncio.Task] = set()
logger = logging.getLogger(__name__)
BUSY = {'queued', 'running', 'awaiting_composite'}
from app.printfilm_studio.writing_context import output_settings, parameters_changed

TEXT = {'text', 'script'}
MEDIA = {'character', 'scene', 'image', 'imageGeneration', 'video', 'videoGeneration'}


def ready(node):
    data = node.get('data', {})
    if data.get('status') in BUSY | {'failed', 'cancelled', 'error'}:
        return False
    return bool(str(data.get('text') or '').strip()) if node.get('type') in TEXT else bool(data.get('mediaUrl') or data.get('url') or data.get('mediaUrls'))


def plan_nodes(document, targets, settings=None, *, text_only=False):
    by_id = {n['id']: n for n in document['nodes']}
    if text_only:
        chosen = [by_id.get(identity) for identity in dict.fromkeys(targets)]
        if any(not node or node.get('type') not in TEXT for node in chosen):
            raise ValueError('单独写作只支持文本节点')
        if any(node['data'].get('status') in BUSY for node in chosen):
            raise ValueError('文本节点正在运行，请等待完成')
        return chosen
    visited, visiting, plan = set(), set(), []
    def visit(identity):
        if identity in visiting:
            raise ValueError('依赖连线存在循环')
        if identity in visited:
            return
        node = by_id.get(identity)
        if not node:
            raise ValueError('依赖节点不存在')
        visited.add(identity)
        stale = node.get('type') in TEXT and parameters_changed(node, output_settings(node, document, settings or {}))
        if ready(node) and not stale:
            return
        if node.get('type') not in TEXT | MEDIA:
            raise ValueError('该节点不支持生成')
        visiting.add(identity)
        incoming = {e['source'] for e in document['edges'] if e['target'] == identity}
        declared = set(node['data'].get('referenceNodeIds') or [])
        if node['data'].get('promptNodeId'):
            declared.add(node['data']['promptNodeId'])
        if not declared.issubset(incoming):
            raise ValueError('节点缺少提示词或参考素材连线')
        if node['data'].get('status') not in BUSY:
            for upstream in sorted(incoming):
                visit(upstream)
        visiting.remove(identity)
        plan.append(node)
    for target in targets:
        visit(target)
    return plan


def params_for(node, settings):
    from app.printfilm_studio.media_defaults import media_ratio
    data = node['data']
    video = node.get('type') in {'video', 'videoGeneration'}
    kind = 'text' if node.get('type') in TEXT else 'video' if video else 'image'
    from app.services.media_model_presets import current_model_selection
    if kind == 'text':
        return kind, {'model_id': current_model_selection(kind, data.get('writingModel') or settings.get('textModel'), settings.get('textModel')) or None}
    return kind, {'model_id': current_model_selection(kind, data.get('modelId') or settings.get(f'{kind}Model')) or None,
                  'resolution': data.get('resolution') or settings.get(f'{kind}Resolution'),
                  'ratio': media_ratio(kind, data.get('ratio') or settings.get(f'{kind}Ratio')),
                  **({'generate_audio': data.get('generateAudio'), 'duration': str(data.get('duration') or settings.get('duration') or '5')} if video else {'count': 1})}


async def estimate_node(db, user, project_id, node, document, settings):
    kind, params = params_for(node, settings)
    if kind == 'text':
        from app.services.billing.settlement import billing_active
        from app.services.logical_model_router import resolve_logical_model
        if params['model_id']:
            resolve_logical_model('text', params['model_id'])
        return 0.05 if billing_active(user) else 0.0
    if kind == 'image':
        from app.printfilm_studio.integration.generation_routes import estimate_image, ImageEstimateRequest
        result = await estimate_image(project_id, ImageEstimateRequest(**params), db, user)
    else:
        from app.api.tools import estimate_generation
        from app.schemas_tools import ToolEstimateRequest
        incoming = {e['source'] for e in document['edges'] if e['target'] == node['id']}
        refs = [n for n in document['nodes'] if n['id'] in incoming and n.get('type') in {'character', 'scene', 'image', 'imageGeneration'}]
        result = await estimate_generation(ToolEstimateRequest(**params, video_mode='omni_reference' if refs else 'text_to_video', references=[{'file_index': i, 'role': 'reference_image'} for i in range(len(refs))]), db, user)
    return result['estimate_yuan']


class QuoteRequest(BaseModel):
    target_ids: list[str] = Field(min_length=1, max_length=200)
    settings: dict = Field(default_factory=dict)
    expected_version: int = Field(ge=1)
    text_only: bool = False


@router.post('/projects/{project_id}/workflow/quote')
async def quote_workflow(body: QuoteRequest, project=Depends(writable_project), db=Depends(get_db), user=Depends(get_current_user)):
    row = await get_or_create(db, project, user)
    if row.document_version != body.expected_version:
        raise HTTPException(409, '画布已变化，请重新加载后运行')
    try:
        nodes = plan_nodes(row.document, body.target_ids, body.settings, text_only=body.text_only)
        if not nodes:
            raise ValueError('节点已有有效结果，无需重复运行')
        items = []
        for node in nodes:
            if node['data'].get('status') in BUSY:
                continue
            if node.get('type') in TEXT and not str(node['data'].get('writingPrompt') or '').strip():
                raise ValueError(f'请先填写「{node["data"].get("label", "文本")}」的写作要求')
            if node.get('type') in TEXT:
                from app.printfilm_studio.agent.director_skills import director_skill_ids
                bindings = output_settings(node, row.document, body.settings)
                task = 'video_prompt' if any(item['kind']=='video' for item in bindings) else 'asset_plan' if bindings else 'script_write'
                await director_skill_ids(db, user.id, task, node['data'].get('writingDirectorSkillIds'))
            kind, params = params_for(node, body.settings)
            yuan = await estimate_node(db, user, project.id, node, row.document, body.settings)
            items.append({'input': {'id': node['id'], 'label': node['data'].get('label', node['id']), 'kind': kind, 'model': params['model_id']}, 'yuan': yuan})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    total = round(sum(item['yuan'] for item in items), 2)
    run = Run(project_id=project.id, user_id=user.id, plan={'ids': [n['id'] for n in nodes], 'settings': body.settings, 'items': items, 'total': total, 'version': row.document_version, 'text_only': body.text_only})
    db.add(run)
    await db.commit()
    return {'runId': run.id, 'items': items, 'total': total, 'settings': body.settings, 'planIds': run.plan['ids']}


@router.post('/projects/{project_id}/workflow/{run_id}/start')
async def start_workflow(run_id: str, project=Depends(writable_project), db=Depends(get_db), user=Depends(get_current_user), edit_session_id: str | None = Header(default=None, alias='X-Edit-Session'), edit_lock_token: str | None = Header(default=None, alias='X-Edit-Token'), edit_lock_version: int | None = Header(default=None, alias='X-Edit-Version')):
    from app.printfilm_studio.sharing import project_for
    await project_for(db, project.id, user, lock=True)
    # Serialize admissions for a project, including duplicate clicks in other tabs.
    row = await db.scalar(select(Document).where(Document.project_id == project.id).with_for_update())
    run = await db.get(Run, run_id)
    if not run or run.project_id != project.id or run.user_id != user.id:
        raise HTTPException(404, '运行记录不存在')
    if run.status != 'quoted':
        return {'id': run.id, 'status': run.status}
    if await db.scalar(select(Run.id).where(Run.project_id == project.id, Run.status == 'running')):
        raise HTTPException(409, '当前画布已有后台运行，请等待完成')
    if not row or row.document_version != run.plan['version']:
        raise HTTPException(409, '画布已变化，请重新确认费用')
    for item in run.plan['items']:
        node = next(n for n in row.document['nodes'] if n['id'] == item['input']['id'])
        if await estimate_node(db, user, project.id, node, row.document, run.plan['settings']) > item['yuan']:
            raise HTTPException(409, '模型价格已变化，请重新确认费用')
    from app.services.billing.settlement import billing_active, pending_task_commitment_fen
    required = round(run.plan['total'] * 100)
    if billing_active(user):
        wallet = await db.scalar(select(User).where(User.id == user.id).with_for_update())
        if int(wallet.balance_fen or 0) < required + await pending_task_commitment_fen(db, user.id):
            raise HTTPException(402, '余额不足，请充值后运行')
    run.status = 'running'
    await db.commit()
    task = asyncio.create_task(execute_workflow(run.id, dict(edit_session_id=edit_session_id, edit_lock_token=edit_lock_token, edit_lock_version=edit_lock_version)))
    workers.add(task)
    task.add_done_callback(workers.discard)
    return {'id': run.id, 'status': run.status}


@router.get('/projects/{project_id}/workflow')
async def workflow_status(project_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    project = await get_project(db, project_id, user)
    run = await db.scalar(select(Run).where(Run.project_id == project.id, Run.status != 'quoted').order_by(Run.created_at.desc()).limit(1))
    if run and run.status == 'running':
        heartbeat = run.updated_at.replace(tzinfo=UTC) if run.updated_at.tzinfo is None else run.updated_at
        if heartbeat < datetime.now(UTC) - timedelta(seconds=90):
            run.status = 'failed'
            run.error = '后台运行已中断；已提交的媒体任务仍保留，可重新运行剩余节点'
            from app.services.billing.text_tasks import finish_text_task
            for identity in run.plan['ids']:
                if identity not in run.completed:
                    await finish_text_task(db, f'studio-workflow:{run.id}:{identity}', False)
            await db.commit()
    row = await get_or_create(db, project, user)
    return {**_response(row), 'run': None if not run else {'id': run.id, 'status': run.status, 'completed': len(run.completed), 'count': len(run.plan['ids']), 'error': run.error}}


async def patch_node(db, project, user, node_id, patch):
    from app.printfilm_studio.sharing import project_for
    await project_for(db, project.id, user, lock=True)
    # Lock only while merging a small result; never hold a DB lock during generation.
    row = await db.scalar(select(Document).where(Document.project_id == project.id).with_for_update().execution_options(populate_existing=True))
    document = deepcopy(row.document)
    node = next((n for n in document['nodes'] if n['id'] == node_id), None)
    if not node:
        raise ValueError('运行节点已删除，停止后续执行')
    if all(node['data'].get(key) == value for key, value in patch.items()):
        return
    node['data'].update(patch)
    await save(db, project, user, document, row.document_version)


async def run_text(db, run, project, user, node, document):
    from app.services.billing.text_tasks import admit_text_task, finish_text_task
    from app.services.llm_client import chat_completions
    key = f'studio-workflow:{run.id}:{node["id"]}'
    await admit_text_task(db, user, project, key, 'node_writing')
    await patch_node(db, project, user, node['id'], {'status': 'running', 'error': None})
    try:
        from app.printfilm_studio.writing_context import writing_context, linked_writing_result
        prompt, bindings = writing_context(node, document, run.plan['settings'])
        from app.printfilm_studio.agent.director_skills import director_skill_block
        task = 'video_prompt' if any(item['kind']=='video' for item in bindings) else 'asset_plan' if bindings else 'script_write'
        skill_block = await director_skill_block(db, user.id, task, node['data'].get('writingDirectorSkillIds'), writing=True)
        _, params = params_for(node, run.plan['settings'])
        from app.printfilm_studio.integration.llm_stream import TEXT_WRITING_TIMEOUT
        try:
            async with asyncio.timeout(TEXT_WRITING_TIMEOUT):
                result = await chat_completions('按写作要求输出最终正文，不输出解释或工具调用。' + skill_block, prompt, model_id=params['model_id'],timeout=TEXT_WRITING_TIMEOUT,strict_output=True)
        except TimeoutError as exc:
            raise ValueError(f'文字模型响应超时（{TEXT_WRITING_TIMEOUT:g}秒），请更换模型或缩短要求后重试') from exc
        if not result.strip():
            raise ValueError('写作模型没有返回正文')
        if bindings:
            result = linked_writing_result(result, node, document)
        latest = await db.scalar(select(Document).where(Document.project_id == project.id).execution_options(populate_existing=True))
        current = next((n for n in latest.document['nodes'] if n['id'] == node['id']), None) if latest else None
        if not current or str(current['data'].get('text') or '') != str(node['data'].get('text') or '') or current['data'].get('writingDirectorSkillIds') != node['data'].get('writingDirectorSkillIds') or writing_context(current, latest.document, run.plan['settings'])[0] != prompt:
            raise ValueError('写作要求、正文或参考素材已变化，本次结果未覆盖画布，请按最新内容重新运行')
        await finish_text_task(db, key, True)
        await patch_node(db, project, user, node['id'], {'text': result, 'writingOutputSettings': bindings, 'status': 'completed', 'error': None})
    except BaseException:
        await db.rollback()
        await finish_text_task(db, key, False)
        await db.commit()
        raise


async def wait_media(db, run, project, user, node_id, task_id):
    from app.printfilm_studio.integration.generation_routes import project_tasks
    from app.schemas_tools import ToolTaskQueryRequest
    for _ in range(3600):
        result = await project_tasks(project.id, ToolTaskQueryRequest(ids=[task_id]), db, user)
        item = next(iter(result['data']), None)
        if not item:
            raise ValueError('生成任务记录不存在')
        if item['status'] in {'failed', 'cancelled'}:
            raise ValueError(item.get('error') or '上游生成失败')
        if item['status'] in {'succeeded', 'completed'}:
            urls = (item.get('result') or {}).get('urls') or []
            if not urls:
                raise ValueError('生成任务没有返回媒体')
            await patch_node(db, project, user, node_id, {'status': 'completed', 'mediaUrl': urls[0], 'mediaUrls': urls, 'assetId': item.get('asset_id'), 'error': None, 'canCancel': False})
            return
        await asyncio.sleep(2)
    raise ValueError('等待上游超时，已有任务仍保留，后续节点未提交')


async def execute_workflow(run_id, lock, factory=AsyncSessionLocal):
    node_id = None
    async def heartbeat():
        while True:
            async with factory() as db:
                await db.execute(update(Run).where(Run.id == run_id, Run.status == 'running').values(updated_at=datetime.now(UTC)))
                await db.commit()
            await asyncio.sleep(10)
    monitor = asyncio.create_task(heartbeat())
    try:
        async with factory() as db:
            db.info['studio_workflow_run'] = run_id
            run = await db.get(Run, run_id)
            user = await db.get(User, run.user_id)
            project = await get_project(db, run.project_id, user)
            from app.printfilm_studio.agent.queries import DatabaseCanvas
            from app.printfilm_studio.integration.media import create_media_task
            canvas = DatabaseCanvas(db, project, user, **lock)
            for node_id in run.plan['ids']:
                # Recheck access and read freshly committed upstream results at each step.
                await get_project(db, project.id, user)
                db.expire_all()
                await db.refresh(user)
                await db.refresh(project)
                run = await db.get(Run, run_id)
                document, _ = await canvas.load()
                node = next(n for n in document['nodes'] if n['id'] == node_id)
                if run.status != 'running':
                    raise ValueError('后台运行已停止，后续任务未提交')
                stale = node.get('type') in TEXT and parameters_changed(node, output_settings(node, document, run.plan['settings']))
                if not ready(node) or stale or run.plan.get('text_only') and node.get('type') in TEXT:
                    if node['data'].get('status') in BUSY and node['data'].get('taskId'):
                        await wait_media(db, run, project, user, node_id, node['data']['taskId'])
                    elif node.get('type') in TEXT:
                        await run_text(db, run, project, user, node, document)
                    else:
                        kind, params = params_for(node, run.plan['settings'])
                        writer = next((n for n in document['nodes'] if n['id'] == node['data'].get('promptNodeId')), None)
                        prompt = str(writer['data'].get('text') or '') if writer else str(node['data'].get('prompt') or '')
                        accepted = next((item for item in run.plan.get('items', []) if item['input']['id'] == node_id), None)
                        if accepted and await estimate_node(db, user, project.id, node, document, run.plan['settings']) > accepted['yuan']:
                            raise ValueError('模型价格已变化，后续任务未提交，请重新报价')
                        result = await create_media_task(canvas, kind, prompt, node_id=node_id, _reuse_node=True, **params)
                        await wait_media(db, run, project, user, node_id, result['task_id'])
                run.completed = [*run.completed, node_id]
                await db.commit()
            run.status = 'completed'
            await db.commit()
    except BaseException as exc:
        logger.exception('Workflow failed %s', run_id)
        async with factory() as db:
            run = await db.get(Run, run_id)
            db.info['studio_workflow_run'] = run_id
            run.status = 'failed'
            run.error = ('服务已停止，已提交的生成任务仍保留' if isinstance(exc, asyncio.CancelledError) else str(getattr(exc, 'detail', exc)))[:1000]
            await db.commit()
            if node_id:
                project = await get_project(db, run.project_id, await db.get(User, run.user_id))
                row = await get_or_create(db, project, await db.get(User, run.user_id))
                node = next((n for n in row.document['nodes'] if n['id'] == node_id), None)
                if node and node.get('type') in TEXT:
                    await patch_node(db, project, await db.get(User, run.user_id), node_id, {'status': 'failed', 'error': run.error})
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)


async def shutdown_workflows():
    for task in list(workers):
        task.cancel()
    await asyncio.gather(*list(workers), return_exceptions=True)
