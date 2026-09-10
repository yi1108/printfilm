"""超长分镜按 @duration 拆分。"""

from app.services.drama.build_fragments import split_overlong_fragment_content


def test_split_overlong_keeps_header_and_caps_chunks():
    content = "\n".join(
        [
            "【字幕：底部居中·简体中文·仅标记段落同步】",
            "【BGM：庄重史诗】",
            "@duration:8",
            "【对白·慢速清晰·同步字幕】禹：第一段足够长的对白内容用来占满时长。",
            "@duration:8",
            "【对白·慢速清晰·同步字幕】禹：第二段继续讲治水方案与人心。",
            "@duration:8",
            "【对白·慢速清晰·同步字幕】禹：第三段再补一句把合计推过三十秒。",
            "@duration:8",
            "【对白·慢速清晰·同步字幕】禹：第四段必须落到下一镜。",
        ]
    )
    chunks = split_overlong_fragment_content(content)
    assert len(chunks) >= 2
    for text, dur in chunks:
        assert "【字幕：" in text
        assert dur <= 30
        assert text.count("@duration:") >= 1
