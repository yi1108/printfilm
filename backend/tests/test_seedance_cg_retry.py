"""Seedance 视频文案策略 → CG 风格重试辅助。"""

from app.services.ark import ArkGateway, _SEEDREAM_CG_STYLE


def test_seedance_privacy_not_text_policy():
    raw = (
        '{"error":{"code":"InputImageSensitive","message":'
        '"PrivacyInformation: may contain real person in content[2]"}}'
    )
    assert ArkGateway._is_seedance_input_privacy_error(raw)
    assert not ArkGateway._is_seedance_text_policy_error(raw)


def test_seedance_text_policy_detects_input_text_sensitive():
    raw = '{"error":{"code":"InputTextSensitive","message":"text sensitive"}}'
    assert not ArkGateway._is_seedance_input_privacy_error(raw)
    assert ArkGateway._is_seedance_text_policy_error(raw)


def test_seedance_text_policy_case_insensitive():
    raw = '{"error":{"message":"Text Sensitive content rejected"}}'
    assert ArkGateway._is_seedance_text_policy_error(raw)


def test_seedance_scd_without_privacy_is_text_policy():
    raw = '{"error":{"code":"SensitiveContentDetected","message":"SensitiveContent"}}'
    assert not ArkGateway._is_seedance_input_privacy_error(raw)
    assert ArkGateway._is_seedance_text_policy_error(raw)


def test_seedance_scd_with_privacy_skips_text_policy():
    raw = (
        '{"error":{"code":"SensitiveContentDetected","message":'
        '"PrivacyInformation may contain real person"}}'
    )
    assert ArkGateway._is_seedance_input_privacy_error(raw)
    assert not ArkGateway._is_seedance_text_policy_error(raw)


def test_seedance_text_policy_detects_zh_formatted():
    msg = "分镜文案未通过内容审核，请修改敏感表述后重试"
    assert ArkGateway._is_seedance_text_policy_error(msg)


def test_seedance_content_with_cg_style_appends_once():
    content = [
        {"type": "text", "text": "暴雨夜巷口，主角踉跄奔逃"},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}, "role": "reference_image"},
    ]
    patched = ArkGateway._seedance_content_with_cg_style(content)
    assert patched is not None
    assert patched[0]["type"] == "text"
    assert "暴雨夜巷口" in patched[0]["text"]
    assert _SEEDREAM_CG_STYLE in patched[0]["text"]
    assert patched[1]["type"] == "image_url"
    # 已含 CG 再调应返回 None
    assert ArkGateway._seedance_content_with_cg_style(patched) is None


def test_seedance_content_with_cg_style_empty():
    assert ArkGateway._seedance_content_with_cg_style(None) is None
    assert ArkGateway._seedance_content_with_cg_style([]) is None
