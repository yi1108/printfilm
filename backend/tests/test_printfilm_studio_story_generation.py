from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.printfilm_studio.integration.generation_inputs import story_video_inputs, prepare_inputs


def test_asset_pair_uses_live_text_and_rejects_missing_or_foreign_writer():
    from app.printfilm_studio.integration.generation_inputs import story_asset_prompt
    writer = {'id': 'writer', 'type': 'text', 'data': {'sourceScriptId': 's', 'text': '用户更新的外貌'}}
    asset = {'id': 'role', 'type': 'character', 'data': {'sourceScriptId': 's', 'storyKind': 'character', 'promptNodeId': 'writer', 'prompt': '过期内容'}}
    document = {'nodes': [writer, asset], 'edges': [{'source': 'writer', 'target': 'role'}]}
    assert story_asset_prompt(document, asset) == '用户更新的外貌'
    writer['data']['text'] = ''
    with pytest.raises(ValueError, match='填写'):
        story_asset_prompt(document, asset)
    writer['data'].update(text='正文', sourceScriptId='other')
    with pytest.raises(ValueError, match='同一剧本'):
        story_asset_prompt(document, asset)
    document['edges'] = []
    with pytest.raises(ValueError, match='连接'):
        story_asset_prompt(document, asset)


def graph():
    nodes = [
        {'id': 'prompt', 'type': 'text', 'data': {'sourceScriptId': 'script', 'text': '最新文本提示词'}},
        {'id': 'role', 'type': 'character', 'data': {'sourceScriptId': 'script', 'storyKind': 'character', 'label': '刘备', 'mediaType': 'image', 'mediaUrls': ['/old.png', '/chosen.png'], 'mediaIndex': 1, 'assetId': 1}},
        {'id': 'scene', 'type': 'scene', 'data': {'sourceScriptId': 'script', 'storyKind': 'scene', 'label': '桃园', 'mediaType': 'image', 'mediaUrl': '/garden.png', 'assetId': 2}},
        {'id': 'video', 'type': 'videoGeneration', 'data': {'sourceScriptId': 'script', 'storyKind': 'shot_video', 'promptNodeId': 'prompt', 'referenceNodeIds': ['role', 'scene'], 'prompt': '过期提示词', 'mediaUrl': '/old-video.mp4'}},
    ]
    return {'nodes': nodes, 'edges': [{'source': source, 'target': 'video'} for source in ['prompt', 'role', 'scene']]}


def test_story_input_uses_live_text_and_current_image_variant():
    document = graph()
    source = document['nodes'][-1]
    resolved = story_video_inputs(document, source)
    assert resolved['prompt'] == '最新文本提示词'
    assert [ref['url'] for ref in resolved['references']] == ['/chosen.png', '/garden.png']
    document['nodes'][2]['data']['mediaUrl'] = ''
    with pytest.raises(ValueError, match='先生成参考图.*桃园'):
        story_video_inputs(document, source)
    document = graph()
    document['edges'].pop()
    with pytest.raises(ValueError, match='连线不完整'):
        story_video_inputs(document, document['nodes'][-1])


def test_story_video_rejects_cross_script_and_missing_scene():
    document = graph()
    source = document['nodes'][-1]
    document['nodes'][0]['data']['sourceScriptId'] = 'other'
    with pytest.raises(ValueError, match='同一个剧本'):
        story_video_inputs(document, source)
    document['nodes'][0]['data']['sourceScriptId'] = 'script'
    source['data']['referenceNodeIds'] = ['role']
    with pytest.raises(ValueError, match='缺少场景'):
        story_video_inputs(document, source)


@pytest.mark.asyncio
async def test_two_story_images_remain_references_not_first_last_frames(monkeypatch, tmp_path):
    from app.printfilm_studio.integration import generation_inputs as module
    assets = [SimpleNamespace(id=1, url='/chosen.png', cover=None, asset_type='image'), SimpleNamespace(id=2, url='/garden.png', cover=None, asset_type='image')]
    canvas = SimpleNamespace(db=SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: assets))), project=SimpleNamespace(id=7), user=SimpleNamespace(id=8))
    async def read(_asset, path, _stopped):
        path.write_bytes(b'image')
    monkeypatch.setattr(module, 'read_asset_file', read)
    monkeypatch.setattr(module, 'validate_upload', lambda *_: None)
    monkeypatch.setattr(module, 'save_upload', lambda _user, raw, name: tmp_path / name)
    monkeypatch.setattr(module, 'reference_params', AsyncMock(return_value={}))
    document = graph()
    files, options = await prepare_inputs(canvas, 'video', document, document['nodes'][-1], None)
    assert len(files) == 2
    assert options['video_mode'] == 'omni_reference'
    assert [ref['role'] for ref in options['references']] == ['reference_image', 'reference_image']


@pytest.mark.asyncio
async def test_agent_generation_reuses_story_video_and_ignores_stale_tool_prompt(monkeypatch):
    from app.printfilm_studio.integration import generation_inputs, media
    from app.services import studio_generation
    document = graph()
    document['nodes'][0]['data']['writingOutputSettings'] = [{'id':'video', 'model':'seedance-2.0-fast', 'ratio':'16:9', 'duration':'6'}]
    document['nodes'][-1]['data'].update(modelId='seedance-2.5', ratio='16:9', duration='6')
    task = SimpleNamespace(cancelable=False, payload={})
    canvas = SimpleNamespace(project=SimpleNamespace(id=7, team_id=None), user=SimpleNamespace(id=8), db=SimpleNamespace(info={}, get=AsyncMock(return_value=task), rollback=AsyncMock()), load=AsyncMock(return_value=(document, 1)), save=AsyncMock(return_value=2))
    monkeypatch.setattr(generation_inputs, 'prepare_inputs', AsyncMock(return_value=([], {'video_mode': 'omni_reference', 'references': []})))
    enqueue = AsyncMock(return_value={'task_id': 'task-1', 'platform_task_id': 1, 'status': 'queued'})
    monkeypatch.setattr(studio_generation, 'enqueue_generation', enqueue)
    result = await media.create_media_task(canvas, 'video', '过期模型正文', node_id='video')
    assert result['node_id'] == 'video'
    assert '最新文本提示词\n参考素材对应' in enqueue.call_args.kwargs['prompt']
    assert enqueue.call_args.kwargs['prompt'].startswith('拍摄指令（只执行，不朗读')
    assert '@图片1：刘备' in enqueue.call_args.kwargs['prompt']
    assert '@图片2：桃园' in enqueue.call_args.kwargs['prompt']
    assert enqueue.call_args.kwargs['params']['model_id'] == 'seedance-2.5'
    assert enqueue.call_args.kwargs['params']['duration'] == '6'
    assert len(document['nodes']) == 4 and len(document['edges']) == 3
    assert document['nodes'][-1]['data']['status'] == 'queued'
    assert document['nodes'][-1]['data']['mediaHistory'][-1]['mediaUrl'] == '/old-video.mp4'
    assert not document['nodes'][-1]['data']['mediaUrl']


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['character', 'scene'])
async def test_story_asset_regeneration_preserves_identity_and_previous_media(monkeypatch, kind):
    from app.printfilm_studio.integration import generation_inputs, media
    from app.services import studio_generation
    source = {'id': 'asset-node', 'type': kind, 'data': {'label': '固定名称', 'sourceScriptId': 'script', 'storyKind': kind, 'mediaType': 'image', 'mediaUrl': '/old.png', 'prompt': '节点里的新提示词'}}
    document = {'nodes': [source], 'edges': []}
    task = SimpleNamespace(cancelable=False, payload={})
    canvas = SimpleNamespace(project=SimpleNamespace(id=7, team_id=None), user=SimpleNamespace(id=8), db=SimpleNamespace(info={}, get=AsyncMock(return_value=task), rollback=AsyncMock()), load=AsyncMock(return_value=(document, 1)), save=AsyncMock(return_value=2))
    monkeypatch.setattr(generation_inputs, 'prepare_inputs', AsyncMock(return_value=([], {})))
    enqueue = AsyncMock(return_value={'task_id': 'task-2', 'platform_task_id': 2, 'status': 'queued'})
    monkeypatch.setattr(studio_generation, 'enqueue_generation', enqueue)
    result = await media.create_media_task(canvas, 'image', '旧工具文本', node_id='asset-node')
    assert result['node_id'] == source['id'] and len(document['nodes']) == 1
    assert enqueue.call_args.kwargs['prompt'] == '节点里的新提示词'
    assert source['data']['label'] == '固定名称'
    assert source['data']['mediaHistory'][-1]['mediaUrl'] == '/old.png'



def test_provider_mentions_follow_actual_upload_order():
    doc = graph()
    doc['nodes'][0]['data']['text'] = '@[刘备](node:role)在@[桃园](node:scene)抬头'
    doc['nodes'][-1]['data']['referenceNodeIds'] = ['scene', 'role']
    result = story_video_inputs(doc, doc['nodes'][-1])
    assert result['provider_prompt'].startswith('@图片2在@图片1抬头')
    assert '@图片1：桃园，用于场景空间与光线' in result['provider_prompt']
    assert '@图片2：刘备，仅用于人物身份' in result['provider_prompt']
    assert '(node:' not in result['provider_prompt']
    assert [ref['url'] for ref in result['references']] == ['/garden.png', '/chosen.png']
