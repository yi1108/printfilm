from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.printfilm_studio.agent.story_workflow import build_story_plan


def assets():
    doc = {'nodes': [{'id': 's', 'type': 'script', 'position': {'x': 0, 'y': 0}, 'data': {'text': '场1：城门 - 日\n等待。\n场2：大殿 - 夜\n交谈。\n场3：城门 - 日\n归来。'}}], 'edges': []}
    doc, _ = build_story_plan(doc, 'plan_story_assets', {'script_node_id': 's', 'assets': [{'kind': 'character', 'name': '甲', 'prompt': '甲的外貌'}]})
    scenes = {node['data']['label']: node['id'] for node in doc['nodes'] if node['type'] == 'scene'}
    assert len(scenes) == 2, 'repeated places reuse one reference image'
    return doc, scenes


def shot(index, scene, number=None):
    return {'index': index, 'name': '动作', 'description': '人物抬头', 'prompt': '固定机位抬头', 'duration': 5, 'ratio': '16:9', 'reference_node_ids': [scene], **({'scene_number': number} if number else {})}


def test_append_and_repeat_preserve_scene_numbers_shot_numbers_and_reference_links():
    doc, scenes = assets()
    doc, _ = build_story_plan(doc, 'plan_story_shots', {'script_node_id': 's', 'shots': [shot(1, scenes['城门']), shot(2, scenes['大殿'])]})
    doc, _ = build_story_plan(doc, 'plan_story_shots', {'script_node_id': 's', 'shots': [shot(3, scenes['大殿'])]})
    videos = sorted((n for n in doc['nodes'] if n['data'].get('storyKind') == 'shot_video'), key=lambda n: n['data']['shotIndex'])
    assert [n['data']['sceneNumber'] for n in videos] == [1, 2, 2]
    assert [n['data']['sceneShotIndex'] for n in videos] == [1, 1, 2]
    before = deepcopy(doc)
    doc, _ = build_story_plan(doc, 'plan_story_shots', {'script_node_id': 's', 'shots': [shot(1, scenes['大殿'])]})
    video = next(n for n in doc['nodes'] if n['id'] == videos[0]['id'])
    assert video['data']['referenceNodeIds'] == [scenes['城门']]
    assert not any(e['source'] == scenes['大殿'] and e['target'] == video['id'] for e in doc['edges'])
    assert len(doc['nodes']) == len(before['nodes'])


def test_returning_to_same_place_can_create_a_separate_scene_group():
    doc, scenes = assets()
    doc, _ = build_story_plan(doc, 'plan_story_shots', {'script_node_id': 's', 'shots': [shot(1, scenes['城门'], 1), shot(2, scenes['大殿'], 2), shot(3, scenes['城门'], 3)]})
    groups = [n for n in doc['nodes'] if n['data'].get('storyKind') == 'shot_video_group']
    assert sorted(n['data']['sceneNumber'] for n in groups) == [1, 2, 3]
    assert all(f"场{n['data']['sceneNumber']} · " in n['data']['label'] for n in groups)
    videos = sorted((n for n in doc['nodes'] if n['data'].get('storyKind') == 'shot_video'), key=lambda n: n['data']['shotIndex'])
    assert [n['data']['label'] for n in videos] == [f'场{number} · 镜头1 · 视频' for number in (1, 2, 3)]
    invalid = shot(4, scenes['城门'])
    invalid['reference_node_ids'].append(scenes['大殿'])
    with pytest.raises(ValueError, match='只能属于一个场景'):
        build_story_plan(doc, 'plan_story_shots', {'script_node_id': 's', 'shots': [invalid]})


@pytest.mark.asyncio
async def test_image_to_video_does_not_replace_video_model_with_image_model(monkeypatch):
    from app.printfilm_studio.integration import media, generation_inputs
    source = {'id': 'image', 'type': 'image', 'position': {'x': 0, 'y': 0}, 'data': {'modelId': 'image-model', 'ratio': '1:1'}}
    doc = {'nodes': [source], 'edges': []}
    task = SimpleNamespace(cancelable=False, payload={})
    canvas = SimpleNamespace(project=SimpleNamespace(id=7, team_id=None), user=SimpleNamespace(id=8), db=SimpleNamespace(info={}, get=AsyncMock(return_value=task), rollback=AsyncMock()), load=AsyncMock(return_value=(doc, 1)), save=AsyncMock(return_value=2))
    enqueue = AsyncMock(return_value={'task_id': 'task', 'platform_task_id': 2})
    monkeypatch.setattr('app.services.studio_generation.enqueue_generation', enqueue)
    monkeypatch.setattr(generation_inputs, 'prepare_inputs', AsyncMock(return_value=([], {})))
    await media.create_media_task(canvas, 'video', '生成视频', node_id='image', model_id='video-model', ratio='16:9', duration='5')
    assert enqueue.call_args.kwargs['params']['model_id'] == 'video-model'
    assert enqueue.call_args.kwargs['params']['ratio'] == '16:9'
