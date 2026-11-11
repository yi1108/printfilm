import pytest
import json

from app.printfilm_studio.agent.actions import split_assistant_action
from app.printfilm_studio.agent.executor import execute_studio_tool
from app.printfilm_studio.agent.runtime import iter_agent_turn


class MemoryCanvas:
    """记录助手写回的画布版本。"""

    def __init__(self) -> None:
        self.document = {"version": 1, "nodes": [{"id": "n1", "type": "text", "data": {"label": "开场"}}], "edges": []}
        self.version = 3

    async def load(self):
        return self.document, self.version

    async def save(self, document):
        self.document = document
        self.version += 1
        return self.version


def test_split_keeps_visible_text_and_canvas_action():
    visible, action = split_assistant_action('先加一个节点。\n```json\n{"canvas_operations": [{"op": "add_node", "node": {"id": "n2", "type": "text"}}]}\n```')
    assert visible == "先加一个节点。"
    assert action["canvas_operations"][0]["op"] == "add_node"


def test_split_ignores_plain_json_without_action():
    visible, action = split_assistant_action('{"reply": "只是说明"}')
    assert action is None
    assert "说明" in visible


def test_split_extracts_bare_actions_after_prose_without_reading_nested_examples():
    call = {'tool': 'add_canvas_node', 'input': {'type': 'script', 'text': '第一场\n桃园结义'}}
    visible, action = split_assistant_action('先创建剧本节点：\n\n' + json.dumps([call], ensure_ascii=False))
    assert visible == '先创建剧本节点：'
    assert action == {'tool_calls': [call]}
    example = '这是数据示例：\n' + json.dumps({'example': call}, indent=2)
    assert split_assistant_action(example) == (example, None)
    fenced_example = '```text\n' + json.dumps(call) + '\n```'
    assert split_assistant_action(fenced_example) == (fenced_example, None)


@pytest.mark.asyncio
@pytest.mark.parametrize('streamed', [False, True])
@pytest.mark.parametrize('enabled', [True, False])
async def test_prose_followed_by_script_action_creates_node_without_leaking_json(streamed, enabled):
    canvas = MemoryCanvas()
    reply = '正在创建剧本。\n\n' + json.dumps([{'tool': 'add_canvas_node', 'input': {
        'type': 'script', 'label': '桃园结义', 'text': '第一场：桃园\n刘备、关羽、张飞结义。',
    }}], ensure_ascii=False)
    replies = iter([reply, '剧本节点已创建。'])

    async def complete(*_):
        return next(replies)

    async def stream(*_):
        for character in next(replies):
            yield character

    events = [event async for event in iter_agent_turn(
        view={'id': 1, 'workflow': 'canvas', 'episodes': []}, canvas=canvas,
        prompt='写一段桃园结义的剧本，直接放到画布', complete=complete,
        stream=stream if streamed else None, enabled_tools=['add_canvas_node'] if enabled else ['read_canvas'],
    )]
    visible = ''.join(event.get('content', '') for event in events if event['type'] == 'message_delta')
    assert '"tool"' not in visible and '"input"' not in visible
    assert canvas.version == (4 if enabled else 3)
    scripts = [node for node in canvas.document['nodes'] if node['type'] == 'script']
    assert len(scripts) == (1 if enabled else 0)
    if enabled:
        assert scripts[0]['data']['text'] == '第一场：桃园\n刘备、关羽、张飞结义。'
        assert any(event['type'] == 'canvas_updated' for event in events)
    else:
        assert '需要启用' in visible


@pytest.mark.asyncio
async def test_canvas_tool_updates_memory_canvas_and_blocks_closed_generation():
    canvas = MemoryCanvas()
    view = {"id": 1, "title": "试播", "description": "", "workflow": "canvas", "episodes": [], "assets": [], "tasks": []}
    created = await execute_studio_tool("add_canvas_node", {"type": "image", "text": "城门"}, view, canvas, allow_write=True)
    assert created["ok"] is True
    assert canvas.version == 4

    assert any(node["type"] == "image" for node in canvas.document["nodes"])
    # Media creation remains behind the existing scheduler and billing boundary;
    # this unit test only verifies that unsupported canvas input is rejected.
    invalid = await execute_studio_tool("create_image_task", {"prompt": ""}, view, canvas, allow_write=True)
    assert invalid["ok"] is False
    denied = await execute_studio_tool("add_canvas_node", {"type": "text"}, view, canvas, allow_write=False)
    assert "编辑权" in denied["error"]


@pytest.mark.asyncio
async def test_agent_turn_applies_tool_then_answers():
    canvas = MemoryCanvas()
    view = {"id": 1, "title": "试播", "description": "", "workflow": "canvas", "assets": [], "episodes": [], "tasks": []}
    answers = iter([
        '{"tool":"add_canvas_node","input":{"type":"script","text":"第一场"}}',
        "已经加上剧本节点。",
    ])

    async def complete(_system: str, _user: str) -> str:
        return next(answers)

    events = [event async for event in iter_agent_turn(view=view, canvas=canvas, prompt="加一场", complete=complete)]
    assert events[0] == {"type": "tool_start", "tool": "add_canvas_node", "call_id": "0", "data": {"type": "script", "text": "第一场"}}
    assert events[1]["call_id"] == events[0]["call_id"]
    assert events[1]["type"] == "tool_result"
    assert events[2]["type"] == "canvas_updated"
    assert events[3] == {"type": "message_delta", "content": "已经加上剧本节点。"}
    assert canvas.version == 4


@pytest.mark.asyncio
async def test_disabled_tool_and_legacy_patch_cannot_mutate_canvas():
    for response in ['{"tool":"add_canvas_node","input":{"type":"text","text":"no"}}', '{"canvas_operations":[{"op":"remove_node","node_id":"n1"}]}']:
        canvas = MemoryCanvas()
        async def complete(*_args): return response
        events = [event async for event in iter_agent_turn(view={"id": 1}, canvas=canvas, prompt="change", enabled_tools=['read_canvas'], complete=complete)]
        assert canvas.version == 3
        assert any(event.get('ok') is False for event in events)

