"""从助手回复里分离可见文本和可选动作。"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_BLOCK_START = re.compile(r'```|^[ \t]*(?=[{\[])', re.MULTILINE)


def _action(payload: str) -> dict[str, Any] | None:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if isinstance(value, list) and any(isinstance(item, dict) and 'tool' in item for item in value):
        return {'tool_calls': value}
    if isinstance(value, dict) and any(key in value for key in ('tool', 'tool_calls', 'canvas_operations')):
        return value
    return None


def split_assistant_action(text: str) -> tuple[str, dict[str, Any] | None]:
    """返回给用户看的文字，以及 tool / canvas_operations 动作。"""
    raw = text or ""
    actions, pieces, end = [], [], 0
    consumed = 0
    decoder = json.JSONDecoder()
    for start in _BLOCK_START.finditer(raw):
        if start.start() < consumed:
            continue
        if raw.startswith('```', start.start()):
            match = _FENCE.match(raw, start.start())
            if match is None:
                break  # Never interpret an incomplete code example as an action.
            consumed = match.end()
            action = _action(match.group(1))
        else:
            offset = start.end()
            try:
                _, length = decoder.raw_decode(raw[offset:])
            except json.JSONDecodeError:
                continue
            consumed = offset + length
            action = _action(raw[offset:consumed])
        if action is None:
            continue
        actions.append(action)
        pieces.append(raw[end:start.start()])
        end = consumed
    if not actions:
        action = _action(raw.strip())
        return ('', action) if action else (raw.strip(), None)
    pieces.append(raw[end:])
    visible = ''.join(pieces).strip()
    if len(actions) == 1:
        return visible, actions[0]
    if any('canvas_operations' in item for item in actions):
        return visible, {'action_error': '请在一次回复中使用同一种画布操作格式'}
    calls = []
    for item in actions:
        if sum(key in item for key in ('tool', 'tool_calls', 'canvas_operations')) != 1:
            return visible, {'action_error': '请在一次回复中使用同一种工具调用格式'}
        batch = item.get('tool_calls', [item])
        if not isinstance(batch, list):
            return visible, {'action_error': '工具调用列表格式无效'}
        calls.extend(batch)
    return visible, {'tool_calls': calls}
