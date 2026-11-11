"""第一批 Printfilm Studio Agent 工具声明与画布 Patch 应用。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.printfilm_studio.canvas.codec import decode_canvas_document

MAX_CANVAS_OPERATIONS = 20


def validate_canvas_operations(operations: Any) -> None:
    """Reject an invalid patch in full before any write or success event."""
    if not isinstance(operations, list) or not operations:
        raise ValueError('没有可执行的画布操作')
    if len(operations) > MAX_CANVAS_OPERATIONS:
        raise ValueError(f'一次最多提交 {MAX_CANVAS_OPERATIONS} 条画布操作，请拆分请求')
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError('画布操作必须为对象')
        op = operation.get('op')
        if op == 'add_node':
            node = operation.get('node')
            if not isinstance(node, dict) or not str(node.get('id') or '').strip():
                raise ValueError('新增节点需要有效的 node 和 id')
        elif op in ('update_node', 'remove_node'):
            if not str(operation.get('node_id') or '').strip():
                raise ValueError('画布操作缺少 node_id')
            if op == 'update_node' and not isinstance(operation.get('changes'), dict):
                raise ValueError('更新节点需要 changes 对象')
        elif op == 'connect_canvas_nodes':
            edge = operation.get('edge')
            if not isinstance(edge, dict) or not edge.get('source') or not edge.get('target'):
                raise ValueError('连接节点需要有效的 edge、source 和 target')
        elif op == 'remove_edge':
            if not str(operation.get('edge_id') or '').strip():
                raise ValueError('移除连接需要 edge_id')
        else:
            raise ValueError(f'unsupported canvas operation: {op}')


def apply_canvas_patch(document: dict[str, Any], base_version: int, current_version: int, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply all operations to a copy so a failed patch never writes partial state."""
    if base_version != current_version:
        raise ValueError("canvas version conflict")
    validate_canvas_operations(operations)
    candidate = decode_canvas_document(deepcopy(document))
    nodes = {str(node["id"]): node for node in candidate["nodes"]}
    edges = {str(edge["id"]): edge for edge in candidate["edges"]}
    for operation in operations:
        op = str(operation.get("op") or "")
        if op == "add_node":
            node = operation.get("node")
            if not isinstance(node, dict) or str(node.get("id") or "") in nodes:
                raise ValueError("invalid or duplicate node")
            nodes[str(node["id"])] = deepcopy(node)
        elif op == "update_node":
            node_id = str(operation.get("node_id") or "")
            changes = operation.get("changes")
            if node_id not in nodes or not isinstance(changes, dict):
                raise ValueError("node does not exist")
            nodes[node_id] = {**nodes[node_id], **deepcopy(changes), "id": node_id}
        elif op == "remove_node":
            node_id = str(operation.get("node_id") or "")
            if node_id not in nodes:
                raise ValueError("node does not exist")
            del nodes[node_id]
            edges = {key: edge for key, edge in edges.items() if edge.get("source") != node_id and edge.get("target") != node_id}
        elif op == "connect_canvas_nodes":
            edge = operation.get("edge")
            if not isinstance(edge, dict) or not nodes.get(str(edge.get("source") or "")) or not nodes.get(str(edge.get("target") or "")):
                raise ValueError("edge references an unknown node")
            edge_id = str(edge.get("id") or f"{edge['source']}->{edge['target']}")
            if edge_id in edges:
                raise ValueError("duplicate edge")
            edges[edge_id] = {**deepcopy(edge), "id": edge_id}
        elif op == "remove_edge":
            edge_id = str(operation.get("edge_id") or "")
            if edge_id not in edges:
                raise ValueError("edge does not exist")
            del edges[edge_id]
        else:
            raise ValueError(f"unsupported canvas operation: {op}")
    candidate["nodes"] = list(nodes.values())
    candidate["edges"] = list(edges.values())
    return decode_canvas_document(candidate)


TOOL_NAMES = (
    "read_project", "read_episode", "read_canvas", "add_canvas_node", "update_canvas_node",
    "remove_canvas_node", "connect_canvas_nodes", "list_assets", "attach_asset_to_node",
    "create_image_task", "create_video_task", "create_audio_task", "get_task_status",
    "update_script", "update_shot", "estimate_generation_price", "edit_media",
    "plan_story_assets", "plan_story_shots",
)

TOOL_DESCRIPTIONS = {
    'plan_story_assets': '从指定剧本完整正文抽取全部角色与场景，一次创建写作要求文本节点及对应角色/场景图片节点，以sourceScriptId记录归属，剧本独立不连线。参数 script_node_id，assets 数组，每项 {kind:character或scene,name:名称,prompt:生成图片提示词的写作要求，描述主体时代构图风格约束，不是最终提示词，禁止写入正文留空或只写要求等流程指令,description:原剧本依据}。仅规划不生成图片；重复调用保留已有节点。最多100项。完成本阶段后停止，等待用户选择拆分分镜。',
    'plan_story_shots': '在已抽取角色场景的剧本下创建视频片段写作节点和视频生成节点。优先少分镜、每段12–15秒，单段不超过15秒；同场连续动作对白反应合并，内部景别变化不另建节点。参数 script_node_id，shots 数组，每项 {index:正整数,name:镜头名称,description:景别/机位/动作/对白/时长,duration:镜头总时长秒数,ratio:明确画幅比例例如16:9或9:16,prompt:生成镜头提示词的写作要求，描述动作机位时长风格约束，不是最终提示词,reference_node_ids:当前剧本的角色及场景图片节点ID数组,scene_number:按剧本场次顺序编号从1开始，同场镜头相同编号，换场或返回同一地点的新场次递增,scene_node_id:对应场景图片节点ID,episodeNumber:可选分集序号}。duration和ratio必须与创作要求中的时长比例一致，落到下游视频节点；引用必须是图片节点ID，不能用写作节点或分组ID；必须包含对应场景及出镜角色。漏传场景时只会匹配正文中唯一明确的已有场景；遇到校验错误应按候选场景ID修正整批方案。最多100镜，只规划，不生成付费媒体。',
    'edit_media': '处理项目音视频并创建新节点。operation 为 trim/extract_audio/separate/mute/speed/frame/frames/concat。用 asset_id 或 node_id 指定素材，拼接按 asset_ids 顺序（2到8项）；时间用 start/end 秒，变速用 speed（0.1到4）。不能接受 URL 或命令。',
    'read_project': '读取当前项目名称与简介', 'read_episode': '按 episode_id 查询分集，省略则列出分集',
    'read_canvas': '读取画布摘要。指定 node_ids 数组（1至20项）可读取节点完整正文和提示词；分析剧本前必须指定剧本ID读取全文', 'list_assets': '列出当前项目素材及素材 ID',
    'get_task_status': '查询 task_id 的任务状态，省略则列出项目任务',
    'add_canvas_node': '直接在画布创建节点。写剧本用 type=script、label=标题、text=完整正文，不需要分集。其他节点使用 type、label、text、position，或完整 node 对象',
    'update_canvas_node': '更新 node_id 的 text、label 或 changes，保留其他字段',
    'remove_canvas_node': '删除 node_id 及关联连线', 'connect_canvas_nodes': '连接 source 和 target 两个节点',
    'attach_asset_to_node': '将本项目 asset_id 素材及媒体地址绑定到 node_id',
    'create_image_task': '提交图片生成任务；prompt 必填，支持 model_id、node_id、ratio、count',
    'create_video_task': '提交视频生成任务；prompt 必填，支持 model_id、node_id、duration、ratio',
    'create_audio_task': '提交音频生成任务；prompt 必填，支持 model_id、node_id',
    'update_script': '仅修改项目剧本资料或分集记录，不创建画布节点。分集使用 episode_number 和 body；项目资料使用 source/name/summary。画布写剧本应使用 add_canvas_node(type=script)',
    'update_shot': '修改 fragment_id 镜头的 content、duration_sec，或用 episode_id 与 sort_order 定位',
    'estimate_generation_price': '只读报价，不扣费；kind 为 image/video/audio，支持 model_id、count、duration',
}

_FIELDS = {
    'plan_story_assets': {'script_node_id': 'string', 'assets': 'array'},
    'plan_story_shots': {'script_node_id': 'string', 'shots': 'array'},
    'read_canvas': {'node_ids': 'array'},
    'edit_media': {'operation': 'string', 'node_id': 'string', 'asset_id': 'integer', 'asset_ids': 'array', 'start': 'number', 'end': 'number', 'speed': 'number'},
    'read_episode': {'episode_id': 'integer'}, 'get_task_status': {'task_id': 'string'},
    'add_canvas_node': {'node': 'object', 'type': 'string', 'label': 'string', 'text': 'string', 'position': 'object'},
    'update_canvas_node': {'node_id': 'string', 'text': 'string', 'label': 'string', 'changes': 'object'},
    'remove_canvas_node': {'node_id': 'string'}, 'connect_canvas_nodes': {'source': 'string', 'target': 'string', 'edge': 'object'},
    'attach_asset_to_node': {'node_id': 'string', 'asset_id': 'integer'},
    'update_script': {'episode_number': 'integer', 'body': 'string', 'source': 'string', 'name': 'string'},
    'update_shot': {'fragment_id': 'integer', 'episode_id': 'integer', 'sort_order': 'integer', 'content': 'string', 'duration_sec': 'integer'},
    'estimate_generation_price': {'kind': 'string', 'model_id': 'string', 'count': 'integer', 'duration': 'number'},
}
for _kind in ('image', 'video', 'audio'):
    _FIELDS[f'create_{_kind}_task'] = {'prompt': 'string', 'model_id': 'string', 'node_id': 'string', 'reference_asset_ids': 'array', 'ratio': 'string', 'count': 'integer', 'duration': 'number'}
_REQUIRED = {name: ['prompt'] for name in TOOL_NAMES if name.startswith('create_')}
_REQUIRED.update(update_canvas_node=['node_id'], remove_canvas_node=['node_id'], attach_asset_to_node=['node_id', 'asset_id'], edit_media=['operation'])
_REQUIRED.update(plan_story_assets=['script_node_id', 'assets'], plan_story_shots=['script_node_id', 'shots'])


def validate_tool_input(name: str, payload: dict[str, Any]) -> None:
    for field in _REQUIRED.get(name, []):
        if field not in payload or payload[field] is None or payload[field] == '':
            raise ValueError(f'工具 {name} 缺少参数 {field}')
    import math
    checks = {'string': lambda value: isinstance(value, str), 'integer': lambda value: type(value) is int, 'number': lambda value: type(value) in (int, float) and math.isfinite(value), 'object': lambda value: isinstance(value, dict), 'array': lambda value: isinstance(value, list)}
    for field, kind in _FIELDS.get(name, {}).items():
        if field in payload and not checks[kind](payload[field]):
            raise ValueError(f'参数 {field} 类型必须为 {kind}')


def tool_definitions() -> list[dict[str, Any]]:
    """Return stable declarations; execution stays behind integration services."""
    def _unbound(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("tool execution must be bound to a project-scoped integration service")

    return [{"name": name, "description": TOOL_DESCRIPTIONS[name], "input_schema": {"type": "object", 'properties': {field: {'type': kind} for field, kind in _FIELDS.get(name, {}).items()}, 'required': _REQUIRED.get(name, [])}, "permission": "read" if name.startswith(("read_", "list_", "get_", "estimate_")) else "write", "execute": _unbound} for name in TOOL_NAMES]
