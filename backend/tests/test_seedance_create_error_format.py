"""Seedance 创建错误中文化。"""

from app.services.ark import _format_seedance_create_error


def test_format_seedance_audio_duration_too_short_with_label():
    body = (
        '{"error":{"code":"InvalidParameter","message":'
        '"The parameter `content[8]` specified in the request is not valid: '
        "the parameter audio duration (seconds) specified in the request must be "
        'greater than or equal to 1.8 for model doubao-seedance-2-5 in r2v."}}'
    )
    labels = [
        "分镜文案",
        "角色「甲」",
        "角色「乙」",
        "场景「天劫」",
        "道具「剑」",
        "角色「丙」",
        "角色「丁」",
        "场景「凡间」",
        "角色音色「双龙」",
    ]
    msg = _format_seedance_create_error(400, body, content_labels=labels)
    assert "参考音频过短" in msg
    assert "角色音色「双龙」" in msg
    assert "1.8" in msg


def test_format_seedance_audio_duration_without_labels():
    body = (
        '{"error":{"message":"content[3] audio duration must be greater than or equal to 1.8"}}'
    )
    msg = _format_seedance_create_error(400, body, content_labels=None)
    assert "参考音频过短" in msg
    assert "content[3]" in msg
