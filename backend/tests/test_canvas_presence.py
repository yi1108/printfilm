"""Awareness transport does not write canvas documents or trust client identities."""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException, WebSocketDisconnect

from app.printfilm_studio import presence


class Socket:
    def __init__(self):
        self.input = asyncio.Queue()
        self.output = asyncio.Queue()

    async def accept(self):
        pass

    async def receive_text(self):
        value = await self.input.get()
        if value is None:
            raise WebSocketDisconnect()
        return json.dumps(value)

    async def send_json(self, value):
        await self.output.put(value)

    async def close(self, code):
        await self.output.put({'close': code})

    async def until(self, predicate):
        async def consume():
            while True:
                result = await self.output.get()
                if predicate(result):
                    return result
        return await asyncio.wait_for(consume(), 2)


@pytest.fixture
def rooms(monkeypatch):
    state, subscribers = {}, {}

    class Room:
        def __init__(self, project):
            self.project, self.events = project, asyncio.Queue()
            state.setdefault(project, {})
            subscribers.setdefault(project, [])

        async def subscribe(self):
            subscribers[self.project].append(self.events)

        async def snapshot(self):
            return list(state[self.project].values())

        async def notify(self):
            for queue in subscribers[self.project]:
                await queue.put(True)

        async def update(self, session, identity, awareness):
            state[self.project][session] = {**identity, **awareness.model_dump(), 'session_id': session}
            await self.notify()

        async def remove(self, session):
            state[self.project].pop(session, None)
            await self.notify()

        async def changes(self):
            while True:
                await self.events.get()
                yield None

        async def close(self):
            subscribers[self.project].remove(self.events)

    async def authorize(project, token):
        if token != 'member':
            raise HTTPException(403, 'not a member')
        return {'user_id': 7, 'name': '成员', 'color': '#123456'}

    monkeypatch.setattr(presence, 'RedisRoom', Room)
    monkeypatch.setattr(presence, 'authorize', authorize)
    return state


@asynccontextmanager
async def connection(project=1, token='member'):
    socket = Socket()
    task = asyncio.create_task(presence.canvas_presence(socket, project))
    await socket.input.put({'token': token})
    try:
        yield socket
    finally:
        await socket.input.put(None)
        await asyncio.wait_for(task, 2)


@pytest.mark.asyncio
async def test_two_sessions_relay_drag_and_leave_without_crossing_rooms(rooms):
    async with connection() as first, connection(project=2) as isolated:
        first_initial = await first.until(lambda value: 'peers' in value)
        await isolated.until(lambda value: 'peers' in value)
        async with connection() as second:
            joined = await second.until(lambda value: len(value.get('peers', [])) == 2)
            # Same logged-in user in another browser is a distinct collaborator.
            assert len({peer['session_id'] for peer in joined['peers']}) == 2
            await first.input.put({'cursor': {'x': 120, 'y': -40}, 'action': 'dragging',
                                   'node_ids': ['image-1'], 'positions': [{'id': 'image-1', 'x': 20, 'y': 30}]})
            moved = await second.until(lambda value: any(peer['action'] == 'dragging' for peer in value.get('peers', [])))
            actor = next(peer for peer in moved['peers'] if peer['action'] == 'dragging')
            assert actor['session_id'] == first_initial['self_id']
            assert actor['cursor'] == {'x': 120, 'y': -40}
            assert actor['positions'][0]['id'] == 'image-1'
            assert len(rooms[2]) == 1
        await first.until(lambda value: len(value.get('peers', [])) == 1)
    assert not rooms[1] and not rooms[2]


@pytest.mark.asyncio
async def test_access_denied_before_join(rooms):
    async with connection(token='outsider') as socket:
        assert await socket.until(lambda value: 'close' in value) == {'close': 4403}
    assert not rooms


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    {'name': '伪造身份'}, {'cursor': {'x': float('nan'), 'y': 0}},
    {'node_ids': ['x'] * 33}, {'node_ids': ['']}, {'positions': [{'id': 'x', 'x': 1e20, 'y': 0}]},
])
async def test_invalid_state_closes_without_broadcast(rooms, payload):
    async with connection() as socket:
        await socket.until(lambda value: 'peers' in value)
        await socket.input.put(payload)
        assert await socket.until(lambda value: 'close' in value) == {'close': 1008}
    assert not rooms[1]


@pytest.mark.asyncio
async def test_member_revocation_disconnects_active_session(rooms, monkeypatch):
    monkeypatch.setattr(presence, 'RECHECK_INTERVAL', .01)
    async with connection() as socket:
        await socket.until(lambda value: 'peers' in value)
        async def revoked(*args):
            raise HTTPException(403, 'removed')
        monkeypatch.setattr(presence, 'authorize', revoked)
        assert await socket.until(lambda value: 'close' in value) == {'close': 4403}
    assert not rooms[1]
