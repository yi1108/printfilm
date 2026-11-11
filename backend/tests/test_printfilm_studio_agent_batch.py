"""Regression for the tool arrays that previously appeared as chat instead of nodes."""
import copy
import json

import pytest

from app.printfilm_studio.agent.actions import split_assistant_action
from app.printfilm_studio.agent.executor import execute_canvas_tool_batch, execute_studio_tool
from app.printfilm_studio.agent.runtime import iter_agent_turn
from app.printfilm_studio.agent.streaming import VisibleReplyBuffer


class Canvas:
    def __init__(self):
        self.document = {'version': 1, 'nodes': [], 'edges': [], 'viewport': {'x': 700, 'y': -1400, 'zoom': .5}}
        self.version = 10
        self.saves = 0

    async def load(self):
        return copy.deepcopy(self.document), self.version

    async def save(self, document):
        self.document = document
        self.version += 1
        self.saves += 1
        return self.version


def add(node_id, kind='text'):
    return {'tool': 'add_canvas_node', 'input': {'node': {'id': node_id, 'type': kind, 'data': {'label': node_id}}}}


@pytest.mark.parametrize('fenced', [False, True])
def test_action_arrays_and_stream_chunks_stay_out_of_chat(fenced):
    calls = [add('a', 'scene'), add('b')]
    raw = json.dumps(calls)
    raw = '正在添加。\n```json\n' + raw + '\n```' if fenced else raw
    buffer = VisibleReplyBuffer()
    visible = ''.join(buffer.push(character) for character in raw)
    text, action = split_assistant_action(raw)
    visible += buffer.remainder(text)
    assert visible == ('正在添加。' if fenced else '')
    assert action == {'tool_calls': calls}


def test_multiple_action_fences_preserve_ordinary_json():
    example = '```json\n{"title":"example"}\n```'
    visible, action = split_assistant_action(example + '\n```json\n' + json.dumps(add('a')) + '\n```\n```json\n' + json.dumps(add('b')) + '\n```')
    assert visible == example
    assert action['tool_calls'] == [add('a'), add('b')]
    assert split_assistant_action('[{"title":"example"}]')[1] is None


@pytest.mark.asyncio
async def test_batch_creates_nodes_and_connections_in_one_version():
    canvas = Canvas()
    calls = [add('a', 'scene'), add('b'), {'tool': 'connect_canvas_nodes', 'input': {'source': 'a', 'target': 'b'}}]
    answers = iter(['我来添加。\n```json\n' + json.dumps(calls) + '\n```', '已添加并连接。'])
    async def complete(*_):
        return next(answers)
    events = [e async for e in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete)]
    assert canvas.saves == 1 and canvas.version == 11
    assert len(canvas.document['nodes']) == 2 and len(canvas.document['edges']) == 1
    a, b = canvas.document['nodes']
    assert a['position'] == {'x': -1160, 'y': 3040}
    assert a['position'] != b['position']
    assert [e['call_id'] for e in events if e['type'] == 'tool_result'] == ['0', '1', '2']
    patches = [e for e in events if e['type'] == 'canvas_patch']
    assert len(patches) == 1 and patches[0]['base_version'] == 10
    assert len(patches[0]['operations']) == 3
    assert 'tool' not in ''.join(e.get('content', '') for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize('allow_write,second', [
    (False, add('b')),
    (True, {'tool': 'connect_canvas_nodes', 'input': {'source': 'a', 'target': 'missing'}}),
    (True, add('a')),
])
async def test_batch_failure_never_persists_partial_nodes(allow_write, second):
    canvas = Canvas()
    result = await execute_canvas_tool_batch([add('a'), second], canvas, allow_write=allow_write)
    assert result['ok'] is False
    assert canvas.saves == 0 and canvas.document['nodes'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('calls', [
    [add('a'), {'tool': 'unknown', 'input': {}}],
    [add('a'), {'tool': 'remove_canvas_node', 'input': {}}],
    [add(str(i)) for i in range(13)],
])
async def test_invalid_batch_is_rejected_before_any_tool(calls):
    canvas = Canvas()
    async def complete(*_): return json.dumps(calls)
    events = [e async for e in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete)]
    assert events[0]['code'] == 'invalid_tool_action'
    assert canvas.saves == 0


@pytest.mark.asyncio
async def test_disabled_tool_in_batch_blocks_whole_batch():
    canvas = Canvas()
    async def complete(*_): return json.dumps([add('a'), {'tool': 'remove_canvas_node', 'input': {'node_id': 'a'}}])
    events = [e async for e in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete, enabled_tools=['add_canvas_node'])]
    assert any(e.get('ok') is False for e in events)
    assert canvas.saves == 0


def patch_add(node_id):
    return {'op': 'add_node', 'node': {'id': node_id, 'type': 'text', 'data': {'label': node_id}}}


@pytest.mark.asyncio
@pytest.mark.parametrize('operations', [
    [], None, 'invalid', [None], [patch_add('a'), 'invalid'],
    [{'op': 'add_node', 'node': {}}],
    [{'op': 'update_node', 'node_id': 'a', 'changes': []}],
    [{'op': 'remove_node'}], [{'op': 'remove_edge'}],
    [{'op': 'connect_canvas_nodes', 'edge': {}}], [{'op': 'unknown'}],
    [patch_add(str(i)) for i in range(21)],
])
async def test_invalid_legacy_patch_reports_error_and_never_writes(operations):
    canvas = Canvas()
    async def complete(*_): return json.dumps({'canvas_operations': operations})
    events = [e async for e in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete)]
    assert canvas.saves == 0
    assert not any(e['type'] in {'tool_start', 'canvas_patch', 'canvas_updated'} for e in events)
    assert any(e.get('code') == 'invalid_tool_action' for e in events)
    assert any('操作未执行' in e.get('content', '') for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize('operations', [[None], [patch_add(str(i)) for i in range(21)]])
async def test_legacy_executor_rejects_invalid_patch_without_truncation(operations):
    canvas = Canvas()
    result = await execute_studio_tool('apply_canvas_operations', {'canvas_operations': operations}, {}, canvas, allow_write=True)
    assert result['ok'] is False and canvas.saves == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('action', [
    [add('a'), None],
    [add('a'), {'input': {}}],
    {'tool_calls': [add('a'), {'tool': 'read_canvas', 'input': []}]},
    {'tool': 'read_canvas', 'input': {}, 'canvas_operations': [patch_add('a')]},
    {'tool_calls': [add('a')], 'canvas_operations': [patch_add('b')]},
])
async def test_malformed_or_mixed_action_envelopes_are_rejected(action):
    canvas = Canvas()
    async def complete(*_): return json.dumps(action)
    events = [e async for e in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete)]
    assert canvas.saves == 0
    assert any(e.get('code') == 'invalid_tool_action' for e in events)


@pytest.mark.asyncio
async def test_legacy_patch_events_match_successful_commit_and_unique_call_ids():
    canvas = Canvas()
    operations = [patch_add(str(i)) for i in range(20)]
    answers = iter([json.dumps([add('a'), add('b')]), json.dumps({'canvas_operations': operations})])
    async def complete(*_): return next(answers)
    events = [e async for e in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete)]
    assert canvas.saves == 2 and len(canvas.document['nodes']) == 22
    assert [e['call_id'] for e in events if e['type'] == 'tool_start'] == ['0', '1', '2']
    patches = [e for e in events if e['type'] == 'canvas_patch']
    assert patches[-1]['base_version'] == 11 and patches[-1]['operations'] == operations


@pytest.mark.asyncio
async def test_legacy_patch_cannot_bypass_disabled_write_tool():
    canvas = Canvas()
    async def complete(*_): return json.dumps({'canvas_operations': [patch_add('a')]})
    events = [e async for e in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete, enabled_tools=['read_canvas', 'update_canvas_node', 'remove_canvas_node', 'connect_canvas_nodes'])]
    assert canvas.saves == 0
    assert any(e.get('ok') is False for e in events)
    assert not any(e['type'] == 'canvas_patch' for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize('calls', [[], [None], [add('a'), None], [add(str(i)) for i in range(13)]])
async def test_direct_batch_executor_validates_its_own_boundary(calls):
    canvas = Canvas()
    result = await execute_canvas_tool_batch(calls, canvas, allow_write=True)
    assert result['ok'] is False and canvas.saves == 0


@pytest.mark.asyncio
async def test_stop_after_batch_announced_does_not_write_or_broadcast_patch():
    canvas = Canvas()
    stopped = False
    async def complete(*_): return json.dumps([add('a'), add('b')])
    events = []
    async for event in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete, stopped=lambda: stopped):
        events.append(event)
        if event['type'] == 'tool_start':
            stopped = True
    assert canvas.saves == 0
    assert not any(e['type'] in {'canvas_patch', 'canvas_updated'} for e in events)


@pytest.mark.asyncio
async def test_bad_coordinate_rejects_whole_batch_with_readable_failure():
    canvas = Canvas()
    malformed = add('b')
    malformed['input']['node']['position'] = {'x': 10 ** 400, 'y': 0}
    result = await execute_canvas_tool_batch([add('a'), malformed], canvas, allow_write=True)
    assert result['ok'] is False and result['error']
    assert canvas.saves == 0


@pytest.mark.asyncio
async def test_batch_updates_and_removes_nodes_without_leaving_dangling_edges():
    canvas = Canvas()
    result = await execute_canvas_tool_batch([
        add('a'), add('b'),
        {'tool': 'update_canvas_node', 'input': {'node_id': 'a', 'changes': {'data': {'description': 'kept'}}, 'text': 'rewritten', 'label': 'renamed'}},
        {'tool': 'connect_canvas_nodes', 'input': {'source': 'a', 'target': 'b'}},
        {'tool': 'remove_canvas_node', 'input': {'node_id': 'b'}},
    ], canvas, allow_write=True)
    assert result['ok'] is True and canvas.saves == 1
    assert canvas.document['edges'] == []
    assert [n['id'] for n in canvas.document['nodes']] == ['a']
    assert canvas.document['nodes'][0]['data'] == {'label': 'renamed', 'description': 'kept', 'text': 'rewritten'}


@pytest.mark.asyncio
async def test_legacy_patch_updates_nodes_and_removes_connections_atomically():
    canvas = Canvas()
    operations = [patch_add('a'), patch_add('b'),
                  {'op': 'connect_canvas_nodes', 'edge': {'source': 'a', 'target': 'b'}},
                  {'op': 'update_node', 'node_id': 'a', 'changes': {'data': {'text': 'updated'}}},
                  {'op': 'remove_edge', 'edge_id': 'a->b'}]
    result = await execute_studio_tool('apply_canvas_operations', {'canvas_operations': operations}, {}, canvas, allow_write=True)
    assert result['ok'] is True and result['operations'] == operations and canvas.saves == 1
    assert len(canvas.document['nodes']) == 2 and canvas.document['edges'] == []
    assert canvas.document['nodes'][0]['data']['text'] == 'updated'


@pytest.mark.asyncio
async def test_multiple_fences_cannot_hide_a_mixed_action_envelope():
    canvas = Canvas()
    mixed = {'tool': 'add_canvas_node', 'input': add('ignored')['input'], 'tool_calls': [add('a')]}
    async def complete(*_): return '```json\n' + json.dumps(mixed) + '\n```\n```json\n' + json.dumps(add('b')) + '\n```'
    events = [e async for e in iter_agent_turn(view={}, canvas=canvas, prompt='add', complete=complete)]
    assert canvas.saves == 0
    assert any(e.get('code') == 'invalid_tool_action' for e in events)
