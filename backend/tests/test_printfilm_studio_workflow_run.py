"""Dependency execution and real wallet settlement in a disposable database."""
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import app.models_teams  # noqa: F401
from app.models import User, UsageEvent, WalletLedger
from app.models_tasks import TaskRun
from app.models_agent import AgentSkill
from app.models_drama import DramaProject
from app.models_printfilm_studio import PrintfilmStudioWorkflowRun as Run, PrintfilmStudioCanvasDocument as Document
from app.printfilm_studio import workflow
from app.services.billing.text_tasks import admit_text_task, finish_text_task


def graph():
    nodes = [
        {'id': 'script', 'type': 'script', 'data': {'text': '已有剧本'}},
        {'id': 'writer', 'type': 'text', 'data': {'writingPrompt': '写角色提示词', 'sourceScriptId': 'script'}},
        {'id': 'image', 'type': 'image', 'data': {'promptNodeId': 'writer'}},
        {'id': 'shot', 'type': 'text', 'data': {'writingPrompt': '根据图片写镜头', 'sourceScriptId': 'script'}},
        {'id': 'video', 'type': 'video', 'data': {'promptNodeId': 'shot'}},
    ]
    for node in nodes:
        node['position'] = {'x': 0, 'y': 0}
        node['data']['label'] = node['id']
    return {'nodes': nodes, 'edges': [{'id': a+b, 'source': a, 'target': b} for a,b in [('writer','image'),('image','shot'),('shot','video')]]}


@pytest_asyncio.fixture
async def store(tmp_path, monkeypatch):
    engine = create_async_engine(f'sqlite+aiosqlite:///{(tmp_path / "workflow.db").as_posix()}')
    async with engine.begin() as conn:
        for model in (User, DramaProject, AgentSkill, UsageEvent, WalletLedger, TaskRun, Run, Document):
            await conn.run_sync(model.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(User(id=1, email='workflow@example.test', hashed_password='test', balance_fen=100, frozen_fen=0))
        db.add(DramaProject(id=1, user_id=1, title='workflow test'))
        db.add(Document(project_id=1, created_by=1, updated_by=1, document=graph(), document_version=1))
        await db.commit()
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'billing_enabled', True)
    project = SimpleNamespace(id=1, team_id=None)
    async def get_project(db, project_id, user):
        return await db.get(DramaProject, project_id)
    monkeypatch.setattr(workflow, 'get_project', get_project)
    yield factory, project
    await engine.dispose()


def test_dependency_order_prunes_completed_and_rejects_cycles():
    doc = graph()
    assert [n['id'] for n in workflow.plan_nodes(doc, ['video'])] == ['writer','image','shot','video']
    doc['edges'].append({'source': 'video', 'target': 'writer'})
    with pytest.raises(ValueError, match='循环'):
        workflow.plan_nodes(doc, ['video'])
    doc['nodes'][2]['data']['mediaUrl'] = '/ready.png'
    assert [n['id'] for n in workflow.plan_nodes(doc, ['shot'])] == ['shot']


def test_direct_text_plan_does_not_run_unfinished_upstream_nodes():
    doc = graph()
    assert [n['id'] for n in workflow.plan_nodes(doc, ['shot'], text_only=True)] == ['shot']
    doc['nodes'][3]['data']['text'] = '已有提示词仍允许单独重写'
    assert [n['id'] for n in workflow.plan_nodes(doc, ['shot'], text_only=True)] == ['shot']
    with pytest.raises(ValueError, match='文本节点'):
        workflow.plan_nodes(doc, ['video'], text_only=True)


@pytest.mark.asyncio
async def test_text_wallet_exactly_five_fen_idempotent_and_failure_refund(store):
    factory, project = store
    async with factory() as db:
        user = await db.get(User, 1)
        task = await admit_text_task(db, user, project, 'one')
        assert user.balance_fen == 95 and user.frozen_fen == 5
        assert (await admit_text_task(db, user, project, 'one')).id == task.id
        await finish_text_task(db, 'one', True)
        await finish_text_task(db, 'one', True)
        await db.commit()
        await db.refresh(user)
        assert user.balance_fen == 95 and user.frozen_fen == 0
        assert task.billing_charged_fen == 5
        assert (await db.scalar(select(UsageEvent))).charge_fen == 5
        await admit_text_task(db, user, project, 'failed', 'node_writing')
        await finish_text_task(db, 'failed', False)
        await db.commit()
        await db.refresh(user)
        assert user.balance_fen == 95 and user.frozen_fen == 0


@pytest.mark.asyncio
async def test_worker_reads_upstream_results_and_finishes_without_http_subscriber(store, monkeypatch):
    factory, project = store
    calls = []
    async def complete(system, prompt, **kwargs):
        calls.append('text')
        if len(calls) > 1:
            assert '/image.png' in prompt
        return '最终提示词'
    async def media(canvas, kind, prompt, **params):
        assert prompt == ('最终提示词\n参考图片：@[image](node:image)' if kind == 'video' else '最终提示词')
        calls.append(kind)
        node_id = params['node_id']
        await workflow.patch_node(canvas.db, project, canvas.user, node_id, {'taskId': f'task-{node_id}', 'status': 'queued'})
        return {'task_id': f'task-{node_id}'}
    async def tasks(project_id, body, db, user):
        identity = body.ids[0].removeprefix('task-')
        return {'data': [{'id': body.ids[0], 'status': 'succeeded', 'result': {'urls': [f'/{identity}.png']}}]}
    monkeypatch.setattr('app.services.llm_client.chat_completions', complete)
    monkeypatch.setattr('app.printfilm_studio.integration.media.create_media_task', media)
    monkeypatch.setattr('app.printfilm_studio.integration.generation_routes.project_tasks', tasks)
    async with factory() as db:
        run = Run(project_id=1, user_id=1, status='running', plan={'ids': ['writer','image','shot','video'], 'settings': {}})
        db.add(run); await db.commit(); run_id = run.id
    await workflow.execute_workflow(run_id, {}, factory)
    async with factory() as db:
        run = await db.get(Run, run_id)
        assert run.status == 'completed', run.error
        assert calls == ['text','image','text','video']
        assert len(run.completed) == 4
        assert (await db.get(User, 1)).balance_fen == 90
        doc = await db.scalar(select(Document))
        assert next(n for n in doc.document['nodes'] if n['id'] == 'video')['data']['mediaUrl'] == '/video.png'


@pytest.mark.asyncio
async def test_failure_refunds_and_does_not_submit_descendants(store, monkeypatch):
    factory, _ = store
    monkeypatch.setattr('app.services.llm_client.chat_completions', AsyncMock(side_effect=ValueError('模型失败')))
    media = AsyncMock()
    monkeypatch.setattr('app.printfilm_studio.integration.media.create_media_task', media)
    async with factory() as db:
        run = Run(project_id=1, user_id=1, status='running', plan={'ids': ['writer','image'], 'settings': {}})
        db.add(run); await db.commit(); identity = run.id
    await workflow.execute_workflow(identity, {}, factory)
    async with factory() as db:
        assert (await db.get(Run, identity)).status == 'failed'
        assert (await db.get(User, 1)).balance_fen == 100
    media.assert_not_awaited()


def test_shot_planning_preserves_assets_and_groups_each_scene():
    from app.printfilm_studio.agent.story_workflow import build_story_plan
    doc = {'nodes': [graph()['nodes'][0]], 'edges': []}
    doc, _ = build_story_plan(doc, 'plan_story_assets', {'script_node_id': 'script', 'assets': [{'kind': 'scene', 'name': name, 'prompt': '写作要求'} for name in ['城门', '大殿']]})
    assets = copy.deepcopy({n['id']: n for n in doc['nodes'] if n['id'] != 'script'})
    scenes = [n for n in doc['nodes'] if n['type'] == 'scene']
    doc, _ = build_story_plan(doc, 'plan_story_shots', {'script_node_id': 'script', 'shots': [{'index': i+1, 'name': '旧名字', 'prompt': '写镜头', 'description': '画面要求', 'reference_node_ids': [scenes[i // 2]['id']]} for i in range(4)]})
    assert all(next(n for n in doc['nodes'] if n['id'] == identity) == before for identity, before in assets.items())
    groups = [n for n in doc['nodes'] if n['data'].get('storyKind') == 'shot_video_group']
    assert len(groups) == 2
    for group in groups:
        videos = [n for n in doc['nodes'] if n.get('parentId') == group['id'] and n['type'] == 'videoGeneration']
        assert [n['data']['label'] for n in videos] == ['镜头1 · 视频', '镜头2 · 视频']


@pytest.mark.asyncio
async def test_edit_during_writing_is_preserved_and_refunded(store, monkeypatch):
    factory, project = store
    async def complete(*args, **kwargs):
        async with factory() as db:
            await workflow.patch_node(db, project, await db.get(User, 1), 'writer', {'text': '用户正在修改的正文'})
        return '旧要求的生成结果'
    monkeypatch.setattr('app.services.llm_client.chat_completions', complete)
    async with factory() as db:
        run = Run(project_id=1, user_id=1, status='running', plan={'ids':['writer'], 'settings':{}})
        db.add(run); await db.commit(); identity = run.id
    await workflow.execute_workflow(identity, {}, factory)
    async with factory() as db:
        run = await db.get(Run, identity)
        assert run.status == 'failed' and '未覆盖' in run.error
        document = await db.scalar(select(Document))
        assert next(n for n in document.document['nodes'] if n['id']=='writer')['data']['text'] == '用户正在修改的正文'
        assert (await db.get(User,1)).balance_fen == 100


@pytest.mark.asyncio
async def test_direct_text_worker_never_generates_its_image_dependencies(store, monkeypatch):
    factory, _ = store
    monkeypatch.setattr('app.services.llm_client.chat_completions', AsyncMock(return_value='仅当前文本的结果'))
    media = AsyncMock()
    monkeypatch.setattr('app.printfilm_studio.integration.media.create_media_task', media)
    async with factory() as db:
        run = Run(project_id=1, user_id=1, status='running', plan={'ids':['shot'], 'settings':{}, 'text_only':True})
        db.add(run); await db.commit(); identity=run.id
    await workflow.execute_workflow(identity, {}, factory)
    async with factory() as db:
        assert (await db.get(Run,identity)).status == 'completed'
        doc = await db.scalar(select(Document))
        assert not next(n for n in doc.document['nodes'] if n['id']=='image')['data'].get('taskId')
        assert next(n for n in doc.document['nodes'] if n['id']=='shot')['data']['text'] == '仅当前文本的结果\n参考图片：@[image](node:image)'
    media.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_timeout_clears_running_state_and_refunds(store, monkeypatch):
    import asyncio
    factory, _ = store
    async def never(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr('app.services.llm_client.chat_completions', never)
    monkeypatch.setattr('app.printfilm_studio.integration.llm_stream.TEXT_WRITING_TIMEOUT', .02)
    async with factory() as db:
        run = Run(project_id=1,user_id=1,status='running',plan={'ids':['shot'],'settings':{},'text_only':True})
        db.add(run); await db.commit(); identity=run.id
    await workflow.execute_workflow(identity,{},factory)
    async with factory() as db:
        run=await db.get(Run,identity)
        assert run.status=='failed' and '响应超时' in run.error
        doc=await db.scalar(select(Document))
        assert next(n for n in doc.document['nodes'] if n['id']=='shot')['data']['status']=='failed'
        assert (await db.get(User,1)).balance_fen==100
