"""LLM 分镜草稿规范化。"""

from types import SimpleNamespace

from app.services.drama.fragment_plan import normalize_llm_fragment_items
from app.services.drama.fragment_plan_prompt import FRAGMENT_PLAN_SYSTEM_PROMPT


def test_fragment_plan_system_prompt_requires_visual_density():
    # 用户反馈「分镜描述太少」：系统提示必须强制画面公式与结束态，不能只靠 docs
    prompt = FRAGMENT_PLAN_SYSTEM_PROMPT
    assert "画面描写密度" in prompt
    assert "结束态" in prompt
    assert "主体 + 动作" in prompt or "主体 + 动作/姿态" in prompt
    assert "禁止的瘦写法" in prompt
    assert "3–7 行" in prompt or "3-7 行" in prompt


def test_normalize_llm_injects_intro_once_for_important_cast():
    assets = [
        SimpleNamespace(
            id=1,
            type="character",
            name="鲧",
            params={"title": "治水先驱", "roleType": "主角"},
        ),
        SimpleNamespace(
            id=2,
            type="character",
            name="禹",
            params={"title": "治水英雄", "roleType": "主角"},
        ),
        SimpleNamespace(
            id=3,
            type="character",
            name="行刑兵",
            params={"title": "出场人物", "roleType": "配角"},
        ),
        SimpleNamespace(id=10, type="scene", name="羽山刑场", params={}),
    ]
    items = [
        {
            "duration_sec": 10,
            "scene_name": "羽山刑场",
            "character_names": [],
            "is_opening": True,
            "lines": [
                "羽山刑场全景，洪水拍崖。",
                "旁白（VO）：上古洪荒，治水未成。",
            ],
        },
        {
            "duration_sec": 12,
            "scene_name": "羽山刑场",
            "character_names": ["鲧", "禹"],
            "lines": [
                "鲧被绑在杉木柱上。",
                "禹冲上刑场高喊父亲。",
            ],
        },
    ]
    drafts = normalize_llm_fragment_items(
        items,
        assets,
        episode_number=1,
        episode_name="羽山刑场",
        project_title="大禹治水",
        story_type="古风神话",
        one_line_story="鲧禹父子在洪荒中对抗天命。",
    )
    assert len(drafts) == 2
    opening = drafts[0]["content"]
    assert "【片头·集号叠字】第1集｜羽山刑场" in opening
    assert "【片头·剧名叠字】大禹治水" in opening
    assert "【背景介绍·画面叠字】" in opening
    assert "【人物介绍·画面叠字·角色身旁】鲧" not in opening

    joined = "\n---\n".join(d["content"] for d in drafts)
    assert "【人物介绍·画面叠字·角色身旁】鲧｜治水先驱" in joined
    assert "【人物介绍·画面叠字·角色身旁】禹｜治水英雄" in joined
    assert joined.count("【人物介绍·画面叠字·角色身旁】鲧｜") == 1
    assert "【人物介绍·画面叠字·角色身旁】行刑兵" not in joined


def test_normalize_llm_links_prop_and_material():
    assets = [
        SimpleNamespace(id=1, type="character", name="禹", params={"title": "治水", "roleType": "主角"}),
        SimpleNamespace(id=10, type="scene", name="裂石崖", params={}),
        SimpleNamespace(id=20, type="prop", name="开山斧", params={}),
        SimpleNamespace(id=21, type="material", name="定海针", params={}),
    ]
    items = [
        {
            "duration_sec": 12,
            "scene_name": "裂石崖",
            "character_names": ["禹"],
            "prop_names": ["开山斧"],
            "material_names": ["定海针"],
            "lines": [
                "全景：禹右手握开山斧，左手持定海针立于裂石崖边。",
            ],
        },
    ]
    drafts = normalize_llm_fragment_items(items, assets)
    assert len(drafts) == 1
    content = drafts[0]["content"]
    ids = drafts[0]["asset_ids"]
    assert 20 in ids and 21 in ids and 1 in ids and 10 in ids
    assert "@asset:20" in content
    assert "@asset:21" in content


def test_build_asset_catalog_excludes_material_and_voice():
    from app.services.drama.fragment_plan import build_asset_catalog

    assets = [
        SimpleNamespace(id=1, type="character", name="禹", params={}),
        SimpleNamespace(id=2, type="prop", name="开山斧", params={}),
        SimpleNamespace(id=3, type="material", name="定海针", params={}),
        SimpleNamespace(id=4, type="voice", name="旁白", params={}),
    ]
    catalog = build_asset_catalog(assets)
    kinds = {c["type"] for c in catalog}
    assert "character" in kinds and "prop" in kinds
    assert "material" not in kinds
    assert "voice" not in kinds


def test_normalize_llm_splits_when_durations_exceed_hard_max():
    # LLM 把过多对白塞进一镜时，规范化须按 30s 硬上限拆成多条
    import re

    long = "这是一句足够长的对白用来推高单行估算时长到上限附近，确保多行合计必然超过三十秒硬上限。"
    assets = [
        SimpleNamespace(id=1, type="character", name="禹", params={"title": "治水", "roleType": "主角"}),
        SimpleNamespace(id=10, type="scene", name="工地", params={}),
    ]
    items = [
        {
            "duration_sec": 30,
            "scene_name": "工地",
            "character_names": ["禹"],
            "lines": [
                f"禹：{long}",
                f"禹：{long}",
                f"禹：{long}",
                f"禹：{long}",
                f"禹：{long}",
            ],
        },
    ]
    drafts = normalize_llm_fragment_items(items, assets)
    assert len(drafts) >= 2
    for draft in drafts:
        total = sum(int(m) for m in re.findall(r"@duration:(\d+)", draft["content"]))
        assert total <= 30
        assert draft["duration_sec"] == total
