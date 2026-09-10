"""本剧跨集人物介绍去重。"""

from types import SimpleNamespace

from app.services.drama.build_fragments import (
    collect_series_introduced_names,
    extract_introduced_names_from_content,
)
from app.services.drama.fragment_plan import normalize_llm_fragment_items


def test_extract_introduced_names_from_content():
    content = "\n".join(
        [
            "【字幕：底部居中】",
            "【人物介绍·画面叠字·角色身旁】鲧｜治水先驱",
            "【人物介绍·画面叠字·角色身旁】禹｜治水英雄",
            "@duration:3",
        ]
    )
    assert extract_introduced_names_from_content(content) == ["鲧", "禹"]


def test_collect_series_introduced_names_skips_later_episodes():
    ep1 = SimpleNamespace(
        id=1,
        params={"episodeNumber": 1},
        fragments=[
            SimpleNamespace(content="【人物介绍·画面叠字·角色身旁】鲧｜治水先驱\n画面"),
        ],
    )
    ep2 = SimpleNamespace(
        id=2,
        params={"episodeNumber": 2},
        fragments=[
            SimpleNamespace(content="【人物介绍·画面叠字·角色身旁】禹｜治水英雄\n画面"),
        ],
    )
    before_ep2 = collect_series_introduced_names([ep1, ep2], before_episode_number=2)
    assert before_ep2 == {"鲧"}
    before_ep3 = collect_series_introduced_names([ep1, ep2], before_episode_number=3)
    assert before_ep3 == {"鲧", "禹"}


def test_normalize_skips_series_already_introduced():
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
    ]
    items = [
        {
            "duration_sec": 8,
            "is_opening": True,
            "character_names": [],
            "lines": ["空镜开场。"],
        },
        {
            "duration_sec": 10,
            "character_names": ["鲧", "禹"],
            "lines": ["鲧看着禹。", "禹：父亲。"],
        },
    ]
    drafts = normalize_llm_fragment_items(
        items,
        assets,
        episode_number=2,
        episode_name="父子重逢",
        already_introduced={"鲧"},
    )
    joined = "\n".join(d["content"] for d in drafts)
    assert "【人物介绍·画面叠字·角色身旁】鲧" not in joined
    assert "【人物介绍·画面叠字·角色身旁】禹｜治水英雄" in joined
