"""把第一批助手工具绑定到项目视图和画布端口，不直接创建付费任务。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol
from uuid import uuid4

from fastapi import HTTPException

from app.printfilm_studio.agent.tools import TOOL_NAMES, apply_canvas_patch, validate_tool_input
from app.printfilm_studio.integration.drama import (
    estimate_generation_price,
    update_script,
    update_shot,
)
from app.printfilm_studio.integration.media import create_media_task

WRITE_TOOLS = {name for name in TOOL_NAMES if not name.startswith(("read_", "list_", "get_", "estimate_"))}
CANVAS_WRITE_TOOLS = {'add_canvas_node', 'update_canvas_node', 'remove_canvas_node', 'connect_canvas_nodes'}


def _error_text(error: Exception) -> str:
    """Keep FastAPI business details visible in Agent tool-result events."""
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("detail") or detail)
        return str(detail or "请求未完成")
    return str(error)


class CanvasPort(Protocol):
    """画布读写端口，测试可以用内存实现替换数据库。"""

    async def load(self) -> tuple[dict[str, Any], int]:
        """返回当前文档和版本。"""

    async def save(self, document: dict[str, Any]) -> int:
        """保存文档并返回新版本。"""


def summarize_canvas(document: dict[str, Any], version: int, limit: int = 40) -> dict[str, Any]:
    """压缩节点列表，避免把整份画布塞进模型上下文。"""
    nodes = list(document.get("nodes") or [])
    edges = list(document.get("edges") or [])
    visible = []
    for node in nodes[:limit]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        visible.append({
            "id": node.get("id"),
            "type": node.get("type"),
            "label": data.get("label") or "",
            "text": str(data.get("text") or "")[:180],
            "asset_id": data.get("assetId"),
            "sourceScriptId": data.get("sourceScriptId"),
            "storyKind": data.get("storyKind"),
            "shotIndex": data.get("shotIndex"),
        })
    return {
        "version": version,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "truncated": len(nodes) > limit,
        "nodes": visible,
        "edges": [{"id": edge.get("id"), "source": edge.get("source"), "target": edge.get("target")} for edge in edges[:limit]],
    }


def _node_from_arguments(arguments: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    """补齐新增节点的 id、类型和文本。"""
    node = deepcopy(arguments.get("node") if isinstance(arguments.get("node"), dict) else arguments)
    node_id = str(node.get("id") or f"n-{uuid4()}")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if arguments.get("text") and "text" not in data:
        data = {**data, "text": arguments.get("text")}
    if arguments.get("label") and "label" not in data:
        data = {**data, "label": arguments.get("label")}
    if "label" not in data:
        data = {**data, "label": str(node.get("type") or arguments.get("type") or "文本")}
    position = node.get("position") if isinstance(node.get("position"), dict) else None
    if position is None:
        viewport = document.get('viewport') or {}
        zoom = max(.05, float(viewport.get('zoom') or 1))
        origin = {'x': (120 - float(viewport.get('x') or 0)) / zoom, 'y': (120 - float(viewport.get('y') or 0)) / zoom}
        nodes = document.get('nodes') or []
        for index in range(len(nodes) + 1):
            position = {'x': origin['x'] + (index % 3) * 380, 'y': origin['y'] + (index // 3) * 280}
            if not any(abs(float((other.get('position') or {}).get('x') or 0) - position['x']) < 340 and abs(float((other.get('position') or {}).get('y') or 0) - position['y']) < 240 for other in nodes):
                break
    return {"id": node_id, "type": str(node.get("type") or arguments.get("type") or "text"), "position": position, "data": data}


def _operations(name: str, arguments: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    """把单个工具参数转换成画布补丁。"""
    if name == "add_canvas_node":
        return [{"op": "add_node", "node": _node_from_arguments(arguments, document)}]
    if name == "update_canvas_node":
        node_id = str(arguments.get("node_id") or "")
        changes = arguments.get("changes") if isinstance(arguments.get("changes"), dict) else {}
        current = next((node for node in document.get("nodes") or [] if str(node.get("id")) == node_id), {})
        if isinstance(changes.get('data'), dict):
            changes = {**changes, 'data': {**current.get('data', {}), **changes['data']}}
        if arguments.get("text") is not None or arguments.get("label") is not None:
            data = dict(changes.get('data') or current.get("data") or {})
            if arguments.get("text") is not None:
                data["text"] = arguments.get("text")
            if arguments.get("label") is not None:
                data["label"] = arguments.get("label")
            changes = {**changes, "data": data}
        return [{"op": "update_node", "node_id": node_id, "changes": changes}]
    if name == "remove_canvas_node":
        return [{"op": "remove_node", "node_id": str(arguments.get("node_id") or "")}]
    if name == "connect_canvas_nodes":
        edge = arguments.get("edge") if isinstance(arguments.get("edge"), dict) else {
            "source": arguments.get("source"),
            "target": arguments.get("target"),
            "id": arguments.get("edge_id") or arguments.get("id"),
        }
        return [{"op": "connect_canvas_nodes", "edge": edge}]
    if name == "attach_asset_to_node":
        node_id = str(arguments.get("node_id") or "")
        current = next((node for node in document.get("nodes") or [] if str(node.get("id")) == node_id), {})
        data = dict(current.get("data") or {})
        data["assetId"] = arguments.get("asset_id")
        return [{"op": "update_node", "node_id": node_id, "changes": {"data": data}}]
    return []


async def execute_canvas_tool_batch(calls: list[dict[str, Any]], canvas: CanvasPort, *, allow_write: bool) -> dict[str, Any]:
    """Validate a batch against a copy and save once; failures never leave half a graph."""
    if not allow_write:
        return {'ok': False, 'error': '需要先取得画布编辑权'}
    if not isinstance(calls, list) or not calls or len(calls) > 12:
        return {'ok': False, 'error': '工具调用必须为非空数组，单轮最多执行 12 个工具'}
    document, version = await canvas.load()
    candidate, operations = document, []
    try:
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get('input', {}), dict):
                raise ValueError('工具名称或参数格式无效')
            name, payload = call['tool'], call.get('input', {})
            if name not in CANVAS_WRITE_TOOLS:
                raise ValueError('不支持的画布批量工具')
            validate_tool_input(name, payload)
            changes = _operations(name, payload, candidate)
            candidate = apply_canvas_patch(candidate, version, version, changes)
            operations.extend(changes)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {'ok': False, 'error': str(exc)}
    new_version = await canvas.save(candidate)
    return {'ok': True, 'version': new_version, 'operations': operations, 'canvas': summarize_canvas(candidate, new_version)}


async def execute_studio_tool(name: str, arguments: dict[str, Any] | None, view: dict[str, Any], canvas: CanvasPort, *, allow_write: bool) -> dict[str, Any]:
    """执行一个已声明工具。未开放的写操作返回原因，不改数据。"""
    if name != "apply_canvas_operations" and name not in TOOL_NAMES:
        return {"ok": False, "error": "不支持的工具"}
    payload = arguments if isinstance(arguments, dict) else {}
    try:
        validate_tool_input(name, payload)
    except ValueError as exc:
        return {'ok': False, 'error': str(exc)}
    if (name in WRITE_TOOLS or name == "apply_canvas_operations") and not allow_write:
        return {"ok": False, "error": "团队项目需要先取得画布编辑权，助手暂不能改画布"}
    if name in {'plan_story_assets', 'plan_story_shots'}:
        from app.printfilm_studio.agent.story_workflow import apply_story_plan
        try:
            return await apply_story_plan(name, payload, canvas)
        except (ValueError, RuntimeError, HTTPException, PermissionError) as exc:
            return {'ok': False, 'error': _error_text(exc)}
    if name == 'edit_media':
        from app.printfilm_studio.integration.agent_media import edit_project_media
        import httpx
        try:
            return await edit_project_media(canvas, payload)
        except (ValueError, RuntimeError, HTTPException, PermissionError, OSError, httpx.HTTPError) as exc:
            return {'ok': False, 'error': _error_text(exc)}
    if name == "read_project":
        return {"ok": True, "project": {key: view.get(key) for key in ("id", "title", "description", "workflow")}}
    if name == "read_episode":
        episodes = list(view.get("episodes") or [])
        episode_id = payload.get("episode_id")
        if episode_id is not None:
            episodes = [item for item in episodes if item.get("id") == episode_id or str(item.get("id")) == str(episode_id)]
        return {"ok": True, "episodes": episodes}
    if name == "list_assets":
        return {"ok": True, "assets": list(view.get("assets") or [])}
    if name == "get_task_status":
        tasks = list(view.get("tasks") or [])
        task_id = payload.get("task_id")
        if task_id is not None:
            tasks = [item for item in tasks if item.get("id") == task_id or str(item.get("id")) == str(task_id).removeprefix('task-')]
        return {"ok": True, "tasks": tasks}
    if name in {"create_image_task", "create_video_task", "create_audio_task"}:
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "媒体任务需要 prompt"}
        kind = name.removeprefix("create_").removesuffix("_task")
        options = {key: value for key, value in payload.items() if key not in {"prompt", "kind"}}
        try:
            task = await create_media_task(canvas, kind, prompt, **options)
        except (ValueError, RuntimeError, HTTPException, PermissionError) as exc:
            return {"ok": False, "error": _error_text(exc)}
        return {"ok": True, "task": task, "task_id": task.get("task_id"), "platform_task_id": task.get("platform_task_id"), "node_id": task.get("node_id"), "version": task.get("version"), "status": task.get("status", "queued")}
    if name == "estimate_generation_price":
        try:
            return await estimate_generation_price(canvas, payload)
        except (ValueError, RuntimeError, HTTPException, PermissionError) as exc:
            return {"ok": False, "error": _error_text(exc)}
    if name == "update_script":
        try:
            return await update_script(canvas, payload)
        except (ValueError, RuntimeError, HTTPException, PermissionError) as exc:
            return {"ok": False, "error": _error_text(exc)}
    if name == "update_shot":
        try:
            return await update_shot(canvas, payload)
        except (ValueError, RuntimeError, PermissionError) as exc:
            return {"ok": False, "error": _error_text(exc)}
    document, version = await canvas.load()
    if name == "read_canvas":
        if 'node_ids' in payload:
            ids = payload['node_ids']
            if not ids or len(ids) > 20 or not all(isinstance(item, str) for item in ids):
                return {'ok': False, 'error': '请指定 1 至 20 个有效节点 ID'}
            selected = [node for node in document.get('nodes', []) if node['id'] in ids]
            if len(selected) != len(set(ids)):
                return {'ok': False, 'error': '引用节点不存在'}
            return {'ok': True, 'nodes': selected}
        return {"ok": True, "canvas": summarize_canvas(document, version)}
    if name == 'attach_asset_to_node':
        asset = next((item for item in view.get('assets', []) if item.get('id') == payload.get('asset_id')), None)
        if not asset:
            return {'ok': False, 'error': '素材不属于当前项目'}
        current = next((item for item in document.get('nodes', []) if item.get('id') == payload.get('node_id')), None)
        if not current:
            return {'ok': False, 'error': '节点不存在'}
        payload = {'node_id': payload['node_id'], 'changes': {'data': {**current.get('data', {}), 'assetId': asset['id'], 'mediaUrl': asset.get('url'), 'mediaType': asset.get('asset_type') or asset.get('type'), 'status': 'completed'}}}
        name = 'update_canvas_node'
    try:
        operations = payload.get("canvas_operations") if name == "apply_canvas_operations" else _operations(name, payload, document)
        updated = apply_canvas_patch(document, version, version, operations)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {"ok": False, "error": str(exc)}
    new_version = await canvas.save(updated)
    return {"ok": True, "version": new_version, "operations": operations, "canvas": summarize_canvas(updated, new_version)}
