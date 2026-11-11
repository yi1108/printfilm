from copy import deepcopy
import json

import pytest

from app.printfilm_studio.agent.story_parameters import shot_parameters
from app.printfilm_studio.writing_context import writing_context, parameters_changed, assert_video_binding, linked_writing_result


def graph():
    return {'nodes': [
        {'id': 'writer', 'type': 'text', 'data': {'sourceScriptId': 's', 'text': '已完成', 'writingPrompt': '使用 @[角色](node:role) 拍摄，约5秒。', 'outputNodeId': 'video'}},
        {'id': 'role', 'type': 'character', 'data': {'sourceScriptId': 's', 'label': '角色', 'mediaUrls': ['/old.png', '/chosen.png'], 'mediaIndex': 1}},
        {'id': 'scene', 'type': 'scene', 'data': {'sourceScriptId': 's', 'label': '场景', 'mediaUrl': '/scene.png'}},
        {'id': 'video', 'type': 'videoGeneration', 'data': {'sourceScriptId': 's', 'promptNodeId': 'writer', 'referenceNodeIds': ['role', 'scene'], 'duration': '8', 'ratio': '9:16', 'modelId': 'video-model'}},
    ], 'edges': [{'source': src, 'target': 'video'} for src in ['writer', 'role', 'scene']]}


def test_shot_parameters_use_explicit_values_then_prose_and_reject_invalid_values():
    assert shot_parameters({'prompt': '约8秒，画幅9:16'}, {}) == {'duration': '8', 'ratio': '9:16'}
    assert shot_parameters({'description': '动作，3秒，比例16:9'}, {}) == {'duration': '3', 'ratio': '16:9'}
    assert shot_parameters({'duration': 6, 'ratio': '1:1', 'prompt': '约8秒，9:16'}, {}) == {'duration': '6', 'ratio': '1:1'}
    for value in [0, -1, True, 'nan', 'inf', 121]:
        with pytest.raises(ValueError):
            shot_parameters({'duration': value}, {})
    with pytest.raises(ValueError):
        shot_parameters({'ratio': 'auto'}, {})


def test_writer_uses_current_downstream_parameters_and_selected_reference_images():
    doc = graph()
    prompt, outputs = writing_context(doc['nodes'][0], doc, {'videoModel': 'fallback', 'duration': '5', 'videoRatio': '16:9'})
    assert '@角色' in prompt and '(node:role)' in prompt and '(node:scene)' in prompt
    assert '/chosen.png' in prompt and '/old.png' not in prompt and '/scene.png' in prompt
    assert outputs[0]['model'] == 'video-model'
    assert outputs[0]['duration'] == '8' and outputs[0]['ratio'] == '9:16'
    assert '优先于旧要求' in prompt


def test_changed_parameters_replan_writer_and_prevent_stale_video_submission():
    from app.printfilm_studio.workflow import plan_nodes
    doc = graph()
    writer, video = doc['nodes'][0], doc['nodes'][-1]
    _, outputs = writing_context(writer, doc, {})
    writer['data']['writingOutputSettings'] = deepcopy(outputs)
    assert plan_nodes(doc, ['writer']) == []
    video['data']['duration'] = '10'
    _, changed = writing_context(writer, doc, {})
    assert parameters_changed(writer, changed)
    assert [n['id'] for n in plan_nodes(doc, ['video'])] == ['writer', 'video']
    with pytest.raises(ValueError, match='重新生成'):
        assert_video_binding(writer, video, {'model_id': 'video-model', 'duration': '10', 'ratio': '9:16'})


def test_planning_persists_references_and_timing_in_writer_and_video_atomically():
    from app.printfilm_studio.agent.story_workflow import build_story_plan
    doc = graph()
    doc['nodes'] = [n for n in doc['nodes'] if n['id'] in {'role', 'scene'}]
    doc['nodes'].insert(0, {'id': 's', 'type': 'script', 'position': {'x': 0, 'y': 0}, 'data': {'text': '角色在场景里行动。'}})
    for node in doc['nodes'][1:]:
        node['data']['storyKind'] = node['type']
        node['position'] = {'x': 300, 'y': 0}
    doc['edges'] = []
    shot = {'index': 1, 'name': '抬头', 'prompt': '保持外貌一致，抬头', 'description': '近景抬头', 'duration': 8, 'ratio': '9:16', 'reference_node_ids': ['role', 'scene']}
    result, _ = build_story_plan(doc, 'plan_story_shots', {'script_node_id': 's', 'shots': [shot]})
    video = next(n for n in result['nodes'] if n['data'].get('storyKind') == 'shot_video')
    writer = next(n for n in result['nodes'] if n['id'] == video['data']['promptNodeId'])
    assert video['data']['duration'] == '8' and video['data']['ratio'] == '9:16'
    assert '8 秒，画幅：9:16' in writer['data']['writingPrompt']
    assert '(node:role)' in writer['data']['writingPrompt'] and '(node:scene)' in writer['data']['writingPrompt']
    before = json.dumps(doc)
    with pytest.raises(ValueError):
        build_story_plan(doc, 'plan_story_shots', {'script_node_id': 's', 'shots': [shot, {**shot, 'index': 2, 'duration': -1}]})
    assert json.dumps(doc) == before


@pytest.mark.parametrize('model', ['seedance-2.0', 'seedance-2.5', 'doubao-seedance-2-0-fast-260128'])
def test_seedance_family_switch_does_not_require_rewriting(model):
    writer = {'data': {'writingOutputSettings': [{'id': 'video', 'model': 'seedance-2.0-fast', 'ratio': '16:9', 'duration': '6'}]}}
    params = {'model_id': model, 'ratio': '16:9', 'duration': '6'}
    assert_video_binding(writer, {'id': 'video'}, params)
    for change in [{'duration': '8'}, {'ratio': '9:16'}, {'model_id': 'MiniMax-H3'}]:
        with pytest.raises(ValueError, match='重新生成'):
            assert_video_binding(writer, {'id': 'video'}, {**params, **change})


def test_generated_prose_links_known_images_without_fabricating_identities():
    doc = graph()
    result = linked_writing_result('@角色走进场景。', doc['nodes'][0], doc)
    assert '(node:role)' in result and '(node:scene)' in result
    assert '@@' not in result
    assert linked_writing_result(result, doc['nodes'][0], doc) == result
    assert linked_writing_result('', doc['nodes'][0], doc) == ''
    doc['nodes'][1]['data']['label'] = doc['nodes'][2]['data']['label'] = '人'
    result = linked_writing_result('人群走过。', doc['nodes'][0], doc)
    assert result.startswith('人群走过。\n参考图片：')
    assert '(node:role)' in result and '(node:scene)' in result
