"""真实上游 HTTP 请求的脱敏 TaskEvent 留痕；日志故障不改变网络请求结果。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models_tasks import TaskEvent, TaskRun, TaskStep
from app.services.tokenfree_video import extract_video_task_id, unwrap_video_task_payload
from app.services.upstream_sanitize import sanitize_upstream_value

logger = logging.getLogger(__name__)
_EVENT_TIMEOUT_SEC = 1.0
_POLL_SAMPLE_SEC = 60.0
_MAX_POLL_SAMPLES = 20
_POLL_CACHE_MAX = 2048
_poll_cache: OrderedDict[tuple, tuple[str, float, int]] = OrderedDict()
_event_session: ContextVar[Any | None] = ContextVar("upstream_event_session", default=None)


@asynccontextmanager
async def upstream_event_session(db: Any) -> AsyncIterator[None]:
    """内联任务尚未提交时，把事件附加到调用者事务，禁止日志独自提交业务数据。"""
    token = _event_session.set(db)
    try:
        yield
    finally:
        _event_session.reset(token)


def _append_event(
    db: Any, task_id: int, task: TaskRun | None, step: TaskStep | None,
    event_type: str, payload: dict[str, Any],
) -> None:
    """仅修改内存对象并 add 事件，不查询、不 flush、不 commit。"""
    provider_id = payload.get("provider_task_id")
    if task is not None:
        task.provider_name = str(payload.get("provider") or "tokenfree")
        response = payload.get("response") or {}
        body = response.get("body") if isinstance(response, dict) else None
        state = body.get("status") if isinstance(body, dict) else None
        task.provider_status = str(state or ("failed" if event_type.endswith("failed") else "accepted"))[:32]
    if step is not None:
        step.provider_name = str(payload.get("provider") or "tokenfree")
    if event_type == "upstream.request.accepted" and payload.get("is_video_submit") and provider_id:
        if task is not None:
            task.provider_task_id = str(provider_id)
            from app.services.media_models.runtime import current_operation
            operation = current_operation.get()
            if operation and operation["capability"] == "video":
                task.media_provider_tasks = {**(task.media_provider_tasks or {}), operation["operation_id"]: str(provider_id)}
        if step is not None:
            step.provider_task_id = str(provider_id)
            step.provider_name = str(payload.get("provider") or "tokenfree")
    db.add(TaskEvent(
        task_id=task_id, event_type=event_type,
        status=task.status if task is not None else None,
        phase=task.current_step_key if task is not None else None,
        message=event_type, payload=payload,
    ))


def _append_to_caller_session(db: Any, task_id: int, event_type: str, payload: dict[str, Any]) -> None:
    """只查看已加载/新建对象，避免未提交任务不可见及日志触发 autoflush。"""
    objects = list(db.identity_map.values()) + list(db.new)
    task = next((item for item in objects if isinstance(item, TaskRun) and item.id == task_id), None)
    if task is not None:
        objects.extend(task.__dict__.get("steps") or [])
    step = next((
        item for item in objects
        if isinstance(item, TaskStep) and item.task_id == task_id
        and (task is None or not task.current_step_key or item.step_key == task.current_step_key)
    ), None)
    _append_event(db, task_id, task, step, event_type, payload)


def _video_request(method: str, endpoint: str) -> tuple[bool, bool, str | None]:
    """识别视频建单与轮询路径，只对异步视频响应回填 provider ID。"""
    path = urlsplit(endpoint).path.rstrip("/")
    for suffix in ("/videos", "/contents/generations/tasks"):
        if path.endswith(suffix):
            return method == "POST", False, None
        marker = f"{suffix}/"
        if marker in path and method == "GET":
            task_id = unquote(path.split(marker, 1)[1].split("/", 1)[0])
            return False, True, task_id
    return False, False, None


def _response_body(response: Any) -> Any:
    """读取响应用于留痕，解析失败时保留文本；二进制只存类型和长度。"""
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        content_type = str(getattr(response, "headers", {}).get("content-type", ""))
        if content_type and not any(kind in content_type for kind in ("json", "text", "xml")):
            return getattr(response, "content", b"")
        return getattr(response, "text", "")


def _should_record_poll(task_id: int, endpoint: str, provider_id: str | None, state: str) -> bool:
    """只记录状态变化与有限的一分钟采样，避免每轮轮询都写事件。"""
    key = (task_id, endpoint.split("?", 1)[0], provider_id)
    now = time.monotonic()
    previous = _poll_cache.get(key)
    changed = previous is None or previous[0] != state
    sampled = previous is not None and previous[2] < _MAX_POLL_SAMPLES and now - previous[1] >= _POLL_SAMPLE_SEC
    if not changed and not sampled:
        return False
    _poll_cache[key] = (state, now, (previous[2] if previous else 0) + 1)
    _poll_cache.move_to_end(key)
    while len(_poll_cache) > _POLL_CACHE_MAX:
        _poll_cache.popitem(last=False)
    return True


async def _persist_event(task_id: int, event_type: str, payload: dict[str, Any]) -> None:
    """使用独立短事务追加事件；仅回填视频上游 ID，不改业务状态或计费字段。"""
    caller_session = _event_session.get()
    if caller_session is not None:
        _append_to_caller_session(caller_session, task_id, event_type, payload)
        return
    async with AsyncSessionLocal() as db:
        task = await db.get(TaskRun, task_id)
        if task is None:
            return
        provider_id = payload.get("provider_task_id")
        step = None
        if event_type == "upstream.request.accepted" and payload.get("is_video_submit") and provider_id:
            stmt = select(TaskStep).where(TaskStep.task_id == task_id)
            if task.current_step_key:
                stmt = stmt.where(TaskStep.step_key == task.current_step_key)
            step = (await db.execute(stmt.order_by(TaskStep.id.asc()).limit(1))).scalar_one_or_none()
        _append_event(db, task_id, task, step, event_type, payload)
        await db.commit()


async def _safe_record(task_id: int, event_type: str, payload: dict[str, Any]) -> None:
    """脱敏与写入均为尽力记录，失败或锁超时不能触发真实请求重试。"""
    try:
        safe = sanitize_upstream_value(payload)
        await asyncio.wait_for(_persist_event(task_id, event_type, safe), timeout=_EVENT_TIMEOUT_SEC)
    except Exception:  # noqa: BLE001
        logger.warning("upstream event unavailable task_id=%s event_type=%s", task_id, event_type)


async def observed_request(
    client: Any, method: str, endpoint: str, *, provider: str = "tokenfree", **kwargs: Any
) -> Any:
    """透明包装一次真实 HTTP 调用，保留参数、返回对象、异常和原重试策略。"""
    # 延迟导入：billing 包 __init__ 会反向导入本模块，模块级导入会形成循环
    from app.services.billing.context import get_current_task_run_id, get_current_team_id

    method = method.upper()
    send = getattr(client, method.lower())
    task_id = get_current_task_run_id()
    if task_id is None:
        return await send(endpoint, **kwargs)
    is_submit, is_poll, provider_id = _video_request(method, endpoint)
    if method not in {"GET", "HEAD", "OPTIONS"} and not is_poll:
        from app.services.billing.unified_ai import guard_upstream_submission, validate_before_upstream
        caller_db = _event_session.get()
        if caller_db is not None:
            await validate_before_upstream(caller_db, task_id)
        else:
            await guard_upstream_submission(task_id)
    if get_current_team_id() is not None and method not in {"GET", "HEAD", "OPTIONS"}:
        from app.services.tasks.team_scope import ensure_upstream_submission_allowed
        caller_db = _event_session.get()
        if caller_db is not None:
            await ensure_upstream_submission_allowed(caller_db, task_id)
        else:
            async with AsyncSessionLocal() as authorization_db:
                await ensure_upstream_submission_allowed(authorization_db, task_id)
    body = kwargs.get("json", kwargs.get("data", kwargs.get("content")))
    model = str(body.get("model") or "") if isinstance(body, dict) else None
    payload = {
        "request_id": uuid.uuid4().hex,
        "method": method, "endpoint": endpoint, "model": model or None,
        "provider": provider, "provider_task_id": provider_id,
        "elapsed_ms": 0, "status_code": None, "is_video_submit": is_submit,
        "request": {"headers": kwargs.get("headers") or {}, "body": body,
                    "params": kwargs.get("params"), "files": kwargs.get("files")},
        "response": None, "error": None,
    }
    from app.services.media_models.runtime import current_operation
    media_operation = current_operation.get()
    if media_operation is not None:
        payload["media_operation_id"] = media_operation["operation_id"]
    if not is_poll:
        await _safe_record(task_id, "upstream.request.started", payload)
    started = time.perf_counter()
    try:
        response = await send(endpoint, **kwargs)
    except Exception as exc:
        payload = {**payload, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                   "error": {"type": type(exc).__name__, "message": str(exc)}}
        if not is_poll or _should_record_poll(task_id, endpoint, provider_id, f"network:{type(exc).__name__}"):
            await _safe_record(task_id, "upstream.request.poll" if is_poll else "upstream.request.failed", payload)
        raise
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    # 以下留痕处理不得改变已成功返回的 HTTP 请求，避免业务据异常重复提交。
    try:
        data = _response_body(response)
        code = int(response.status_code)
        unwrapped = unwrap_video_task_payload(data) if isinstance(data, dict) else {}
        state = str(unwrapped.get("status") or "").lower()
        error = unwrapped.get("error")
        failed = code >= 400 or bool(error) or state in {"failed", "error", "cancelled"}
        if is_submit and not failed:
            provider_id = extract_video_task_id(data)
        payload = {
            **payload, "provider_task_id": provider_id,
            "status_code": code,
            "elapsed_ms": elapsed_ms,
            "response": {"status_code": code, "headers": dict(getattr(response, "headers", {})), "body": data},
            "error": error or (f"HTTP {code}" if code >= 400 else None),
        }
        if is_poll:
            if _should_record_poll(task_id, endpoint, provider_id, f"{code}:{state}"):
                await _safe_record(task_id, "upstream.request.poll", payload)
        else:
            await _safe_record(task_id, "upstream.request.failed" if failed else "upstream.request.accepted", payload)
    except Exception:  # noqa: BLE001
        logger.warning("upstream response observation unavailable task_id=%s", task_id)
    return response
