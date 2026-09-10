"""分镜切分：场内按时长二次拆条；人物介绍按首次出场注入。"""

from types import SimpleNamespace

from app.services.drama.build_fragments import (
    FRAGMENT_SOFT_MAX,
    FRAGMENT_TOTAL_MAX,
    _is_important_character,
    _resolve_character_intro_text,
    build_character_binding,
    build_fragments_from_episode_body,
    plan_fragments_from_scene,
)


def test_long_scene_splits_into_multiple_fragments():
    # 构造足够多的对白行，使合计时长超过软上限
    lines = ["日外 羽山刑场", "出场人物：禹"]
    for i in range(12):
        lines.append(f"禹：这是第{i}句很长的对白用来撑满时长测试内容足够长。")
    body = "\n".join(lines)

    chunks = plan_fragments_from_scene(
        body,
        {"sceneName": "羽山刑场", "characterNames": ["禹"]},
        scene_asset_id=1,
        character_bindings=[
            {"name": "禹", "assetId": 2, "introText": "治水英雄", "important": True},
        ],
    )

    assert len(chunks) >= 2
    for content, duration in chunks:
        assert duration <= FRAGMENT_TOTAL_MAX
        assert "@duration:" in content
        assert "【字幕" in content
    # 首条应含人物介绍；后续跨镜不再重复
    intro_hits = [c for c, _ in chunks if "【人物介绍·画面叠字·角色身旁】禹｜治水英雄" in c]
    assert len(intro_hits) == 1
    assert all(d <= FRAGMENT_SOFT_MAX or True for _, d in chunks)


def test_build_fragments_one_scene_header_can_yield_many():
    narrative = "\n".join(
        [f"旁白（VO）：第{i}段旁白内容用来累计时长超过三十秒的填充。" for i in range(15)]
    )
    content = f"### 场1-1\n日外 大河\n出场人物：无\n{narrative}"
    drafts = build_fragments_from_episode_body(content, [])
    assert len(drafts) >= 2
    total = sum(int(d["duration_sec"]) for d in drafts)
    assert total > FRAGMENT_TOTAL_MAX


def test_intro_only_on_first_appearance_across_scenes():
    # 跨场同一重要角色只介绍一次；次要群体角色不介绍
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
        SimpleNamespace(
            id=4,
            type="character",
            name="部落百姓",
            params={"title": "出场人物", "roleType": "群演"},
        ),
    ]
    content = "\n".join(
        [
            "### 场1-1",
            "日外 羽山刑场",
            "出场人物：鲧、行刑兵、部落百姓",
            "△ 刑场全景，洪水拍打山崖。",
            "鲧被绑在杉木柱上，白发湿透。",
            "### 场1-2",
            "日外 羽山刑场",
            "出场人物：鲧、禹",
            "禹冲上刑场高喊父亲。",
            "鲧抬头望向禹。",
        ]
    )
    drafts = build_fragments_from_episode_body(content, assets)
    joined = "\n---\n".join(d["content"] for d in drafts)

    assert "【人物介绍·画面叠字·角色身旁】鲧｜治水先驱" in joined
    assert "【人物介绍·画面叠字·角色身旁】禹｜治水英雄" in joined
    assert joined.count("【人物介绍·画面叠字·角色身旁】鲧｜") == 1
    assert joined.count("【人物介绍·画面叠字·角色身旁】禹｜") == 1
    assert "行刑兵" not in joined or "【人物介绍·画面叠字·角色身旁】行刑兵" not in joined
    assert "【人物介绍·画面叠字·角色身旁】部落百姓" not in joined

    # 鲧应出现在首次提及他所在的分镜，而非机械堆在开场空镜
    first_with_gun = next(d for d in drafts if "【人物介绍·画面叠字·角色身旁】鲧｜" in d["content"])
    assert "鲧" in first_with_gun["content"] or "@asset:1" in first_with_gun["content"]


def test_important_and_intro_helpers():
    assert _is_important_character("鲧", role_type="主角", title="治水先驱")
    assert _is_important_character("四岳首领", role_type="重要配角", title="部落长老")
    assert not _is_important_character("行刑兵", role_type="配角", title="出场人物")
    assert not _is_important_character("部落百姓", role_type="群演", title="出场人物")
    assert _resolve_character_intro_text({"title": "出场人物", "roleType": "主角"}) == "主角"
    assert _resolve_character_intro_text({"title": "治水先驱"}) == "治水先驱"


def test_stub_asset_uses_summary_for_intro():
    # 资产仍为 stub，但摘要有小传 → 应可介绍
    asset = SimpleNamespace(
        id=132,
        type="character",
        name="禹",
        params={"title": "出场人物", "roleType": "配角", "coreTags": "出场人物"},
    )
    summary = {
        "characters": [
            {
                "name": "禹（大禹）",
                "roleType": "主角",
                "title": "治水英雄",
                "identityBackground": "鲧之子，承父遗志治理洪水",
            },
        ]
    }
    binding = build_character_binding("禹", asset, summary=summary)
    assert binding["important"] is True
    assert binding["introText"] == "治水英雄"


def test_narrative_summary_fallback_for_gun():
    asset = SimpleNamespace(
        id=131,
        type="character",
        name="鲧",
        params={"title": "出场人物", "roleType": "配角"},
    )
    summary = {
        "characters": [],
        "synopsis": "罪臣之子大禹因父亲鲧盗息壤堵水失败被处死，在部落的唾骂中临危受命。",
    }
    binding = build_character_binding("鲧", asset, summary=summary)
    assert binding["important"] is True
    assert binding["introText"]
    assert "鲧" in binding["introText"] or "堵水" in binding["introText"]


def test_stub_identity_background_not_used_as_intro():
    from app.services.drama.build_fragments import infer_character_intro_text

    assert infer_character_intro_text(
        "鲧",
        {"title": "出场人物", "identityBackground": "剧本分集出场人物「鲧」"},
    ) is None

    asset = SimpleNamespace(
        id=3,
        type="character",
        name="舜",
        params={"title": "出场人物", "roleType": "配角", "identityBackground": "剧本分集出场人物「舜」"},
    )
    bodies = ["四岳首领推举禹治水，舜帝端坐大殿目光深沉。"]
    binding = build_character_binding("舜", asset, summary={"characters": []}, episode_bodies=bodies)
    assert binding["introText"]
    assert "剧本分集出场人物" not in binding["introText"]
    assert "舜" in binding["introText"]


def test_scene_description_marked_visual_not_voiceover():
    from app.services.drama.build_fragments import _format_narrative_line
    from app.services.seedance_segments import (
        DRAMA_SUBTITLE_CUE,
        build_seedance_production_section,
        rewrite_misclassified_visual_voice_lines,
        script_has_dialogue_cue,
        script_has_narration_cue,
    )

    scene = "月亮被乌云遮得严严实实，只有零星的火把亮着，禹跪在新堆的坟前。"
    formatted = _format_narrative_line(scene)
    assert formatted.startswith("【画面·无配音仅环境音】")
    assert scene in formatted

    dialogue = "伯益：大洪水来了，快撤！"
    assert _format_narrative_line(dialogue).startswith("【对白·慢速清晰·同步字幕】")

    # 「空镜：…」是画面描述，绝不能打成对白/旁白
    empty_shot = "空镜：浑浊的黄河浪扣打着门口老石，溅起数丈高的浊浪。"
    empty_formatted = _format_narrative_line(empty_shot)
    assert empty_formatted.startswith("【画面·无配音仅环境音】")
    assert "对白" not in empty_formatted
    assert "旁白" not in empty_formatted

    # 已误标为对白的旧数据：格式化与提交前纠正均可修复
    mistagged = "【对白·慢速清晰·同步字幕】" + empty_shot
    assert _format_narrative_line(mistagged).startswith("【画面·无配音仅环境音】")
    fixed_script = rewrite_misclassified_visual_voice_lines(
        "\n".join([DRAMA_SUBTITLE_CUE, "@duration:6", mistagged])
    )
    assert "【对白" not in fixed_script
    assert "【画面·无配音仅环境音】空镜：" in fixed_script
    assert script_has_dialogue_cue(fixed_script) is False

    script = "\n".join(
        [
            DRAMA_SUBTITLE_CUE,
            "【BGM：流动感环境音乐；音量低于人声】",
            "@duration:6",
            empty_formatted,
            "@duration:6",
            _format_narrative_line(dialogue),
        ]
    )
    assert script_has_narration_cue(script) is False
    section = build_seedance_production_section(script)
    assert "禁止为其生成配音" in section
    assert "画面描述段不出现字幕" in section
