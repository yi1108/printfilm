"""TokenFree 生图走 /v1/responses。"""

import json
from types import SimpleNamespace

import pytest

from app.services.tokenfree_image import (
    build_tokenfree_image_body,
    extract_tokenfree_image_url,
    is_tokenfree_input_text_sensitive,
    is_tokenfree_no_distributor,
    is_tokenfree_protocol_error,
    is_tokenfree_rate_limit,
    is_tokenfree_retryable_image_error,
    post_until_not_rate_limited,
    raise_tokenfree_image_if_failed,
    tokenfree_image_channel_dead,
    tokenfree_image_user_error,
    tokenfree_working_image_model,
    uses_tokenfree_image,
)
from app.services.tokenfree_gateway import TOKENFREE_BASE_URL, TOKENFREE_CHANNEL_ID


def test_uses_tokenfree_image_on_tokenfree_host():
    assert uses_tokenfree_image(base_url=TOKENFREE_BASE_URL) is True
    assert uses_tokenfree_image(channel_id=TOKENFREE_CHANNEL_ID) is True
    assert uses_tokenfree_image(base_url="https://ark.cn-beijing.volces.com/api/v3") is True


def test_build_tokenfree_image_body_matches_live_success():
    body = build_tokenfree_image_body(model="gpt-image-2", prompt="橘猫", size="2K")
    assert body["model"] == "gpt-image-2"
    assert "橘猫" in body["input"]
    assert "输出清晰度2K" in body["input"]
    assert "size:" not in body["input"]
    assert "prompt" not in body
    assert "watermark" not in body


def test_build_tokenfree_image_body_includes_aspect_ratio():
    """UI 所选画幅必须进自然语言 input，不能只写清晰度。"""
    body = build_tokenfree_image_body(
        model="gpt-image-2",
        prompt="国风角色设定板",
        size="2K",
        aspect_ratio="16:9",
    )
    text = body["input"]
    assert "输出画幅必须为16:9" in text
    assert "横构图" in text
    assert "输出清晰度2K" in text
    assert "输出清晰度2816x1584" not in text


def test_build_tokenfree_image_body_pixel_size_not_called_clarity():
    body = build_tokenfree_image_body(
        model="gpt-image-2",
        prompt="场景",
        size="2816x1584",
        aspect_ratio="16:9",
    )
    text = body["input"]
    assert "目标像素约2816x1584" in text
    assert "输出画幅必须为16:9" in text
    assert "输出清晰度2816x1584" not in text


def test_build_tokenfree_image_body_separates_style_and_subject_refs():
    body = build_tokenfree_image_body(
        model="gpt-image-2",
        prompt="少女站在窗边",
        ref_urls=["https://cdn.example.com/character.png"],
        style_ref_urls=["https://cdn.example.com/ghibli.png"],
    )
    text = body["input"]
    assert "画风参考图（只借色调、笔触、光影，禁止抄主体与构图）：https://cdn.example.com/ghibli.png" in text
    assert "构图与主体参考：https://cdn.example.com/character.png" in text
    assert text.index("画风参考图") < text.index("构图与主体参考")


def test_gpt_image_25_uses_openai_generations_body():
    """2.5 必须走 images/generations 字段，并带 resolution 供 1K/2K/4K 计费。"""
    from app.services.tokenfree_image import (
        build_tokenfree_openai_image_body,
        gpt_image_resolution_tier,
        is_gpt_image_25,
    )

    assert is_gpt_image_25("gpt-image-2.5") is True
    assert is_gpt_image_25("gpt-image-2") is False
    assert gpt_image_resolution_tier("3520x4694") == "4K"
    assert gpt_image_resolution_tier("1776x2368") == "2K"
    body = build_tokenfree_openai_image_body(
        model="gpt-image-2.5",
        prompt="角色设定",
        size="1776x2368",
        aspect_ratio="3:4",
    )
    assert body["model"] == "gpt-image-2.5"
    assert body["size"] == "1776x2368"
    assert body["resolution"] == "2K"
    assert body["response_format"] == "url"
    assert "prompt" in body and "input" not in body
    assert "3:4" in body["prompt"]


def test_tokenfree_working_image_model_passthrough():
    """按渠道配置原样发送，不硬改 Seedream / 2.5。"""
    assert tokenfree_working_image_model("seedream-5-0-pro") == "seedream-5-0-pro"
    assert tokenfree_working_image_model("gpt-image-2-5") == "gpt-image-2-5"
    assert tokenfree_working_image_model("gpt-image-2-5-sunburst") == "gpt-image-2-5-sunburst"
    assert tokenfree_working_image_model("doubao-seedream-5-0-260128") == "doubao-seedream-5-0-260128"
    assert tokenfree_working_image_model("gpt-image-2") == "gpt-image-2"
    assert tokenfree_working_image_model("gpt-image-2.0") == "gpt-image-2.0"


def test_extract_tokenfree_image_url_from_img_tag():
    url = extract_tokenfree_image_url(
        {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '<img src="https://www.tokenfree.com/v1/tasks/t1/artifacts/image-0/content?access=x" />',
                        }
                    ]
                }
            ]
        }
    )
    assert url and url.startswith("https://www.tokenfree.com/v1/tasks/")


def test_extract_tokenfree_image_url_from_bare_https():
    """纯 URL 文本走 _URL_RE（无捕获组），不能再 group(1)。"""
    url = extract_tokenfree_image_url(
        {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "https://www.tokenfree.com/v1/tasks/t2/artifacts/image-0/content?access=y",
                        }
                    ]
                }
            ]
        }
    )
    assert url == "https://www.tokenfree.com/v1/tasks/t2/artifacts/image-0/content?access=y"


def test_failed_responses_payload_is_user_error_not_missing_url():
    """HTTP 200 但 status=failed 时，应报上游任务失败，不要 Seedream missing url。"""
    payload = {
        "id": "resp_x",
        "status": "failed",
        "model": "gpt-image-2",
        "output": [],
        "error": {"code": "server_error", "message": "The task failed."},
        "metadata": {"task_status": "failed", "task_id": "task_x"},
    }
    with pytest.raises(RuntimeError, match="出图上游任务失败") as ei:
        raise_tokenfree_image_if_failed(payload)
    assert "Seedream missing url" not in str(ei.value)
    assert "resp_" not in str(ei.value)
    body = json.dumps(payload)
    assert is_tokenfree_retryable_image_error(status_code=200, body=body) is True
    assert is_tokenfree_retryable_image_error(status_code=400, body=body) is False
    http_msg = tokenfree_image_user_error(model="gpt-image-2", status_code=200, body=body)
    assert "出图上游任务失败" in http_msg
    assert "resp_" not in http_msg


def test_is_tokenfree_rate_limit_detects_observations():
    body = '{"error":{"code":"rate_limit_exceeded","message":"Too many active task observations"}}'
    assert is_tokenfree_rate_limit(status_code=429, body="") is True
    assert is_tokenfree_rate_limit(status_code=200, body=body) is True
    assert is_tokenfree_rate_limit(status_code=200, body='{"usage":{"rate_limit":{"remaining":1}}}') is False
    assert is_tokenfree_rate_limit(status_code=503, body="model_not_found") is False


def test_is_tokenfree_protocol_error():
    body = '{"error":{"code":"task_protocol_error","message":"Task protocol request failed"}}'
    assert is_tokenfree_protocol_error(status_code=502, body=body) is True
    assert is_tokenfree_protocol_error(status_code=200, body='{"id":"ok"}') is False
    invalid = '{"error":{"code":"invalid_request_error","message":"Invalid task protocol request"}}'
    assert is_tokenfree_protocol_error(status_code=400, body=invalid) is True
    assert is_tokenfree_retryable_image_error(status_code=502, body=body) is False
    assert tokenfree_image_channel_dead(status_code=502, body=body) is True


def test_sunburst_model_not_found_is_channel_dead():
    """default 组没有 sunburst distributor 时，应判定通道不可用而不是限流。"""
    body = (
        '{"error":{"code":"model_not_found",'
        '"message":"分组 default 下模型 gpt-image-2-5-sunburst 无可用的渠道distributor"}}'
    )
    assert is_tokenfree_no_distributor(status_code=503, body=body) is True
    msg = tokenfree_image_user_error(
        model="gpt-image-2.5", status_code=503, body=body
    )
    assert "未开通" in msg
    assert "gpt-image-2.5" in msg


def test_is_tokenfree_no_distributor():
    """503 model_not_found 视为无线路，不再当限流重试。"""
    body = '{"error":{"code":"model_not_found","message":"分组 default 下模型 gpt-image-2-5 无可用的渠道distributor"}}'
    assert is_tokenfree_no_distributor(status_code=503, body=body) is True
    assert tokenfree_image_channel_dead(status_code=503, body=body) is True
    assert is_tokenfree_retryable_image_error(status_code=503, body=body) is False


def test_tokenfree_image_user_error_does_not_nudge_switch_model():
    """TokenFree 通道挂了不再硬推 gpt-image-2；Seedream 协议失败单独提示。"""
    protocol = '{"error":{"code":"task_protocol_error","message":"Task protocol request failed"}}'
    gpt_msg = tokenfree_image_user_error(model="gpt-image-2", status_code=502, body=protocol)
    assert "请改用 gpt-image-2" not in gpt_msg
    assert "暂时失败" in gpt_msg
    seedream_msg = tokenfree_image_user_error(model="seedream-5-0-pro", status_code=502, body=protocol)
    assert "Seedream" in seedream_msg
    assert "请改用 gpt-image-2" not in seedream_msg


def test_raise_seedream_http_error_tokenfree_vs_ark():
    """TokenFree 走友好文案，官方方舟保持 Seedream error。"""
    from app.services.ark import _raise_seedream_http_error

    protocol = '{"error":{"code":"task_protocol_error","message":"Task protocol request failed"}}'
    with pytest.raises(RuntimeError, match="暂时失败"):
        _raise_seedream_http_error(502, protocol, model="gpt-image-2-5", tokenfree=True)
    with pytest.raises(RuntimeError, match="Seedream error 502"):
        _raise_seedream_http_error(502, protocol, model="gpt-image-2-5", tokenfree=False)


def test_is_tokenfree_input_text_sensitive_skips_protocol_and_429():
    """协议失败和限流不算审核，避免 compact/style_only 被通道故障误触发。"""
    protocol = '{"error":{"code":"task_protocol_error","message":"Task protocol request failed"}}'
    assert is_tokenfree_input_text_sensitive(status_code=502, body=protocol) is False
    assert is_tokenfree_input_text_sensitive(status_code=429, body="Too many active task observations") is False
    body = '{"error":{"code":"InputTextSensitive","message":"text sensitive"}}'
    assert is_tokenfree_input_text_sensitive(status_code=400, body=body) is True


def test_raise_seedream_http_error_tokenfree_moderation_uses_audit_text():
    """TokenFree 审核失败抛「内容审核」，才能走 compact/style_only。"""
    from app.services.ark import _raise_seedream_http_error

    body = '{"error":{"code":"InputTextSensitive","message":"text sensitive"}}'
    with pytest.raises(RuntimeError, match="内容审核"):
        _raise_seedream_http_error(400, body, model="gpt-image-2-5", tokenfree=True)


@pytest.mark.asyncio
async def test_post_until_not_rate_limited_retries_then_ok():
    calls = {"n": 0}
    sleeps: list[float] = []

    async def post():
        calls["n"] += 1
        if calls["n"] < 3:
            return SimpleNamespace(status_code=429, text="Too many active task observations")
        return SimpleNamespace(status_code=200, text="ok")

    async def fake_sleep(sec: float):
        sleeps.append(sec)

    resp = await post_until_not_rate_limited(post, delays=(0.1, 0.2), sleep=fake_sleep)
    assert resp.status_code == 200
    assert calls["n"] == 3
    assert sleeps == [0.1, 0.2]


@pytest.mark.asyncio
async def test_post_does_not_retry_protocol_error():
    """协议失败立即返回，避免空等四轮。"""
    calls = {"n": 0}

    async def post():
        calls["n"] += 1
        return SimpleNamespace(
            status_code=502,
            text='{"error":{"code":"task_protocol_error","message":"Task protocol request failed"}}',
        )

    async def fake_sleep(_sec: float):
        return None

    resp = await post_until_not_rate_limited(post, delays=(0.01,), sleep=fake_sleep)
    assert resp.status_code == 502
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_post_retries_http200_server_error_then_ok():
    """HTTP 200 + server_error 视为瞬时失败，退避后再试。"""
    calls = {"n": 0}
    failed = json.dumps(
        {
            "status": "failed",
            "output": [],
            "error": {"code": "server_error", "message": "The task failed."},
        }
    )

    async def post():
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(status_code=200, text=failed)
        return SimpleNamespace(status_code=200, text='{"status":"completed"}')

    async def fake_sleep(_sec: float):
        return None

    resp = await post_until_not_rate_limited(post, delays=(0.01,), sleep=fake_sleep)
    assert calls["n"] == 2
    assert "completed" in resp.text


@pytest.mark.asyncio
async def test_seedream_once_protocol_error_raises(monkeypatch):
    """TokenFree 协议失败时直接报错，不改打其它上游。"""
    from app.config import Settings
    from app.services.ark import ArkGateway

    settings = Settings(
        ark_mock=False,
        local_media_mock=False,
        ark_api_key="sk-test",
        ark_base_url="https://www.tokenfree.com/v1",
    )
    gw = ArkGateway(settings=settings)

    class _Resp:
        status_code = 502
        text = '{"error":{"code":"task_protocol_error","message":"Task protocol request failed"}}'

        def json(self):
            return {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr("app.services.ark.httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr(gw, "_resolve_ark_route", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="暂时失败"):
        await gw._seedream_once(
            "湖",
            None,
            project_id=1,
            shot_no=1,
            size="2k",
            model="gpt-image-2-5",
        )


@pytest.mark.asyncio
async def test_seedream_once_http200_failed_task(monkeypatch):
    """同步 /responses 返回 200 + status=failed 时，中文报错且不吐 JSON。"""
    from app.config import Settings
    from app.services.ark import ArkGateway

    payload = {
        "created_at": 1789538577,
        "error": {"code": "server_error", "message": "The task failed."},
        "id": "resp_gagCp3JX4JSSQ798RHcnzT6o1hxxkYs6",
        "model": "gpt-image-2",
        "output": [],
        "status": "failed",
        "metadata": {"task_id": "task_x", "task_status": "failed"},
    }
    settings = Settings(
        ark_mock=False,
        local_media_mock=False,
        ark_api_key="sk-test",
        ark_base_url="https://www.tokenfree.com/v1",
    )
    gw = ArkGateway(settings=settings)

    class _Resp:
        status_code = 200
        text = json.dumps(payload)

        def json(self):
            return payload

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return _Resp()

    async def _no_retry(post, **_kwargs):
        return await post()

    monkeypatch.setattr("app.services.ark.httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr("app.services.ark.post_until_not_rate_limited", _no_retry)
    monkeypatch.setattr(gw, "_resolve_ark_route", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="出图上游任务失败") as ei:
        await gw._seedream_once(
            "湖",
            None,
            project_id=1,
            shot_no=1,
            size="2k",
            model="gpt-image-2",
        )
    assert "Seedream missing url" not in str(ei.value)
    assert "resp_gag" not in str(ei.value)


def test_response_image_references_are_multimodal_inputs_when_enabled():
    body = build_tokenfree_image_body(model='seedream-5.0', prompt='Change the ball to green', ref_urls=['https://example.test/ball.png', 'https://example.test/mask.png'], style_ref_urls=['https://example.test/style.png'], structured_refs=True)
    parts = body['input'][0]['content']
    assert parts[0]['type'] == 'input_text'
    assert 'Change the ball to green' in parts[0]['text']
    assert [part['image_url'] for part in parts[1:]] == ['https://example.test/ball.png', 'https://example.test/mask.png', 'https://example.test/style.png']
    assert all(part['type'] == 'input_image' for part in parts[1:])
    assert isinstance(build_tokenfree_image_body(model='seedream-5.0', prompt='A ball', structured_refs=True)['input'], str)
