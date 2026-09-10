"""Unit tests for manju-style segment planning."""

from app.services.seedance_segments import (
    NARRATION_PREFIX,
    SEEDANCE_PRODUCTION_SECTION_HEADER,
    SegmentBeat,
    apply_segment_script_edit,
    build_segment_script,
    build_seedance_production_section,
    build_seedance_prompt,
    estimate_narration_duration,
    first_visual_prompt,
    narration_from_script,
    parse_beats_from_llm_shot,
    replace_duration_with_time_ranges,
    replace_first_visual_in_script,
    replace_narration_in_script,
    resolve_api_duration,
    suggested_kepu_shot_range,
    sum_duration,
)


def test_build_segment_script_and_time_ranges():
    script = build_segment_script(
        [
            SegmentBeat(duration=4, kind="visual", text="过肩工位打开工作台"),
            SegmentBeat(duration=8, kind="narration", text="很多人找开源工具却卡在接入"),
        ],
        bgm_mood="轻快专业",
    )
    assert "【字幕：" in script
    assert "【BGM：" in script
    assert "@duration:4" in script
    assert "@duration:8" in script
    assert "【旁白·自然语速·同步字幕】" in script
    assert sum_duration(script) == 12
    timed = replace_duration_with_time_ranges(script)
    assert "00:00-00:04" in timed
    assert "00:04-00:12" in timed
    assert resolve_api_duration(script) == 12
    assert "很多人找开源工具" in narration_from_script(script)


def test_build_seedance_prompt_includes_style_and_production():
    script = build_segment_script(
        [
            SegmentBeat(duration=5, kind="visual", text="手部点击配置"),
            SegmentBeat(duration=6, kind="narration", text="一键接入即可开始监控"),
        ],
        bgm_mood="轻快专业",
    )
    prompt = build_seedance_prompt(
        script, style_prefix="真人写实工位", motion_bias="轻推", camera="缓慢推近"
    )
    assert "强制约束：视频画面风格" in prompt
    assert "真人写实工位" in prompt
    assert SEEDANCE_PRODUCTION_SECTION_HEADER in prompt
    assert "语速" in prompt
    assert "字幕" in prompt
    assert "背景音乐" in prompt
    assert "00:00-00:05" in prompt
    assert NARRATION_PREFIX in prompt or "旁白" in prompt


def test_build_seedance_production_section_detects_vo():
    script = (
        "【字幕：全程简体中文字幕，旁白逐句同步烧录】\n"
        "【BGM：轻快专业，音量低于人声】\n"
        "@duration:4\n过肩演示\n"
        f"@duration:8\n{NARRATION_PREFIX}口播一句"
    )
    section = build_seedance_production_section(script)
    assert section.startswith(SEEDANCE_PRODUCTION_SECTION_HEADER)
    assert "第三人称旁白配音" in section
    assert "自然偏快" in section
    assert "轻快专业" in section


def test_parse_beats_clamps_short_narration_duration():
    beats = parse_beats_from_llm_shot(
        {
            "segments": [
                {"kind": "visual", "duration": 4, "text": "过肩景，程序员点击触控板"},
                {
                    "kind": "narration",
                    "duration": 3,
                    "text": "还在被网站加载慢、用户流失、性能问题反复出现困扰吗？",
                },
            ]
        }
    )
    assert len(beats) == 2
    assert beats[0].duration == 4
    # 旁白按字数估时应大于等于 LLM 给的 3 秒
    assert beats[1].duration >= 3
    assert beats[1].duration <= 12


def test_parse_beats_does_not_pad_short_narration_to_shot_max():
    text = "质检痛点切入。"
    est = estimate_narration_duration(text)
    beats = parse_beats_from_llm_shot(
        {
            "segments": [
                {"kind": "visual", "duration": 4, "text": "工位过肩打开质检看板"},
                {"kind": "narration", "duration": 20, "text": text},
            ]
        }
    )
    assert beats[1].duration <= est + 1
    assert beats[1].duration >= est
    assert beats[1].duration < 12


def test_suggested_kepu_shot_range_full_mode():
    short = suggested_kepu_shot_range("工业AI平台简介", pipeline_mode="full")
    medium = suggested_kepu_shot_range("字" * 250, pipeline_mode="full")
    long = suggested_kepu_shot_range("字" * 500, pipeline_mode="full")
    assert short == (6, 8)
    assert medium == (7, 10)
    assert long == (8, 10)


def test_apply_segment_script_edit_fills_cues():
    out = apply_segment_script_edit(
        "@duration:6\n过肩演示产品\n@duration:6\n【旁白·自然语速·同步字幕】一句话介绍能力",
        bgm_mood="冷静纪实",
    )
    assert out["duration"] == 12.0
    assert "【字幕：" in out["segment_script"]
    assert "【BGM：" in out["segment_script"]
    assert out["narration"]


def test_replace_narration_and_visual_write_back_into_script():
    script = (
        "【字幕：全程简体中文字幕，旁白逐句同步烧录】\n"
        "【BGM：轻快专业，音量低于人声】\n"
        "@duration:4\n侧脸打开深色仪表盘\n"
        f"@duration:8\n{NARRATION_PREFIX}旧旁白一句"
    )
    with_vo = replace_narration_in_script(script, "一句话给出方向和信心度。")
    assert "旧旁白一句" not in with_vo
    assert narration_from_script(with_vo) == "一句话给出方向和信心度。"
    with_vis = replace_first_visual_in_script(with_vo, "过肩工位，大屏亮绿色看多信号")
    assert first_visual_prompt(with_vis) == "过肩工位，大屏亮绿色看多信号"
    assert "侧脸打开深色仪表盘" not in with_vis


def test_empty_shot_misclassified_as_dialogue_is_rewritten():
    from app.services.seedance_segments import (
        DRAMA_SUBTITLE_CUE,
        rewrite_misclassified_visual_voice_lines,
        script_has_dialogue_cue,
        script_has_visual_only_cue,
    )

    mistagged = "\n".join(
        [
            DRAMA_SUBTITLE_CUE,
            "【BGM：流动感环境音乐；音量低于人声】",
            "@duration:6",
            "【对白·慢速清晰·同步字幕】空镜：浑浊的黄河浪扣打着门口老石。",
        ]
    )
    fixed = rewrite_misclassified_visual_voice_lines(mistagged)
    assert "【对白" not in fixed
    assert "【画面·无配音仅环境音】空镜：" in fixed
    assert script_has_dialogue_cue(fixed) is False
    assert script_has_visual_only_cue(fixed) is True
    section = build_seedance_production_section(fixed)
    assert "禁止为其生成配音" in section
    assert "画面描述段不出现字幕" in section
    assert "逐句轮换" in section


def test_legacy_drama_subtitle_cue_normalized_on_rewrite():
    from app.services.seedance_segments import (
        DRAMA_SUBTITLE_CUE,
        rewrite_misclassified_visual_voice_lines,
    )

    legacy = "【字幕：底部居中·简体中文·仅标记段落同步】\n@duration:4\n空镜：黄河浪。"
    fixed = rewrite_misclassified_visual_voice_lines(legacy)
    assert DRAMA_SUBTITLE_CUE in fixed
    assert "仅标记段落同步" not in fixed
    assert "逐句轮换" in build_seedance_production_section(fixed)


def test_character_intro_cue_normalized_beside_character():
    from app.services.seedance_segments import rewrite_misclassified_visual_voice_lines

    legacy = "【人物介绍·画面叠字】禹｜治水英雄\n@duration:4\n【对白·慢速清晰·同步字幕】禹：水患未平。"
    fixed = rewrite_misclassified_visual_voice_lines(legacy)
    assert "【人物介绍·画面叠字·角色身旁】禹｜治水英雄" in fixed
    assert "【人物介绍·画面叠字】禹" not in fixed.replace("【人物介绍·画面叠字·角色身旁】", "")
    section = build_seedance_production_section(fixed)
    assert "角色身旁" in section
    assert "禁止居中大标题" in section


def test_build_seedance_production_section_ambient_only():
    script = build_segment_script(
        [
            SegmentBeat(duration=4, kind="visual", text="过肩工位打开工作台"),
            SegmentBeat(duration=8, kind="narration", text="很多人找开源工具却卡在接入"),
        ],
        bgm_mood="轻快专业",
    )
    section = build_seedance_production_section(script, ambient_only=True)
    assert section.startswith(SEEDANCE_PRODUCTION_SECTION_HEADER)
    assert "后期外部 TTS" in section
    assert "禁止任何旁白" in section
    assert "禁止任何 BGM" in section
    assert "操作环境音" in section
    assert "第三人称旁白配音" not in section
    assert "轻快专业" not in section


def test_build_seedance_prompt_ambient_only_rewrites_narration():
    from app.services.seedance_segments import seedance_timeline_without_voice

    script = build_segment_script(
        [
            SegmentBeat(duration=5, kind="visual", text="手部点击配置"),
            SegmentBeat(duration=6, kind="narration", text="一键接入即可开始监控"),
        ],
        bgm_mood="轻快专业",
    )
    body = seedance_timeline_without_voice(script)
    assert "手部点击配置" in body
    assert "一键接入即可开始监控" not in body
    assert "【BGM" not in body
    assert "【字幕" not in body
    assert "无配音仅环境音" in body

    prompt = build_seedance_prompt(script, ambient_only=True)
    assert "禁止任何旁白" in prompt
    assert "一键接入即可开始监控" not in prompt
    assert "00:00-00:05" in prompt
    assert NARRATION_PREFIX not in prompt
