"""Session and NDJSON Agent API."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.deps import get_current_user
from app.models import User
from app.models_printfilm_studio import PrintfilmStudioAgentMessage, PrintfilmStudioAgentSession, PrintfilmStudioAgentRun
from app.printfilm_studio import ensure_enabled
from app.printfilm_studio.agent import runs
from app.printfilm_studio.canvas.service import get_project

router = APIRouter(prefix="/printfilm-studio", tags=["printfilm-studio-agent"])


class SessionCreate(BaseModel):
    title: str = Field(default="Printfilm Studio 会话", max_length=200)
    model_id: str | None = Field(default=None, max_length=128)


class NodeDefaults(BaseModel):
    image: str = Field(default='', max_length=128)
    video: str = Field(default='', max_length=128)
    text: str = Field(default='', max_length=128)


class StreamRequest(BaseModel):
    node_defaults: NodeDefaults = Field(default_factory=NodeDefaults)
    prompt: str = Field(min_length=1, max_length=20_000)
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=64)
    enabled_tools: list[str] | None = Field(default=None, max_length=30)
    node_ids: list[str] = Field(default_factory=list, max_length=20)
    asset_ids: list[int] = Field(default_factory=list, max_length=20)
    story_step: Literal['assets', 'shots'] | None = None
    review_changes: bool = False
    agent_mode: Literal['director', 'assistant'] = 'assistant'
    skill_task: Literal['script_write', 'asset_plan', 'shot_plan', 'video_prompt', 'edit_plan'] | None = None
    skill_ids: list[StrictInt] | None = Field(default=None, max_length=1)
    director_skill_selection: dict[Literal['script_write', 'asset_plan', 'shot_plan', 'video_prompt', 'edit_plan'], StrictInt | None] = Field(default_factory=dict)


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    model_id: str | None = Field(default=None, max_length=128)


@router.get('/agent/config')
async def agent_config(user: User = Depends(get_current_user)):
    ensure_enabled()
    from app.services.model_settings import get_routing_snapshot
    from app.config import get_settings
    from app.printfilm_studio.agent.tools import TOOL_NAMES
    from app.services.media_model_presets import preset_display_meta
    snapshot = get_routing_snapshot()
    models = [{'id': model.id, 'label': preset_display_meta(model.id)['label'] or model.id} for model in snapshot.logical_models if model.enabled and model.capability == 'text']
    default = get_settings().model_llm
    if not models and default:
        models = [{'id': default, 'label': default}]
    return {'models': models, 'tools': list(TOOL_NAMES), 'default_model': default if any(model['id'] == default for model in models) else models[0]['id'] if models else ''}


@router.patch('/agent/sessions/{session_id}')
async def update_session(session_id: str, body: SessionUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    row = await _session(db, session_id, user)
    if row.status == 'running':
        raise HTTPException(409, '当前执行结束后才能更改会话设置')
    if body.title is not None:
        row.title = body.title.strip() or 'Printfilm Studio 会话'
    if 'model_id' in body.model_fields_set:
        config = await agent_config(user)
        if body.model_id and body.model_id not in {item['id'] for item in config['models']}:
            raise HTTPException(422, '所选文字模型不可用')
        row.model_id = body.model_id or None
    await db.commit()
    # onupdate timestamps are server-generated and expire even with
    # expire_on_commit=False. Load them before synchronous serialization.
    await db.refresh(row)
    return _session_out(row)


class AnswerRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class HistoryAction(BaseModel):
    action: Literal['branch', 'edit_branch', 'truncate']
    expected_sequence: int = Field(ge=1)
    expected_last_message_id: str = Field(min_length=1, max_length=36)


@router.post('/agent/sessions/{session_id}/messages/{message_id}/actions')
async def message_action(session_id: str, message_id: str, body: HistoryAction, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    await _session(db, session_id, user)
    from app.printfilm_studio.agent.conversation import change_history
    changed_id = await change_history(db, session_id, message_id, body.action, body.expected_sequence, body.expected_last_message_id)
    return await get_session(changed_id, db, user)


def _session_out(row: PrintfilmStudioAgentSession) -> dict:
    return {"id": row.id, "project_id": row.project_id, "title": row.title, "model_id": row.model_id, "status": row.status, "created_at": row.created_at.isoformat() if row.created_at else None, "updated_at": row.updated_at.isoformat() if row.updated_at else None}


async def _session(db: AsyncSession, session_id: str, user: User) -> PrintfilmStudioAgentSession:
    row = await db.get(PrintfilmStudioAgentSession, session_id)
    if not row or not user or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Agent 会话不存在")
    await get_project(db, row.project_id, user)
    # Pre-replay versions left sessions running when their HTTP request died.
    # Recover only old orphan sessions; current durable runs use their lease.
    if row.status == 'running' and row.updated_at:
        updated = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=UTC)
        if updated < datetime.now(UTC) - timedelta(minutes=10) and not await runs.latest_run(db, row.id):
            row.status = 'failed'
            await db.commit()
    return row


@router.get("/projects/{project_id}/agent/sessions")
async def list_sessions(project_id: Annotated[int, Path(gt=0)], db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_enabled()
    await get_project(db, project_id, user)
    rows = (await db.scalars(select(PrintfilmStudioAgentSession).where(PrintfilmStudioAgentSession.project_id == project_id, PrintfilmStudioAgentSession.user_id == user.id).order_by(PrintfilmStudioAgentSession.updated_at.desc()))).all()
    return {"sessions": [_session_out(row) for row in rows]}


@router.post("/projects/{project_id}/agent/sessions")
async def create_session(project_id: Annotated[int, Path(gt=0)], body: SessionCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_enabled()
    project = await get_project(db, project_id, user)
    if body.model_id and body.model_id not in {item['id'] for item in (await agent_config(user))['models']}:
        raise HTTPException(422, '所选文字模型不可用')
    row = PrintfilmStudioAgentSession(project_id=project.id, team_id=project.team_id, user_id=user.id, title=body.title, model_id=body.model_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _session_out(row)


@router.get("/agent/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_enabled()
    row = await _session(db, session_id, user)
    run = await runs.latest_run(db, row.id)
    if run:
        await runs.expire_run(db, run.id)
        await db.refresh(row)
        await db.refresh(run)
    from app.printfilm_studio.agent.conversation import messages_out
    return {**_session_out(row), "run": runs.run_out(run), "messages": await messages_out(db, row.id)}


async def _subscribe(session_id, run_id, user_id, info, after=0):
    """Each poll uses a fresh transaction; no connection is held during waits."""
    cursor = after
    while True:
        async with AsyncSessionLocal() as db:
            db.info.update(info)
            user = await db.get(User, user_id)
            try:
                await _session(db, session_id, user)
                ensure_enabled()
            except HTTPException:
                yield json.dumps({'type': 'error', 'code': 'access_revoked', 'message': '会话权限已失效'}) + '\n'
                return
            await runs.expire_run(db, run_id)
            batch = await runs.read_events(db, run_id, cursor)
            run = await db.get(PrintfilmStudioAgentRun, run_id, populate_existing=True)
            terminal = not run or run.status != 'running'
            last_sequence = run.next_sequence - 1 if run else cursor
        for event in batch:
            cursor = event['sequence']
            yield json.dumps(event, ensure_ascii=False) + '\n'
        if terminal and cursor >= last_sequence:
            return
        if not batch:
            yield json.dumps({'type': 'heartbeat', 'run_id': run_id}) + '\n'
            await asyncio.sleep(1)


def _stream_response(session_id, run_id, user_id, info, after=0):
    return StreamingResponse(_subscribe(session_id, run_id, user_id, info, after), media_type='application/x-ndjson', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@router.post("/agent/sessions/{session_id}/stream")
async def stream_session(session_id: str, body: StreamRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), edit_session_id: str | None = Header(default=None, alias="X-Edit-Session"), edit_lock_token: str | None = Header(default=None, alias="X-Edit-Token"), edit_lock_version: int | None = Header(default=None, alias="X-Edit-Version")) -> StreamingResponse:
    ensure_enabled()
    row = await _session(db, session_id, user)
    project = await get_project(db, row.project_id, user)
    user_id = user.id
    from app.printfilm_studio.agent.tools import TOOL_NAMES
    from app.printfilm_studio.canvas.service import get_or_create
    from app.models_drama import DramaAsset
    if body.enabled_tools is not None and not set(body.enabled_tools).issubset(TOOL_NAMES):
        raise HTTPException(422, '工具列表包含未知工具')
    if body.agent_mode == 'director' and body.enabled_tools is None:
        body.enabled_tools = [tool for tool in TOOL_NAMES if tool not in {'create_image_task','create_video_task','create_audio_task'}]
    from app.printfilm_studio.agent.references import asset_reference, node_reference
    context = []
    referenced_nodes = []
    if body.node_ids:
        document = await get_or_create(db, project, user)
        nodes = {node['id']: node for node in document.document.get('nodes', [])}
        if not set(body.node_ids).issubset(nodes):
            raise HTTPException(422, '引用节点已不存在')
        referenced_nodes = [nodes[node_id] for node_id in dict.fromkeys(body.node_ids)]
        context += [f"引用节点 {node_id}：{json.dumps(nodes[node_id], ensure_ascii=False)[:2000]}" for node_id in body.node_ids]
    linked_ids = {int(value) for node in referenced_nodes if str(value := (node.get('data') or {}).get('assetId') or (node.get('data') or {}).get('asset_id') or '').isdigit()}
    asset_ids = set(body.asset_ids) | linked_ids
    assets = []
    if asset_ids:
        assets = (await db.scalars(select(DramaAsset).where(DramaAsset.project_id == project.id, DramaAsset.id.in_(asset_ids)))).all()
        if not set(body.asset_ids).issubset({asset.id for asset in assets}):
            raise HTTPException(422, '引用素材不属于当前项目')
        context += [f'引用项目素材 #{asset.id}：{asset.name}，类型 {asset.asset_type}，地址 {asset.url}' for asset in assets if asset.id in body.asset_ids]
    assets_by_id = {asset.id: asset for asset in assets}
    references = [node_reference(node, assets) for node in referenced_nodes]
    references += [asset_reference(assets_by_id[asset_id]) for asset_id in dict.fromkeys(body.asset_ids)]
    if body.story_step:
        if len(referenced_nodes) != 1:
            raise HTTPException(422, '创作引导需要选择一个剧本节点')
        script = referenced_nodes[0]
        if script.get('type') not in {'script', 'text'} or not str(script.get('data', {}).get('text') or '').strip():
            raise HTTPException(422, '请选择有正文的剧本节点')
        required_tool = 'plan_story_assets' if body.story_step == 'assets' else 'plan_story_shots'
        stage_tools = {'read_canvas', required_tool}
        if body.enabled_tools is not None and not stage_tools.issubset(body.enabled_tools):
            raise HTTPException(422, '请开启当前创作阶段需要的工具')
        body.enabled_tools = sorted(stage_tools)
        if body.story_step == 'shots' and not any(node.get('data', {}).get('sourceScriptId') == script['id'] and node.get('data', {}).get('storyKind') == 'scene' for node in document.document.get('nodes', [])):
            raise HTTPException(422, '请先补齐场景图片节点')
        related = [{'id': node['id'], 'name': node.get('data', {}).get('label'), 'kind': node.get('data', {}).get('storyKind')} for node in document.document.get('nodes', []) if node.get('data', {}).get('sourceScriptId') == script['id']]
        context.append(f"本次创作阶段：{body.story_step}。剧本节点：{script['id']}。先用 read_canvas(node_ids=[剧本ID]) 读取完整正文，再调用 {required_tool} 完成本阶段；成功后停止。相关节点：{json.dumps(related, ensure_ascii=False)}")
    from app.printfilm_studio.agent.director_skills import director_skill_ids, resolve_director_skill_task
    task = resolve_director_skill_task(body.story_step, body.skill_task)
    selections = {}
    if body.agent_mode == 'director':
        try:
            for phase, identity in body.director_skill_selection.items():
                selections[phase] = await director_skill_ids(db, user_id, phase, [identity] if identity is not None else [])
            body.skill_ids = await director_skill_ids(db, user_id, task, selections.get(task, body.skill_ids))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    previous = await runs.latest_run(db, row.id)
    if previous:
        await runs.expire_run(db, previous.id)
    run, created = await runs.reserve_run(db, session_id, body.prompt, body.request_id, references=references, billing_context=(user, project))
    info = dict(db.info)
    info['studio_enabled_tools'] = body.enabled_tools
    info['studio_review_changes'] = body.review_changes
    from app.printfilm_studio.agent.director_skills import resolve_director_skill_task
    info['studio_agent_mode'] = body.agent_mode
    info['studio_skill_task'] = resolve_director_skill_task(body.story_step, body.skill_task)
    info['studio_skill_ids'] = body.skill_ids
    info['studio_director_selection'] = selections
    info['studio_node_defaults'] = body.node_defaults.model_dump()
    info['studio_required_tool'] = required_tool if body.story_step else None
    if created:
        runs.launch_run(run.id, session_id, user_id, body.prompt + ('\n\n用户引用内容（素材地址仅作引用，不能假设已读取媒体内容）：\n' + '\n'.join(context) if context else ''), info, dict(edit_session_id=edit_session_id, edit_lock_token=edit_lock_token, edit_lock_version=edit_lock_version))
    return _stream_response(session_id, run.id, user_id, info)


@router.get("/agent/sessions/{session_id}/runs/{run_id}/events")
async def replay_events(session_id: str, run_id: str, after: int = Query(default=0, ge=0), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    await _session(db, session_id, user)
    run = await db.get(PrintfilmStudioAgentRun, run_id)
    if not run or run.session_id != session_id:
        raise HTTPException(404, 'Agent 运行不存在')
    return _stream_response(session_id, run_id, user.id, dict(db.info), after)


@router.post("/agent/sessions/{session_id}/stop")
async def stop_session(session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_enabled()
    row = await _session(db, session_id, user)
    run = await runs.latest_run(db, row.id)
    if run and run.status == 'running':
        run.stop_requested = True
        await db.commit()
        await runs.cancel_linked_tasks(db, run.id, user)
        await db.refresh(row)
        await db.refresh(run)
    return {**_session_out(row), 'stop_requested': bool(run and run.stop_requested)}


@router.post("/agent/sessions/{session_id}/answer")
async def answer_session(session_id: str, body: AnswerRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Persist a user answer for a waiting Agent run; the next stream consumes it."""
    ensure_enabled()
    row = await _session(db, session_id, user)
    if row.status == "running":
        raise HTTPException(409, "请先停止当前执行再补充回答")
    latest = await db.scalar(select(PrintfilmStudioAgentMessage.sequence).where(PrintfilmStudioAgentMessage.session_id == row.id).order_by(PrintfilmStudioAgentMessage.sequence.desc()).limit(1))
    db.add(PrintfilmStudioAgentMessage(session_id=row.id, role="user", content=body.content, sequence=int(latest or 0) + 1))
    row.status = "idle"
    await db.commit()
    return _session_out(row)


@router.delete("/agent/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_enabled()
    row = await _session(db, session_id, user)
    if row.status == "running":
        raise HTTPException(409, "请先停止当前执行再删除会话")
    await db.execute(delete(PrintfilmStudioAgentSession).where(PrintfilmStudioAgentSession.id == row.id))
    await db.commit()
    return {"ok": True}
