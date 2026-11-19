"""TokenFree / New API 视频路径与 Seedance 请求体包装。"""

from __future__ import annotations

from app.services.ark import ArkGateway, _build_task_result_from_payload
from app.services.tokenfree_gateway import TOKENFREE_BASE_URL, TOKENFREE_CHANNEL_ID
from app.services.tokenfree_video import (
    extract_video_task_id,
    prepare_video_create_body,
    remap_video_path,
    uses_tokenfree_video,
    wrap_seedance_payload_for_newapi,
)


def test_remap_video_path_on_tokenfree():
    create = remap_video_path(
        "/contents/generations/tasks",
        base_url=TOKENFREE_BASE_URL,
        channel_id=TOKENFREE_CHANNEL_ID,
    )
    poll = remap_video_path(
        "/contents/generations/tasks/task-1",
        base_url=TOKENFREE_BASE_URL,
    )
    assert create == "/videos"
    assert poll == "/videos/task-1"


def test_remap_video_path_ignores_volces_host():
    """方舟主机不再保留原生任务路径。"""
    path = remap_video_path(
        "/contents/generations/tasks",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )
    assert path == "/videos"
    assert uses_tokenfree_video(base_url="https://ark.cn-beijing.volces.com/api/v3") is True


def test_wrap_seedance_payload_canonicalizes_mini_hyphen_id():
    """Mini 上游未开通：旧连字符/mini 规范到 seedance-2.0。"""
    wrapped = wrap_seedance_payload_for_newapi(
        {
            "model": "seedance-2-0-mini",
            "content": [{"type": "text", "text": "x"}],
            "duration": 4,
        }
    )
    assert wrapped["model"] == "seedance-2.0"


def test_wrap_seedance_payload_uses_metadata_content_not_input():
    """首帧：media 在 metadata.content，禁止再包 metadata.input。"""
    payload = {
        "model": "seedance-2-5",
        "content": [
            {"type": "text", "text": "镜头推进"},
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/a.jpg"},
                "role": "first_frame",
            },
        ],
        "duration": 5,
        "resolution": "720p",
        "ratio": "16:9",
        "watermark": False,
        "generate_audio": True,
        "return_last_frame": True,
    }
    wrapped = wrap_seedance_payload_for_newapi(payload)
    assert wrapped["model"] == "seedance-2.5"
    assert wrapped["prompt"] == "镜头推进"
    assert "image" not in wrapped, "top-level image would create a second first frame"
    assert wrapped["seconds"] == "5"
    assert "input" not in wrapped["metadata"]
    meta = wrapped["metadata"]
    assert meta["duration"] == 5
    assert "ratio" not in meta
    assert meta["generate_audio"] is True
    assert meta["content"] == [
        {
            "type": "image_url",
            "image_url": {"url": "https://cdn.example.com/a.jpg"},
            "role": "first_frame",
        }
    ]
    assert "reference_image_urls" not in meta
    assert "content" not in wrapped


def test_wrap_seedance_payload_keeps_all_reference_images():
    """多参考须落在 metadata.content（TF 插件才会并进方舟顶层 content）。"""
    payload = {
        "model": "seedance-2-5",
        "content": [
            {"type": "text", "text": "光光飞过"},
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/guang.png"},
                "role": "reference_image",
            },
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/mimi.png"},
                "role": "reference_image",
            },
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/last.jpg"},
                "role": "reference_image",
            },
            {
                "type": "audio_url",
                "audio_url": {"url": "https://cdn.example.com/voice.mp3"},
                "role": "reference_audio",
            },
        ],
        "duration": 22,
        "resolution": "480p",
        "ratio": "16:9",
        "watermark": False,
        "generate_audio": True,
        "return_last_frame": True,
    }
    wrapped = wrap_seedance_payload_for_newapi(payload)
    meta = wrapped["metadata"]
    refs = [
        "https://cdn.example.com/guang.png",
        "https://cdn.example.com/mimi.png",
        "https://cdn.example.com/last.jpg",
    ]
    assert "image" not in wrapped
    assert "input" not in meta
    assert meta["ratio"] == "16:9"
    content_image_urls = [
        item["image_url"]["url"]
        for item in meta.get("content") or []
        if isinstance(item, dict) and item.get("type") == "image_url"
    ]
    assert content_image_urls == refs
    assert any(
        isinstance(item, dict) and item.get("type") == "audio_url"
        for item in meta.get("content") or []
    )
    # 文案只在 prompt，不进 metadata.content（插件会用 prompt 重写 text）
    assert all(
        not (isinstance(item, dict) and item.get("type") == "text")
        for item in meta.get("content") or []
    )
    assert wrapped["prompt"] == "光光飞过"


def test_wrap_seedance_payload_single_reference_image_keeps_ratio_mode():
    """有画幅的单张 i2v 也是 reference_image，不能退化成 first_frame。"""
    payload = {
        "model": "seedance-2-5",
        "content": [
            {"type": "text", "text": "镜头推进"},
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/a.jpg"},
                "role": "reference_image",
            },
        ],
        "duration": 5,
        "ratio": "9:16",
        "resolution": "480p",
    }
    wrapped = wrap_seedance_payload_for_newapi(payload)
    meta = wrapped["metadata"]
    assert "image" not in wrapped
    assert "input" not in meta
    assert meta["ratio"] == "9:16"
    assert meta["content"][0]["role"] == "reference_image"
    assert meta["content"][0]["image_url"]["url"] == "https://cdn.example.com/a.jpg"


def test_wrap_seedance_payload_from_generate_body_includes_continuity():
    """真实组装体：角色图 + 上一镜尾帧都要进 metadata.content。"""
    from app.services.drama.build_seedance_generate_body import build_seedance_generate_body

    body = build_seedance_generate_body(
        {
            "content": "@duration:6\n禹：水患未平。",
            "aspect_ratio": "16:9",
            "resolution": "480p",
            "duration_fallback": 8,
            "continuity_first_frame_url": "https://cdn.example.com/prev_last.jpg",
            "reference": [
                {
                    "id": 1,
                    "type": "character",
                    "name": "禹",
                    "cover": "https://cdn.example.com/yu.jpg",
                    "url": "https://cdn.example.com/yu.jpg",
                    "params": {},
                }
            ],
        }
    )
    wrapped = wrap_seedance_payload_for_newapi(body)
    urls = [
        item["image_url"]["url"]
        for item in wrapped["metadata"]["content"]
        if item.get("type") == "image_url"
    ]
    assert urls[0] == "https://cdn.example.com/yu.jpg"
    assert urls[-1] == "https://cdn.example.com/prev_last.jpg"
    assert "image" not in wrapped
    assert "input" not in wrapped["metadata"]


def test_wrap_seedance_payload_preserves_validated_reference_images():
    """数量由模型策略提前校验；传输层不能静默截断已通过校验的素材。"""
    content = [{"type": "text", "text": "群戏"}]
    for i in range(12):
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"https://cdn.example.com/{i}.png"},
                "role": "reference_image",
            }
        )
    wrapped = wrap_seedance_payload_for_newapi(
        {"model": "seedance-2-5", "content": content, "duration": 8}
    )
    urls = [
        item["image_url"]["url"]
        for item in wrapped["metadata"]["content"]
        if item.get("type") == "image_url"
    ]
    assert len(urls) == 12
    assert "input" not in wrapped["metadata"]


def test_prepare_video_create_body_always_wraps():
    body = {"model": "seedance-2-5", "content": [{"type": "text", "text": "hi"}], "duration": 5}
    wrapped = prepare_video_create_body(
        body,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
    )
    assert wrapped["prompt"] == "hi"
    assert wrapped["metadata"]["duration"] == 5
    assert "input" not in wrapped["metadata"]


def test_extract_video_task_id_from_newapi_and_wrapped_data():
    assert extract_video_task_id({"task_id": "abc"}) == "abc"
    assert extract_video_task_id({"id": "ark-1"}) == "ark-1"
    assert extract_video_task_id({"data": {"task_id": "nested"}}) == "nested"
    assert extract_video_task_id({"id": "video_123", "task_id": "abcd"}) == "abcd"
    assert extract_video_task_id({"id": "outer", "data": {"task_id": "nested", "status": "queued"}}) == "nested"
    assert extract_video_task_id({"code": "success", "data": "cgt-xxx"}) == "cgt-xxx"


def test_build_task_result_from_newapi_completed_url():
    result = _build_task_result_from_payload(
        {
            "task_id": "abcd",
            "status": "completed",
            "url": "https://example.com/video.mp4",
        }
    )
    assert result.status == "succeeded"
    assert result.url == "https://example.com/video.mp4"


def test_build_task_result_from_newapi_nested_data():
    result = _build_task_result_from_payload(
        {
            "data": {
                "status": "succeeded",
                "content": {"video_url": "https://example.com/ark.mp4"},
            }
        }
    )
    assert result.status == "succeeded"
    assert result.url == "https://example.com/ark.mp4"


def test_build_task_result_parses_usage_tokens_and_quota():
    """成功响应里的 usage.tokens / quota 须进入 TaskResult，供对齐 TokenFree 扣费。"""
    result = _build_task_result_from_payload(
        {
            "status": "succeeded",
            "url": "https://example.com/v.mp4",
            "usage": {"completion_tokens": 245025, "total_tokens": 245025},
            "quota": 1938383,
        }
    )
    assert result.status == "succeeded"
    assert result.total_tokens == 245025
    assert result.completion_tokens == 245025
    assert isinstance(result.raw_usage, dict)
    assert result.raw_usage.get("quota") == 1938383
    assert int(result.upstream_cost_fen or 0) > 0


def test_ark_client_tokenfree_video_url():
    from app.config import get_settings

    settings = get_settings().model_copy(update={"ark_base_url": TOKENFREE_BASE_URL})
    client = ArkGateway(settings=settings)
    assert client._url("/contents/generations/tasks") == f"{TOKENFREE_BASE_URL}/videos"
    assert client._url("/contents/generations/tasks/t1") == f"{TOKENFREE_BASE_URL}/videos/t1"
    wrapped = client._video_json(
        {
            "model": "seedance-2-5",
            "content": [{"type": "text", "text": "hi"}],
            "duration": 5,
            "ratio": "16:9",
        }
    )
    assert wrapped["prompt"] == "hi"
    assert wrapped["metadata"]["duration"] == 5
    assert wrapped["metadata"]["ratio"] == "16:9"
    assert "input" not in wrapped["metadata"]
    finalized = client._finalize_video_result(
        _build_task_result_from_payload({"status": "completed"}),
        "task-9",
    )
    assert finalized.status == "succeeded"
    assert finalized.url == f"{TOKENFREE_BASE_URL}/videos/task-9/content"


async def test_resolve_tokenfree_media_download_url_follows_tos_redirect(monkeypatch):
    """content 302 到火山 TOS 时改走直链。"""
    import httpx
    from app.services.tokenfree_video import resolve_tokenfree_media_download_url

    content = f"{TOKENFREE_BASE_URL}/videos/task-x/content"
    direct = "https://ark-acg-cn-beijing.tos-cn-beijing.volces.com/x.mp4?sig=1"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(content)
        return httpx.Response(302, headers={"location": direct})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    got = await resolve_tokenfree_media_download_url(content, api_key="sk-test")
    assert got == direct


async def test_resolve_tokenfree_media_download_url_keeps_content_on_200(monkeypatch):
    """content 直接 200 出片时仍用原地址。"""
    import httpx
    from app.services.tokenfree_video import resolve_tokenfree_media_download_url

    content = f"{TOKENFREE_BASE_URL}/videos/task-y/content"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "video/mp4"}, content=b"abc")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    got = await resolve_tokenfree_media_download_url(content, api_key="sk-test")
    assert got == content


def test_same_image_can_fill_distinct_first_and_last_slots():
    content = [{"type": "image_url", "image_url": {"url": "https://cdn.example.com/loop.jpg"}, "role": role}
               for role in ("first_frame", "last_frame")]
    request = wrap_seedance_payload_for_newapi({"content": content, "ratio": "16:9"})
    assert "image" not in request
    assert "ratio" not in request["metadata"]
    assert request["metadata"]["content"] == content
