"""Agent Skill 解析、注入与内置手册。"""

from pathlib import Path

from app.models_agent import AgentSkill
from app.services.agent.compose import render_skill_block, skill_matches_task
from app.services.agent.parse import parse_skill_markdown
from app.services.agent.store import BUILTIN_SKILLS_DIR, builtin_skill_files


def test_parse_cinedance_builtin_skill():
    path = BUILTIN_SKILLS_DIR / "cinedance-seedance" / "SKILL.md"
    parsed = parse_skill_markdown(path.read_text(encoding="utf-8"))
    assert parsed["slug"] == "cinedance-seedance"
    assert "shot_plan" in parsed["tasks"]
    assert "video_prompt" in parsed["tasks"]
    assert "第一帧" in parsed["body"]
    assert "空间站位" in parsed["body"]
    assert "CINEDANCE" in parsed["name"] or "CINEDANCE" in parsed["description"] or "CINEDANCE" in parsed["body"]


def test_parse_folded_description_and_task_list():
    markdown = """---
name: my-shot-guide
description: >-
  用于规划镜头与分镜。
  强调站位。
tasks:
  - shot_plan
  - 生视频
---

# 正文
必须写清第一帧。
"""
    parsed = parse_skill_markdown(markdown)
    assert parsed["slug"] == "my-shot-guide"
    assert "规划镜头" in parsed["description"]
    assert parsed["tasks"] == ["shot_plan", "video_prompt"]
    assert "第一帧" in parsed["body"]


def test_render_skill_block_includes_director_locks():
    skill = AgentSkill(
        slug="cinedance-seedance",
        name="CINEDANCE 镜头导演",
        description="",
        body="第一帧必须有人。空间站位用 1 米以内。",
        tasks=["shot_plan"],
        is_builtin=True,
        is_active=True,
    )
    block = render_skill_block([skill])
    assert "已启用 Agent Skill" in block
    assert "第一帧必须有人" in block
    assert skill_matches_task(skill, "shot_plan")
    assert not skill_matches_task(
        AgentSkill(slug="x", name="x", body="b", tasks=["video_prompt"]),
        "shot_plan",
    )


def test_slugify_chinese_names_are_unique():
    from app.services.agent.parse import slugify_skill_name

    first = slugify_skill_name("我的运镜")
    second = slugify_skill_name("另一套运镜")
    assert first.startswith("skill-")
    assert second.startswith("skill-")
    assert first != second
    assert slugify_skill_name("my-camera-style") == "my-camera-style"


def test_builtin_skill_files_exist():
    files = builtin_skill_files()
    assert any(path.name == "SKILL.md" for path in files)
    assert (BUILTIN_SKILLS_DIR / "cinedance-seedance" / "SKILL.md").is_file()


def test_parse_skill_ids_none_and_empty():
    from app.services.agent.compose import parse_skill_ids

    assert parse_skill_ids(None) is None
    assert parse_skill_ids([]) == []
    assert parse_skill_ids([1, "2", 0, "x", 1]) == [1, 2]


def test_restore_asset_tokens_keeps_mentions():
    from app.services.agent.optimize import restore_asset_tokens

    original = "@asset:12 和 @asset:8 在 @asset:3 谈恋爱"
    rewritten = "近景：两人在祭坛前对视，缓慢推进。"
    out = restore_asset_tokens(original, rewritten)
    assert "@asset:12" in out
    assert "@asset:8" in out
    assert "@asset:3" in out


def test_restore_asset_tokens_strips_fences():
    from app.services.agent.optimize import restore_asset_tokens

    original = "角色 @asset:1 回头"
    rewritten = "```\n@asset:1 回头看向镜头，第一帧站在门内。\n```"
    assert restore_asset_tokens(original, rewritten) == "@asset:1 回头看向镜头，第一帧站在门内。"
