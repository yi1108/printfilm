import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.printfilm_studio.agent.runtime import iter_agent_turn
from app.printfilm_studio.integration import llm_stream
from app.services import llm_client


class TransportChunks(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content
        self.closed = False

    async def __aiter__(self):
        # Split JSON, SSE separators and multibyte Chinese characters.
        for offset in range(0, len(self.content), 7):
            yield self.content[offset:offset + 7]

    async def aclose(self):
        self.closed = True


def chunk(content='', **choice):
    return 'data: ' + json.dumps({'choices': [{'index': 0, 'delta': {'content': content}, **choice}]}, ensure_ascii=False) + '\n\n'


@pytest.fixture
def transport(monkeypatch):
    requests = []
    monkeypatch.setattr(llm_client, 'get_settings', lambda: SimpleNamespace(model_llm='kimi-test'))
    monkeypatch.setattr(llm_client, 'resolve_upstream_model', lambda *_: 'kimi-test')
    monkeypatch.setattr(llm_client, 'resolve_logical_model_id', lambda *_: 'logical-test')
    monkeypatch.setattr(llm_client, 'resolve_logical_model', lambda *_: SimpleNamespace(
        api_key='test-key', base_url='https://channel.test/v1/', upstream_model='kimi-test'))
    client_type = httpx.AsyncClient

    def configure(body, status=200, content_type='text/event-stream'):
        source = TransportChunks(body.encode('utf-8'))

        def respond(request):
            requests.append(request)
            return httpx.Response(status, headers={'content-type': content_type}, stream=source)

        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(
            transport=httpx.MockTransport(respond), **kwargs))
        return source

    return configure, requests


@pytest.mark.asyncio
async def test_real_sse_transport_uses_managed_model_and_only_visible_deltas(transport):
    configure, requests = transport
    source = configure(': heartbeat\n\n' +
        'data: {"choices":[{"delta":{"reasoning_content":"private"}}]}\n\n' +
        chunk('你好') + chunk('，画布已读取。') + chunk(finish_reason='stop') + 'data: [DONE]\n\n')
    result = [part async for part in llm_stream.chat_completions_stream('system', 'user', model_id='logical-test', temperature=.9)]
    assert result == ['你好', '，画布已读取。']
    assert source.closed
    request = requests[0]
    assert str(request.url) == 'https://channel.test/v1/chat/completions'
    assert request.headers['Authorization'] == 'Bearer test-key'
    payload = json.loads(request.content)
    assert payload['model'] == 'kimi-test' and payload['stream'] is True
    assert payload['temperature'] == .6 and payload['thinking'] == {'type': 'disabled'}


@pytest.mark.asyncio
@pytest.mark.parametrize('body,status', [
    (chunk('未结束'), 200),
    (chunk('截断') + chunk(finish_reason='length') + 'data: [DONE]\n\n', 200),
    ('data: {"error":{"message":"provider failed"}}\n\n', 200),
    ('data: not json\n\n', 200),
    ('service unavailable', 503),
])
async def test_sse_failures_are_not_successful_completions(transport, body, status):
    configure, _ = transport
    source = configure(body, status)
    with pytest.raises(RuntimeError):
        _ = [part async for part in llm_stream.chat_completions_stream('s', 'u')]
    assert source.closed


@pytest.mark.asyncio
async def test_json_compatible_fallback_does_not_fake_streaming_or_reveal_reasoning(transport):
    configure, _ = transport
    configure(json.dumps({'choices': [{'message': {'content': '完整回复', 'reasoning_content': 'hidden'}}]}), content_type='application/json')
    assert [p async for p in llm_stream.chat_completions_stream('s', 'u')] == ['完整回复']
    configure(json.dumps({'choices': [{'message': {'reasoning_content': 'hidden'}}]}), content_type='application/json')
    with pytest.raises(RuntimeError, match='正文'):
        _ = [p async for p in llm_stream.chat_completions_stream('s', 'u')]


@pytest.mark.asyncio
async def test_nonstream_writing_rejects_truncated_or_reasoning_only_responses(transport):
    configure, requests = transport
    for choice in [
        {'finish_reason': 'length', 'message': {'content': '未完成'}},
        {'finish_reason': 'stop', 'message': {'reasoning_content': '内部思考'}},
    ]:
        configure(json.dumps({'choices': [choice]}), content_type='application/json')
        with pytest.raises(RuntimeError, match='正文'):
            await llm_client.chat_completions('s', 'u', strict_output=True)
    configure(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '完整正文'}}]}), content_type='application/json')
    assert await llm_client.chat_completions('s', 'u', strict_output=True) == '完整正文'
    assert not json.loads(requests[-1].content).get('stream', False)


@pytest.mark.asyncio
async def test_stop_finish_reason_finishes_without_waiting_for_provider_disconnect(transport):
    configure, _ = transport
    source = configure(chunk('完成正文') + chunk(finish_reason='stop') + 'data: invalid trailing data\n\n')
    assert [p async for p in llm_stream.chat_completions_stream('s','u')] == ['完成正文']
    assert source.closed


@pytest.mark.asyncio
async def test_heartbeats_cannot_keep_a_text_request_alive_forever(monkeypatch):
    closed = asyncio.Event()
    async def stuck(*args, **kwargs):
        try:
            await asyncio.Event().wait()
            yield 'never'
        finally:
            closed.set()
    monkeypatch.setattr(llm_stream, '_chat_completions_stream', stuck)
    with pytest.raises(RuntimeError, match='响应超时'):
        _ = [p async for p in llm_stream.chat_completions_stream('s','u',timeout=.02)]
    assert closed.is_set()


def canvas():
    return SimpleNamespace(load=AsyncMock(return_value=({'nodes': [], 'edges': []}, 1)))


@pytest.mark.asyncio
async def test_writing_waits_for_complete_response_and_excludes_other_canvas_shots():
    gate = asyncio.Event()
    started = asyncio.Event()
    seen = []

    async def complete(system, prompt):
        seen.append((system, prompt))
        started.set()
        await gate.wait()
        return '画面：大军向北行进。\n运镜：高位俯拍，缓慢横移。\n环境声：脚步声。\n台词：无'

    other = SimpleNamespace(load=AsyncMock(return_value=({'nodes': [
        {'id': 'other-shot', 'type': 'text', 'data': {'text': '另一个镜头的秘密剧情', 'label': '无关镜头'}}
    ], 'edges': []}, 1)))
    turn = iter_agent_turn(view={}, canvas=other, prompt='当前镜头：大军向北行进，4秒。', enabled_tools=[], complete=complete)
    pending = asyncio.create_task(anext(turn))
    await asyncio.wait_for(started.wait(), 1)
    assert not pending.done(), 'no partial output before the model finishes'
    assert '无关镜头' not in seen[0][1] and '画布摘要' not in seen[0][1]
    assert '当前镜头：大军向北行进' in seen[0][1]
    assert '工具参数说明' not in seen[0][0]
    gate.set()
    result = await asyncio.wait_for(pending, 1)
    assert result['type'] == 'message_delta' and result['content'].endswith('台词：无')
    assert [item async for item in turn] == []


@pytest.mark.asyncio
async def test_runtime_yields_before_model_finishes_without_duplicate_text():
    gate = asyncio.Event()

    async def stream(*_):
        yield '正文已经开始'
        await gate.wait()
        yield '，现在完成。'

    turn = iter_agent_turn(view={}, canvas=canvas(), prompt='x', stream=stream)
    first = await asyncio.wait_for(anext(turn), 1)
    assert first == {'type': 'message_delta', 'content': '正文已经开始'}
    gate.set()
    rest = [e async for e in turn]
    assert ''.join(e['content'] for e in [first, *rest]) == '正文已经开始，现在完成。'


@pytest.mark.asyncio
@pytest.mark.parametrize('fenced', [False, True])
async def test_tool_only_executes_after_full_stream_and_json_stays_hidden(monkeypatch, fenced):
    import app.printfilm_studio.agent.runtime as runtime
    gate = asyncio.Event()
    executor = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(runtime, 'execute_studio_tool', executor)
    answer = '{"tool":"read_canvas","input":{}}'
    if fenced:
        answer = '正在查看。\n```json\n' + answer + '\n```'
    calls = 0

    async def stream(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            for character in answer:
                yield character
            await gate.wait()  # Even complete JSON cannot run before EOF.
        else:
            yield '查看完成。'

    events = []

    async def consume():
        async for event in iter_agent_turn(view={}, canvas=canvas(), prompt='x', stream=stream):
            events.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(.05)
    assert not task.done() and executor.await_count == 0
    assert all('tool' not in e.get('content', '') for e in events)
    gate.set()
    await asyncio.wait_for(task, 2)
    assert executor.await_count == 1
    text = ''.join(e.get('content', '') for e in events)
    assert text == ('正在查看。' if fenced else '') + '查看完成。'
    assert [e['type'] for e in events if e['type'].startswith('tool_')] == ['tool_start', 'tool_result']


@pytest.mark.asyncio
async def test_stop_cancels_stream_read_and_closes_connection():
    stop = asyncio.Event()
    waiting = asyncio.Event()
    closed = asyncio.Event()

    async def stream(*_):
        try:
            yield '正在处理'
            waiting.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    events = []

    async def consume():
        async for event in iter_agent_turn(view={}, canvas=canvas(), prompt='x', stream=stream, stopped=stop.is_set):
            events.append(event)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(waiting.wait(), 1)
    stop.set()
    await asyncio.wait_for(task, 1)
    assert closed.is_set()
    assert events == [{'type': 'message_delta', 'content': '正在处理'}]


@pytest.mark.asyncio
async def test_broken_stream_never_executes_a_buffered_tool(monkeypatch):
    import app.printfilm_studio.agent.runtime as runtime
    executor = AsyncMock()
    monkeypatch.setattr(runtime, 'execute_studio_tool', executor)

    async def stream(*_):
        yield '{"tool":"add_canvas_node","input":{"type":"text"}}'
        raise RuntimeError('connection reset')

    with pytest.raises(RuntimeError, match='connection reset'):
        _ = [e async for e in iter_agent_turn(view={}, canvas=canvas(), prompt='x', stream=stream)]
    executor.assert_not_awaited()
