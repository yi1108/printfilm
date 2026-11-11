import copy
import json

import pytest

from app.printfilm_studio.agent.executor import execute_studio_tool
from app.printfilm_studio.agent.runtime import iter_agent_turn


class Canvas:
    def __init__(self):
        self.document = {'nodes': [{'id': 'script', 'type': 'script', 'position': {'x': 0, 'y': 0}, 'data': {'label': '桃园结义', 'text': '开场。' * 100 + '结尾三人结义。'}}], 'edges': []}
        self.version = 1

    async def load(self):
        return copy.deepcopy(self.document), self.version

    async def save(self, document):
        self.document = document
        self.version += 1
        return self.version


ASSETS = {'script_node_id': 'script', 'assets': [
    {'kind': 'character', 'name': '刘备', 'prompt': '东汉青年刘备，布衣长袍，温和坚毅，写实电影风格'},
    {'kind': 'scene', 'name': '桃园', 'prompt': '东汉桃园，桃花盛开，清晨柔和光线，写实电影风格'},
]}


def test_shot_duration_defaults_to_fifteen_and_binds_writer_and_video():
    from app.printfilm_studio.agent.story_workflow import build_story_plan
    from app.printfilm_studio.agent.story_parameters import shot_parameters

    document, _ = build_story_plan(Canvas().document, 'plan_story_assets', ASSETS)
    refs = [node['id'] for node in document['nodes'] if node['type'] in {'character', 'scene'}]
    item = {'index': 1, 'name': '进园与宣誓', 'description': '三人走入桃园，站定并说出誓言，另两人回应。',
            'prompt': '按连续动作与对白反应写完整片段', 'reference_node_ids': refs}
    planned, _ = build_story_plan(document, 'plan_story_shots', {'script_node_id': 'script', 'shots': [item]})
    video = next(node for node in planned['nodes'] if node['data'].get('storyKind') == 'shot_video')
    writer = next(node for node in planned['nodes'] if node['id'] == video['data']['promptNodeId'])
    assert video['data']['duration'] == '15'
    assert '镜头时长：15 秒' in writer['data']['writingPrompt']
    assert item['description'] in writer['data']['writingPrompt']
    assert shot_parameters({'duration': 6}, {})['duration'] == '6'
    assert shot_parameters({}, {'videoDuration': 12})['duration'] == '12'


@pytest.mark.parametrize('duration', [16, 30, 120, 0, -1, True, 'nan', 'inf'])
def test_shot_duration_above_fifteen_rejects_whole_plan(duration):
    from app.printfilm_studio.agent.story_workflow import build_story_plan
    document, _ = build_story_plan(Canvas().document, 'plan_story_assets', ASSETS)
    before = copy.deepcopy(document)
    refs = [node['id'] for node in document['nodes'] if node['type'] in {'character', 'scene'}]
    item = {'index': 1, 'name': '完整片段', 'description': '走入桃园并宣誓', 'prompt': '连续叙事', 'duration': 15, 'reference_node_ids': refs}
    with pytest.raises(ValueError, match='分镜.*时长'):
        build_story_plan(document, 'plan_story_shots', {'script_node_id': 'script', 'shots': [item, {**item, 'index': 2, 'duration': duration}]})
    assert document == before


@pytest.mark.asyncio
async def test_story_stages_create_text_video_pairs_and_keep_reference_links():
    canvas = Canvas()
    full = await execute_studio_tool('read_canvas', {'node_ids': ['script']}, {}, canvas, allow_write=False)
    assert full['nodes'][0]['data']['text'].endswith('结尾三人结义。')
    result = await execute_studio_tool('plan_story_assets', ASSETS, {}, canvas, allow_write=True)
    assert result['ok'] and canvas.version == 2
    characters = [node for node in canvas.document['nodes'] if node['type'] == 'character']
    scenes = [node for node in canvas.document['nodes'] if node['type'] == 'scene']
    assert len(characters) == len(scenes) == 1
    assert all(not node['data']['prompt'] and node['data']['writingRequirements'] and node['data']['mediaType'] == 'image' for node in characters + scenes)
    assert len(canvas.document['edges']) == 2
    for node in characters + scenes:
        assert node['parentId']
        writer = next(item for item in canvas.document['nodes'] if item['id'] == node['data']['promptNodeId'])
        assert writer['data']['text'] == '' and '创作要求' in writer['data']['writingPrompt']
        assert any(edge['source'] == node['data']['promptNodeId'] and edge['target'] == node['id'] for edge in canvas.document['edges'])
    refs = [node['id'] for node in characters + scenes]
    payload = {'script_node_id': 'script', 'shots': [
        {'index': 1, 'name': '桃园远景', 'description': '远景，平视，三人走入桃园，5秒', 'prompt': '三人走入桃园，全景，清晨，写实电影风格', 'reference_node_ids': refs},
        {'index': 2, 'name': '刘备特写', 'description': '近景，平视，刘备说出誓言，3秒', 'prompt': '刘备在桃园宣誓，特写，柔和侧光，写实电影风格', 'reference_node_ids': refs},
    ]}
    result = await execute_studio_tool('plan_story_shots', payload, {}, canvas, allow_write=True)
    assert result['ok'] and canvas.version == 3
    shots = [node for node in canvas.document['nodes'] if node['data'].get('storyKind') == 'shot_prompt']
    videos = [node for node in canvas.document['nodes'] if node['data'].get('storyKind') == 'shot_video']
    assert len(shots) == len(videos) == 2 and all(node['type'] == 'text' for node in shots)
    assert all(node['type'] == 'videoGeneration' for node in videos)
    assert all(set(node['data']['referenceNodeIds']) == set(refs) for node in shots)
    assert len(canvas.document['edges']) == 12
    assert all(not node['data']['text'] and node['data']['writingPrompt'] for node in shots)
    assert all(any(edge['source'] == ref and edge['target'] == shot['id'] for edge in canvas.document['edges']) for shot in shots for ref in refs)
    assert not any('script' in (edge['source'], edge['target']) for edge in canvas.document['edges'])
    pairs = {(edge['source'], edge['target']) for edge in canvas.document['edges']}
    for video in videos:
        assert (video['data']['promptNodeId'], video['id']) in pairs
        assert all((ref, video['id']) in pairs for ref in refs)
    # Repeating planning preserves media and edited prompts, and creates no duplicate nodes.
    shots[0]['data'].update(text='用户修改后的提示词')
    videos[0]['data'].update(mediaUrl='/existing.mp4')
    await execute_studio_tool('plan_story_shots', payload, {}, canvas, allow_write=True)
    assert len(canvas.document['nodes']) == 12
    groups = [node for node in canvas.document['nodes'] if node['type'] == 'group']
    assert len(groups) == 3
    assert sorted(len(node['data']['children']) for node in groups) == [2, 2, 4]
    assert next(node for node in canvas.document['nodes'] if node['id'] == shots[0]['id'])['data']['text'] == '用户修改后的提示词'
    assert next(node for node in canvas.document['nodes'] if node['id'] == videos[0]['id'])['data']['mediaUrl'] == '/existing.mp4'


@pytest.mark.asyncio
async def test_story_stage_validation_is_atomic_and_requires_edit_permission():
    canvas = Canvas()
    denied = await execute_studio_tool('plan_story_assets', ASSETS, {}, canvas, allow_write=False)
    assert not denied['ok'] and canvas.version == 1
    skipped = await execute_studio_tool('plan_story_shots', {'script_node_id': 'script', 'shots': []}, {}, canvas, allow_write=True)
    assert not skipped['ok'] and '先补齐' in skipped['error']
    invalid = copy.deepcopy(ASSETS)
    invalid['assets'][1]['prompt'] = ''
    result = await execute_studio_tool('plan_story_assets', invalid, {}, canvas, allow_write=True)
    assert not result['ok'] and canvas.version == 1 and len(canvas.document['nodes']) == 1
    await execute_studio_tool('plan_story_assets', ASSETS, {}, canvas, allow_write=True)
    invalid_shot = {'script_node_id': 'script', 'shots': [{'index': 1, 'name': '镜头', 'description': '描述', 'prompt': '提示词', 'reference_node_ids': ['foreign-script-character']}]}
    result = await execute_studio_tool('plan_story_shots', invalid_shot, {}, canvas, allow_write=True)
    assert not result['ok'] and canvas.version == 2


@pytest.mark.asyncio
async def test_completed_planning_stops_at_user_checkpoint_without_another_model_call():
    canvas = Canvas()
    calls = []

    async def complete(*args):
        calls.append(args)
        assert len(calls) == 1
        return json.dumps({'tool': 'plan_story_assets', 'input': ASSETS}, ensure_ascii=False)

    events = [event async for event in iter_agent_turn(view={}, canvas=canvas, prompt='抽取角色与场景', complete=complete, enabled_tools=['read_canvas', 'plan_story_assets'])]
    assert any(event['type'] == 'canvas_updated' for event in events)
    assert '拆分分镜' in events[-1]['content']
    assert not any(event['type'] == 'task_created' for event in events)


def test_legacy_repair_reuses_media_adds_scenes_and_is_repeatable():
    from app.printfilm_studio.agent.story_graph import repair_story_graph
    graph = {'nodes': [
        {'id': 's', 'type': 'script', 'position': {'x': 0, 'y': 0}, 'data': {'label': '剧本', 'text': '场景一：桃园 - 日\n（桃花盛开）刘备走入。'}},
        {'id': 'c', 'type': 'character', 'position': {'x': 400, 'y': 0}, 'data': {'label': '【刘备 · 刘玄德】', 'prompt': '保留角色提示词', 'mediaUrl': '/existing.png'}},
        {'id': 'o', 'type': 'storyboard', 'position': {'x': 800, 'y': 0}, 'data': {'label': '分镜桃园', 'text': '【场景一：桃园 - 日】\n★ 镜头1：全景\n刘备走入桃园，5秒\n★ 镜头2：近景\n刘备抬头，3秒'}},
    ], 'edges': []}
    result = repair_story_graph(graph, 's')
    assert graph['edges'] == [] and len(graph['nodes']) == 3
    nodes = result['nodes']
    assert next(n for n in nodes if n['id'] == 'c')['data']['mediaUrl'] == '/existing.png'
    scenes = [n for n in nodes if n['type'] == 'scene']
    assert len(scenes) == 1 and '桃花盛开' in scenes[0]['data']['writingRequirements']
    prompts = [n for n in nodes if n['data'].get('storyKind') == 'shot_prompt']
    videos = [n for n in nodes if n['data'].get('storyKind') == 'shot_video']
    assert len(prompts) == len(videos) == 2
    pairs = {(e['source'], e['target']) for e in result['edges']}
    for video in videos:
        assert (video['data']['promptNodeId'], video['id']) in pairs
        assert ('c', video['id']) in pairs
        assert (scenes[0]['id'], video['id']) in pairs
    assert repair_story_graph(result, 's') == result
    # Removing a partner and its edges can be repaired without changing text.
    removed = videos[0]['id']
    prompts[0]['data']['text'] = '用户新写的镜头'
    result['nodes'] = [n for n in nodes if n['id'] != removed]
    result['edges'] = [e for e in result['edges'] if e['target'] != removed]
    fixed = repair_story_graph(result, 's')
    assert any(n['id'] == removed for n in fixed['nodes'])
    assert next(n for n in fixed['nodes'] if n['id'] == prompts[0]['id'])['data']['text'] == '用户新写的镜头'


def test_repair_does_not_adopt_unowned_storyboards_in_multi_script_canvas():
    from app.printfilm_studio.agent.story_graph import repair_story_graph
    graph = {'nodes': [
        {'id': 's', 'type': 'script', 'data': {'text': '场景一：桃园 - 日\n刘备结义。'}},
        {'id': 'other', 'type': 'script', 'data': {'text': '另一个故事'}},
        {'id': 'old', 'type': 'storyboard', 'data': {'text': '★ 镜头1：桃园\n刘备', 'label': '分镜'}},
    ], 'edges': []}
    result = repair_story_graph(graph, 's')
    assert next(n for n in result['nodes'] if n['id'] == 'old')['type'] == 'storyboard'
    assert not any(n['data'].get('storyKind') == 'shot_prompt' for n in result['nodes'])
