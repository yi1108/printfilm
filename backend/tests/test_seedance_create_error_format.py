"""Seedance 创建错误中文化。"""

from app.services.ark import _format_seedance_create_error


def test_format_seedance_invalid_image_format():
    body = (
        '{"error":{"code":"InvalidParameter","message":'
        '"The parameter `content[3]` specified in the request is not valid: '
        'invalid image format (detected format); received: M4A. '
        'Request id: 021792136049408d"}}'
    )
    labels = ["分镜文案", "角色「甲」", "场景「室」", "参考图「试听」"]
    msg = _format_seedance_create_error(400, body, content_labels=labels)
    assert "参考图格式无效" in msg
    assert "试听" in msg
    assert "1.8" not in msg


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


def test_format_seedance_output_duration_invalid_for_2_0():
    body = (
        '{"code":"fail_to_fetch_task","message":"{\\"error\\":{\\"code\\":\\"InvalidParameter\\",'
        '\\"message\\":\\"the parameter duration specified in the request is not valid for model '
        'doubao-seedance-2-0 in r2v\\"}}"}'
    )
    msg = _format_seedance_create_error(400, body)
    assert "4–15" in msg
    assert "15 秒" in msg


def test_format_seedance_model_not_found_2_5():
    body = (
        '{"error":{"code":"model_not_found","message":'
        '"分组 default 下模型 seedance-2.5 无可用渠道（distributor）","type":"new_api_error"}}'
    )
    msg = _format_seedance_create_error(503, body)
    assert "未开通" in msg
    assert "2.0" in msg


def test_duplicate_first_frame_has_actionable_chinese_message():
    msg = _format_seedance_create_error(400, 'expected at most one first frame image content but got 2 instead')
    assert "首帧只能设置一张" in msg and "全能参考" in msg
