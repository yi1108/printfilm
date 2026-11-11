import copy
import json
import pytest
from app.printfilm_studio.agent.runtime import iter_agent_turn
from app.printfilm_studio.agent.story_workflow import build_story_plan

class Canvas:
    def __init__(self):
        self.document = {'version': 1, 'nodes': [{'id': 's', 'type': 'script', 'position': {'x': 0, 'y': 0}, 'data': {'label': '空城计', 'text': '场景一：城楼 - 日\n诸葛亮抚琴。'}}], 'edges': []}
        self.version = 1
    async def load(self):
        return copy.deepcopy(self.document), self.version
    async def save(self, document):
        self.document = copy.deepcopy(document)
        self.version += 1
        return self.version

@pytest.mark.asyncio
async def test_reviewed_plan_never_writes_canvas_and_emits_paired_groups():
    canvas = Canvas()
    original = copy.deepcopy(canvas.document)
    async def complete(*args):
        return json.dumps({'tool': 'plan_story_assets', 'input': {'script_node_id': 's', 'assets': [{'kind': 'character', 'name': '诸葛亮', 'prompt': '羽扇纶巾'}]}})
    events = [event async for event in iter_agent_turn(view={}, canvas=canvas, prompt='规划角色场景', complete=complete, review_changes=True)]
    assert canvas.document == original and canvas.version == 1
    proposal = next(event['data'] for event in events if event['type'] == 'proposal')
    added = [change['after'] for change in proposal['nodes'] if change['before'] is None]
    assert len(added) == 6
    groups = [node for node in added if node['type'] == 'group']
    assert {node['data']['storyKind'] for node in groups} == {'character_group', 'scene_group'}
    for group in groups:
        assert len(group['data']['children']) == 2
        assert all(node['parentId'] == group['id'] for node in added if node['id'] in group['data']['children'])
    assert len(proposal['edges']) == 2
    assert not any(event['type'] in {'canvas_updated', 'task_created'} for event in events)

@pytest.mark.asyncio
async def test_reviewed_generic_batch_is_atomic_and_respects_permission():
    canvas = Canvas()
    action = {'tool_calls': [{'tool': 'add_canvas_node', 'input': {'node': {'id': 't', 'type': 'text', 'data': {'text': '剧本'}}}}, {'tool': 'connect_canvas_nodes', 'input': {'source': 'missing', 'target': 't'}}]}
    async def complete(*args): return json.dumps(action)
    events = [event async for event in iter_agent_turn(view={}, canvas=canvas, prompt='创建', complete=complete, review_changes=True)]
    assert any(event['type'] == 'error' for event in events)
    assert not any(event['type'] == 'proposal' for event in events)
    assert len(canvas.document['nodes']) == 1
    action['tool_calls'].pop()
    events = [event async for event in iter_agent_turn(view={}, canvas=canvas, prompt='创建', complete=complete, review_changes=True, allow_write=False)]
    assert not any(event['type'] == 'proposal' for event in events)


def test_layout_is_repeatable_and_preserves_edited_prompt_media_and_group_position():
    canvas = Canvas()
    payload = {'script_node_id': 's', 'assets': [{'kind': 'character', 'name': '诸葛亮', 'prompt': '羽扇纶巾'}]}
    document, _ = build_story_plan(canvas.document, 'plan_story_assets', payload)
    role = next(node for node in document['nodes'] if node['type'] == 'character')
    prompt = next(node for node in document['nodes'] if node['id'] == role['data']['promptNodeId'])
    prompt['data']['text'] = '用户修改后的外貌'
    role['data']['mediaUrl'] = '/completed.png'
    group = next(node for node in document['nodes'] if node['id'] == role['parentId'])
    group['position'] = {'x': 880, 'y': 1200}
    repeated, _ = build_story_plan(document, 'plan_story_assets', payload)
    assert repeated == document


@pytest.mark.asyncio
async def test_ambiguous_scene_is_corrected_before_emitting_one_proposal():
    canvas = Canvas()
    canvas.document, _ = build_story_plan(canvas.document, 'plan_story_assets', {'script_node_id':'s','assets':[{'kind':'scene','name':'桃园','prompt':'桃园环境'},{'kind':'scene','name':'酒肆','prompt':'酒肆环境'}]})
    scene = next(n for n in canvas.document['nodes'] if n['data'].get('label') == '桃园')
    original = copy.deepcopy(canvas.document)
    calls = []
    async def complete(system, context):
        calls.append(context)
        shot = {'index':1,'name':'结义','description':'三人举杯','prompt':'三人举杯','reference_node_ids':[]}
        if len(calls) > 1:
            assert scene['id'] in context
            shot['scene_node_id'] = scene['id']
        return json.dumps({'tool':'plan_story_shots','input':{'script_node_id':'s','shots':[shot]}})
    events = [event async for event in iter_agent_turn(view={},canvas=canvas,prompt='规划分镜',complete=complete,review_changes=True)]
    assert len(calls) == 2
    assert len([e for e in events if e['type']=='proposal']) == 1
    assert not any(e['type']=='error' for e in events)
    assert canvas.document == original


def test_scene_omission_matches_unique_name_but_never_a_foreign_scene():
    from app.printfilm_studio.agent.story_references import shot_references
    refs = {key:{'id':key,'data':{'sourceScriptId':'s','storyKind':'scene','label':label}} for key,label in [('garden','桃园'),('inn','酒肆')]}
    item={'name':'宣誓','prompt':'三人在桃园举杯','reference_node_ids':[]}
    assert shot_references(item,refs,'s') == ['garden']
    item['prompt']='三人举杯'
    with pytest.raises(ValueError,match='尚未明确'):
        shot_references(item,refs,'s')
    item['reference_node_ids']=['foreign']
    with pytest.raises(ValueError,match='当前剧本'):
        shot_references(item,refs,'s')


def test_same_shot_number_in_different_episodes_and_large_script_layout():
    canvas=Canvas()
    canvas.document['nodes'][0].update(width=1200,height=780)
    doc,_=build_story_plan(canvas.document,'plan_story_assets',{'script_node_id':'s','assets':[{'kind':'scene','name':'城楼','prompt':'城楼'}]})
    scene=next(n for n in doc['nodes'] if n['type']=='scene')
    assert next(n for n in doc['nodes'] if n['id']==scene['parentId'])['position']['x'] >= 1320
    shots=[{'index':1,'episodeNumber':ep,'name':'城楼','prompt':'城楼远景','description':'空镜','reference_node_ids':[scene['id']]} for ep in [1,2]]
    result,_=build_story_plan(doc,'plan_story_shots',{'script_node_id':'s','shots':shots})
    videos=[n for n in result['nodes'] if n['type']=='videoGeneration']
    assert len(videos)==2 and len({n['id'] for n in videos})==2
    assert videos[0]['parentId'] != videos[1]['parentId']
    assert build_story_plan(result,'plan_story_shots',{'script_node_id':'s','shots':shots})[0] == result
