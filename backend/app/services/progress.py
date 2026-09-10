"""Progress pub/sub — Redis when available, else in-process queues."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_queues: dict[int, list[asyncio.Queue]] = defaultdict(list)
_latest: dict[int, dict[str, Any]] = {}
_redis = None
_redis_failed = False


def _get_redis():
    global _redis, _redis_failed
    if _redis_failed:
        return None
    if _redis is not None:
        return _redis
    try:
        import redis

        client = redis.Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        _redis = client
        return _redis
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable for progress: %s", exc)
        _redis_failed = True
        return None


def channel(project_id: int) -> str:
    return f"framecut:progress:{project_id}"


async def publish_progress(project_id: int, payload: dict[str, Any]) -> None:
    _latest[project_id] = payload
    r = _get_redis()
    if r is not None:
        try:
            r.publish(channel(project_id), json.dumps(payload, ensure_ascii=False))
            r.setex(f"framecut:latest:{project_id}", 3600, json.dumps(payload, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis publish failed: %s", exc)

    dead: list[asyncio.Queue] = []
    for q in _queues[project_id]:
        try:
            q.put_nowait(payload)
        except Exception:  # noqa: BLE001
            dead.append(q)
    for q in dead:
        _queues[project_id].remove(q)


def subscribe(project_id: int) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _queues[project_id].append(q)
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(f"framecut:latest:{project_id}")
            if raw:
                q.put_nowait(json.loads(raw))
        except Exception:  # noqa: BLE001
            pass
    elif project_id in _latest:
        q.put_nowait(_latest[project_id])
    return q


def unsubscribe(project_id: int, q: asyncio.Queue) -> None:
    if q in _queues[project_id]:
        _queues[project_id].remove(q)


async def redis_bridge(project_id: int, q: asyncio.Queue) -> None:
    """Background task: forward Redis pubsub messages into local queue."""
    r = _get_redis()
    if r is None:
        return
    pubsub = r.pubsub()
    pubsub.subscribe(channel(project_id))
    try:
        while True:
            msg = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") == "message":
                data = msg.get("data")
                if isinstance(data, str):
                    q.put_nowait(json.loads(data))
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        pubsub.unsubscribe(channel(project_id))
        pubsub.close()
        raise
