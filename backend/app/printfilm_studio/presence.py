"""Ephemeral canvas awareness across API workers; graph writes keep their CAS guard."""
import asyncio
import json
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.deps import _user_from_bearer
from app.printfilm_studio.sharing import project_for

router = APIRouter(prefix='/printfilm-studio', tags=['printfilm-studio-presence'])
TTL = 20
RECHECK_INTERVAL = 5
COLORS = ('#7953a2', '#148a82', '#ce7638', '#447ccc', '#c45186', '#63862e')


class Point(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    x: float = Field(ge=-10_000_000, le=10_000_000)
    y: float = Field(ge=-10_000_000, le=10_000_000)


class NodePosition(Point):
    id: str = Field(min_length=1, max_length=128)


class Awareness(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cursor: Point | None = None
    action: Literal['idle', 'selecting', 'dragging', 'editing', 'connecting', 'generating', 'saved'] = 'idle'
    node_ids: list[str] = Field(default_factory=list, max_length=32)
    positions: list[NodePosition] = Field(default_factory=list, max_length=32)


async def authorize(project_id, token):
    async with AsyncSessionLocal() as db:
        user = await _user_from_bearer(db, token)
        if not user:
            raise HTTPException(401, '登录已失效')
        await project_for(db, project_id, user)
        return {'user_id': user.id, 'name': (user.nickname or '画布成员')[:64], 'color': COLORS[user.id % len(COLORS)]}


class RedisRoom:
    def __init__(self, project_id):
        self.redis = Redis.from_url(get_settings().redis_url, decode_responses=True,
                                    socket_connect_timeout=2, socket_timeout=3)
        self.key = f'printfilm:presence:v1:{project_id}'
        self.channel = self.key + ':events'
        self.pubsub = self.redis.pubsub()

    async def subscribe(self):
        await self.pubsub.subscribe(self.channel)

    async def snapshot(self):
        raw = await self.redis.hgetall(self.key)
        now = time.time()
        peers = []
        for session, value in raw.items():
            try:
                item = json.loads(value)
                if now - item['seen_at'] < TTL:
                    peers.append(item)
                else:
                    await self.redis.eval("if redis.call('HGET',KEYS[1],ARGV[1]) == ARGV[2] then return redis.call('HDEL',KEYS[1],ARGV[1]) else return 0 end", 1, self.key, session, value)
            except (ValueError, KeyError, TypeError):
                continue
        return peers[:64]

    async def update(self, session, identity, state):
        # Each field contains its lease; the entire hash also expires when empty.
        if len(await self.snapshot()) >= 64 and not await self.redis.hexists(self.key, session):
            raise HTTPException(409, '当前画布在线人数已满')
        value = {**identity, **state.model_dump(), 'session_id': session, 'seen_at': time.time()}
        await self.redis.hset(self.key, session, json.dumps(value, ensure_ascii=False))
        await self.redis.expire(self.key, TTL * 2)
        await self.redis.publish(self.channel, 'changed')

    async def remove(self, session):
        await self.redis.hdel(self.key, session)
        await self.redis.publish(self.channel, 'changed')

    async def changes(self):
        while True:
            event = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            if event and event['type'] == 'message':
                yield None

    async def close(self):
        await self.pubsub.aclose()
        await self.redis.aclose()


async def read_message(socket):
    raw = await socket.receive_text()
    if len(raw) > 16_000:
        raise ValueError('message too large')
    return json.loads(raw)


@router.websocket('/projects/{project_id}/presence')
async def canvas_presence(socket: WebSocket, project_id: int):
    await socket.accept()
    room = None
    session = str(uuid4())
    tasks = []
    joined = False
    try:
        hello = await asyncio.wait_for(read_message(socket), timeout=5)
        token = hello.get('token') if isinstance(hello, dict) else None
        if not isinstance(token, str) or not 1 <= len(token) <= 8192:
            await socket.close(code=4401)
            return
        identity = await authorize(project_id, token)
        room = RedisRoom(project_id)
        await room.subscribe()
        await room.update(session, identity, Awareness())
        joined = True
        send_lock = asyncio.Lock()
        async def send_snapshot():
            peers = await room.snapshot()
            async with send_lock:
                await socket.send_json({'type': 'presence', 'self_id': session, 'peers': peers})
        await send_snapshot()
        last_input = time.monotonic()
        last_update = 0.0

        async def receive():
            nonlocal last_input, last_update
            while True:
                message = await read_message(socket)
                state = Awareness.model_validate(message)
                if any(not 1 <= len(identity) <= 128 for identity in state.node_ids):
                    raise ValueError('invalid node id')
                last_input = time.monotonic()
                if last_input - last_update < 0.08:
                    continue
                last_update = last_input
                await room.update(session, identity, state)

        async def broadcast():
            async for _ in room.changes():
                await send_snapshot()

        async def guard():
            while True:
                await asyncio.sleep(RECHECK_INTERVAL)
                await authorize(project_id, token)  # Membership and revoked credentials are rechecked.
                if time.monotonic() - last_input > TTL:
                    raise TimeoutError('presence heartbeat expired')
                await send_snapshot()

        tasks = [asyncio.create_task(receive()), asyncio.create_task(broadcast()), asyncio.create_task(guard())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except HTTPException as error:
        await socket.close(code=4401 if error.status_code == 401 else 4403)
    except (ValueError, TypeError, ValidationError, asyncio.TimeoutError):
        await socket.close(code=1008)
    except RedisError:
        await socket.close(code=1013)
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if room:
            try:
                if joined:
                    await room.remove(session)
            except RedisError:
                pass
            await room.close()
