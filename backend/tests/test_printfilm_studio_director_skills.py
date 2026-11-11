"""Printfilm Studio 导演 Skill 的阶段选择与注入测试。"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models_agent import AgentSkill
from app.printfilm_studio.agent import director_skills
from app.printfilm_studio.agent.runtime import iter_agent_turn
from app.printfilm_studio.agent.routes import StreamRequest
from app.services.agent import compose
from app.services.agent.parse import parse_skill_markdown
from app.services.agent.store import BUILTIN_SKILLS_DIR, seed_builtin_skills


EXPECTED_SKILLS = {
    "short-drama-assets": ("asset_plan", "连续性"),
    "short-drama-storyboard": ("shot_plan", "戏剧职责"),
    "short-drama-video-prompts": ("video_prompt", "参考"),
    "seedance-2-5-video-director": ("video_prompt", "4–30"),
}


def test_four_builtin_director_skills_parse_with_expected_tasks():
    for slug, (task, keyword) in EXPECTED_SKILLS.items():
        path = BUILTIN_SKILLS_DIR / slug / "SKILL.md"
        parsed = parse_skill_markdown(path.read_text(encoding="utf-8"))
        assert parsed["slug"] == slug
        assert parsed["tasks"] == [task]
        assert keyword in parsed["body"]
        assert "github.com/" in parsed["body"]
        assert len(parsed["body"]) < 12000


@pytest.mark.asyncio
async def test_builtin_seed_registers_all_four_skills_idempotently(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'skills.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(AgentSkill.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        await seed_builtin_skills(db)
        slugs = set((await db.scalars(select(AgentSkill.slug))).all())
        assert set(EXPECTED_SKILLS).issubset(slugs)
        assert "cinedance-seedance" in slugs
        await seed_builtin_skills(db)
        assert len((await db.scalars(select(AgentSkill))).all()) == len(slugs)
    await engine.dispose()


def test_asset_plan_task_alias_is_preserved():
    parsed = parse_skill_markdown("""---
name: asset-demo
description: 资产规划测试
tasks:
  - asset_plan
---

正文
""")
    assert parsed["tasks"] == ["asset_plan"]


@pytest.mark.asyncio
async def test_selected_skills_are_filtered_by_stage(monkeypatch):
    rows = [
        AgentSkill(id=1, slug="assets", name="资产", body="资产规则", tasks=["asset_plan"], is_builtin=True),
        AgentSkill(id=2, slug="shots", name="分镜", body="分镜规则", tasks=["shot_plan"], is_builtin=True),
    ]

    async def fake_list(_db, _user_id, _ids):
        return rows

    monkeypatch.setattr(compose, "list_skills_by_ids", fake_list)
    block = await compose.compose_selected_task_skills(object(), 1, "shot_plan", [1, 2])
    assert "分镜规则" in block
    assert "资产规则" not in block
    assert await compose.compose_selected_task_skills(None, 1, "shot_plan", []) == ""


def test_story_stage_overrides_requested_skill_task():
    assert director_skills.resolve_director_skill_task("assets", "video_prompt") == "asset_plan"
    assert director_skills.resolve_director_skill_task("shots", "asset_plan") == "shot_plan"
    assert director_skills.resolve_director_skill_task(None, "video_prompt") == "video_prompt"
    assert director_skills.resolve_director_skill_task(None, None) == "shot_plan"


@pytest.mark.asyncio
async def test_director_skill_block_uses_single_selected_skill(monkeypatch):
    calls = []

    async def fake_compose(_db, _user_id, _task, _ids):
        calls.append((_task, _ids))
        return "选定分镜 Skill"

    monkeypatch.setattr(director_skills, "director_skill_block", fake_compose)
    block = await director_skills.load_director_skill_block(None, 7, {
        "studio_agent_mode": "director",
        "studio_skill_task": "shot_plan",
        "studio_skill_ids": [9],
    })
    assert block == "选定分镜 Skill"
    assert calls == [("shot_plan", [9])]
    assert await director_skills.load_director_skill_block(None, 7, {
        "studio_agent_mode": "assistant",
        "studio_skill_task": "shot_plan",
        "studio_skill_ids": [9],
    }) == ""


@pytest.mark.asyncio
async def test_story_shot_planning_uses_selected_skill_without_skipping_stage(monkeypatch):
    async def selected(*_args):
        return '分镜导演的轴线与职责规则'
    monkeypatch.setattr(director_skills, 'director_skill_block', selected)
    block = await director_skills.load_director_skill_block(None, 7, {
        'studio_agent_mode': 'director', 'studio_skill_task': 'shot_plan',
        'studio_skill_ids': [5], 'studio_required_tool': 'plan_story_shots',
    })
    assert '轴线与职责' in block and '正文留空' in block


def test_stream_request_accepts_director_skill_options():
    request = StreamRequest(prompt="继续", agent_mode="director", skill_task="video_prompt", skill_ids=[4])
    assert request.agent_mode == "director"
    assert request.skill_task == "video_prompt"
    assert request.skill_ids == [4]


@pytest.mark.asyncio
async def test_agent_runtime_appends_selected_skill_to_system_prompt():
    seen = []

    class Canvas:
        async def load(self):
            return {"nodes": [], "edges": []}, 1

    async def complete(system, _user):
        seen.append(system)
        return "已完成"

    events = [event async for event in iter_agent_turn(
        view={"id": 1}, canvas=Canvas(), prompt="测试", complete=complete,
        skill_block="### 分镜 Skill\n每镜只有一个职责。",
    )]
    assert events[-1]["type"] == "message_delta"
    assert "每镜只有一个职责" in seen[0]
