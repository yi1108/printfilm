"""故事引导必需工具未调用时的纠正与失败保护。"""

import copy
import json

import pytest

from app.printfilm_studio.agent.runtime import iter_agent_turn


class Canvas:
    def __init__(self):
        self.document = {
            "nodes": [
                {"id": "script", "type": "script", "position": {"x": 0, "y": 0}, "data": {"label": "三国", "text": "第一幕，刘备与曹操在桃园交谈。"}},
                {"id": "scene", "type": "scene", "position": {"x": 400, "y": 0}, "data": {"label": "桃园", "sourceScriptId": "script", "storyKind": "scene", "writingRequirements": "东汉桃园", "prompt": "桃园清晨"}},
            ],
            "edges": [],
        }
        self.version = 1

    async def load(self):
        return copy.deepcopy(self.document), self.version

    async def save(self, document):
        self.document = document
        self.version += 1
        return self.version


SHOT_CALL = {
    "tool": "plan_story_shots",
    "input": {
        "script_node_id": "script",
        "shots": [{
            "index": 1,
            "name": "桃园对谈",
            "description": "中景，刘备与曹操交谈，5秒",
            "prompt": "刘备与曹操在桃园交谈，清晨柔光，固定镜头",
            "reference_node_ids": ["scene"],
        }],
    },
}


@pytest.mark.asyncio
async def test_missing_required_tool_is_retried_then_produces_proposal():
    canvas = Canvas()
    prompts = []
    answers = iter(["现在提交分镜规划：", json.dumps(SHOT_CALL, ensure_ascii=False)])

    async def complete(_system, user):
        prompts.append(user)
        return next(answers)

    events = [event async for event in iter_agent_turn(
        view={}, canvas=canvas, prompt="拆分分镜", complete=complete,
        enabled_tools=["read_canvas", "plan_story_shots"], review_changes=True,
        required_tool="plan_story_shots",
    )]
    assert any(event["type"] == "proposal" for event in events)
    assert len(prompts) == 2
    assert "没有实际调用 plan_story_shots" in prompts[1]


@pytest.mark.asyncio
async def test_missing_required_tool_after_retries_fails_instead_of_completing():
    canvas = Canvas()
    calls = []

    async def complete(_system, user):
        calls.append(user)
        return "现在提交分镜规划："

    with pytest.raises(RuntimeError, match="plan_story_shots"):
        _ = [event async for event in iter_agent_turn(
            view={}, canvas=canvas, prompt="拆分分镜", complete=complete,
            enabled_tools=["read_canvas", "plan_story_shots"], review_changes=True,
            required_tool="plan_story_shots",
        )]
    assert len(calls) == 3
