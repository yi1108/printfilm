"""No provider calls: defaults/proposals and the exact audio payload contract."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.printfilm_studio.agent.proposals import PreviewCanvas, prepare_proposal
from app.services import studio_generation, studio_tools


def test_workflow_replaces_retired_models_without_changing_saved_nodes():
    from app.printfilm_studio.workflow import params_for
    for kind, data, expected in [
        ('text', {'writingModel': 'kimi-k2.6'}, 'deepseek-v4-pro'),
        ('text', {'writingModel': 'gpt-5.5'}, 'deepseek-v4-pro'),
        ('text', {'writingModel': 'gpt-6-astra'}, 'gpt-6-astra'),
        ('image', {'modelId': 'gpt-image-2'}, 'gpt-image-2.5'),
        ('image', {'modelId': 'seedream-5.0-pro'}, 'seedream-5.0'),
    ]:
        node = {'type': kind, 'data': data}
        before = deepcopy(node)
        assert params_for(node, {'textModel': 'deepseek-v4-pro'})[1]['model_id'] == expected
        assert node == before


@pytest.mark.asyncio
async def test_database_canvas_defaults_only_new_nodes(monkeypatch):
    from app.printfilm_studio.agent import queries
    before = {'nodes': [{'id': 'old', 'type': 'image', 'data': {'modelId': 'existing-choice'}}], 'edges': []}
    monkeypatch.setattr(queries, 'get_or_create', AsyncMock(return_value=SimpleNamespace(document=before, document_version=2)))
    save = AsyncMock(return_value=SimpleNamespace(document_version=3))
    monkeypatch.setattr(queries, 'save', save)
    db = SimpleNamespace(info={'studio_node_defaults': {'image': 'gpt-image-2.5'}})
    canvas = queries.DatabaseCanvas(db, SimpleNamespace(), SimpleNamespace())
    document, _ = await canvas.load()
    document['nodes'] = [*document['nodes'], {'id': 'new', 'type': 'imageGeneration', 'data': {}}]
    await canvas.save(document)
    persisted = save.call_args.args[3]
    assert persisted['nodes'][0]['data']['modelId'] == 'existing-choice'
    assert persisted['nodes'][1]['data']['modelId'] == 'gpt-image-2.5'


@pytest.mark.asyncio
async def test_reviewed_new_nodes_inherit_browser_models_and_director_selection():
    before = {'nodes': [{'id': 's', 'type': 'script', 'data': {'text': '场景一：城楼 - 日\n诸葛亮抚琴。'}}], 'edges': []}
    canvas = PreviewCanvas(before, 1, {
        'studio_node_defaults': {'image': 'gpt-image-2.5', 'video': 'seedance-2.0', 'text': 'deepseek-v4-pro'},
        'studio_director_selection': {'asset_plan': [42]},
    })
    result = await prepare_proposal({'tool': 'plan_story_assets', 'input': {'script_node_id': 's', 'assets': [
        {'kind': 'character', 'name': '诸葛亮', 'prompt': '羽扇纶巾'},
        {'kind': 'scene', 'name': '城楼', 'prompt': '汉代城楼'},
    ]}}, {}, canvas, True)
    assert result['ok']
    assert canvas.document == before, 'reviewing does not persist or enqueue anything'
    added = [change['after'] for change in result['proposal']['nodes'] if change['before'] is None]
    for node in added:
        if node['type'] in {'character', 'scene'}:
            assert node['data']['modelId'] == 'gpt-image-2.5'
        if node['type'] == 'text':
            assert node['data']['writingModel'] == 'deepseek-v4-pro'
            assert node['data']['writingDirectorSkillIds'] == [42]


@pytest.mark.asyncio
async def test_new_video_overrides_hallucinated_model_but_existing_settings_survive():
    document = {'nodes': [{'id': 'old', 'type': 'videoGeneration', 'data': {'modelId': 'custom-model'}}], 'edges': []}
    canvas = PreviewCanvas(document, 1, {'studio_node_defaults': {'video': 'seedance-2.0'}})
    candidate = deepcopy(document)
    candidate['nodes'].append({'id': 'new', 'type': 'videoGeneration', 'data': {'modelId': 'seedance-2.0-fast'}})
    await canvas.save(candidate)
    assert canvas.document['nodes'][0]['data']['modelId'] == 'custom-model'
    assert canvas.document['nodes'][1]['data']['modelId'] == 'seedance-2.0'
    candidate['nodes'][1]['data']['modelId'] = 'user-edited'
    await canvas.save(candidate)
    assert canvas.document['nodes'][1]['data']['modelId'] == 'user-edited'


@pytest.mark.parametrize('requested,expected', [(None, True), (True, True), (False, False)])
@pytest.mark.asyncio
async def test_audio_quote_queue_and_provider_payload_agree(monkeypatch, requested, expected):
    from app.models import ToolRun
    from app.schemas_tools import ToolEstimateRequest
    from app.api.tools import estimate_generation
    from app.services.media_models import planning
    from app.services.billing import estimates, settlement

    params = {'model_id': 'seedance-2.0', 'ratio': '16:9', 'resolution': '720p', 'duration': '6',
              'video_mode': 'text_to_video', 'references': [], 'generate_audio': requested}
    monkeypatch.setattr(planning, 'prepare_task_media', AsyncMock())
    monkeypatch.setattr(estimates, 'estimate_task_fen', AsyncMock(return_value=50))
    monkeypatch.setattr(settlement, 'billing_active', lambda user: True)
    user = SimpleNamespace(id=1)
    await estimate_generation(ToolEstimateRequest(**params), SimpleNamespace(), user)
    quoted_task = planning.prepare_task_media.call_args.args[1]
    assert quoted_task.payload['generate_audio'] is expected

    create = AsyncMock(return_value=SimpleNamespace(id=901))
    monkeypatch.setattr(studio_generation, 'create_task', create)
    def add(row):
        assert isinstance(row, ToolRun)
        row.id = 21
    db = SimpleNamespace(add=add, flush=AsyncMock())
    await studio_generation.enqueue_generation(db, user, tool_id='t2v', prompt='风声，脚步声', params=params, files=[])
    queued = create.call_args.args[2].payload
    assert queued['generate_audio'] is expected
    assert params['generate_audio'] is expected

    ark = SimpleNamespace(gen_video_seedance_body=AsyncMock(return_value='mock-provider-id'))
    monkeypatch.setattr(studio_tools, 'get_ark', lambda: ark)
    await studio_tools.start_video_tool(db, user, tool_id='t2v', prompt='风声，脚步声', ratio='16:9',
        duration_raw='6', motion=None, files=[], model_id='seedance-2.0', resolution='720p',
        video_mode='text_to_video', references=queued, generate_audio=queued['generate_audio'])
    assert ark.gen_video_seedance_body.call_args.args[0]['generate_audio'] is expected


def test_multiple_text_targets_do_not_generate_upstream_images():
    from app.printfilm_studio.workflow import plan_nodes, params_for
    doc = {'nodes': [{'id': 'image', 'type': 'image', 'data': {}},
        *[{'id': identity, 'type': 'text', 'data': {'writingPrompt': '写镜头'}} for identity in ['a', 'b']]],
        'edges': [{'source': 'image', 'target': identity} for identity in ['a', 'b']]}
    assert [n['id'] for n in plan_nodes(doc, ['a', 'b'], text_only=True)] == ['a', 'b']
    assert params_for({'type': 'video', 'data': {'generateAudio': False}}, {})[1]['generate_audio'] is False
