"""TokenFree / New API 视频任务：路径映射与 Seedance 请求体包装。

方舟原生是 POST /contents/generations/tasks。TokenFree 走 OpenAI Videos 兼容接口：
POST /v1/videos、GET /v1/videos/:id、GET /v1/videos/:id/content。

New API doubao 插件约定（见 QuantumNous/new-api PR #4042）：
- 文案放顶层 `prompt`（插件会清掉 content 里的 text 再追加 prompt）
- 参考图/音/视频放 **`metadata.content`**（不要包一层 `metadata.input`）
- 时长用顶层 `seconds`；也可在 metadata 里带方舟字段（ratio/resolution 等）
"""

from __future__ import annotations

from typing import Any



async def post_video_create(client: Any, method: str, url: str, *, request_call: Any = None, **kwargs: Any) -> Any:
    """MiniMax 插件明确拒绝分辨率枚举时，仅转换大小写重试一次。"""
    if request_call is None:
        from app.services.tasks.upstream import observed_request

        request_call = observed_request
    response = await request_call(client, method, url, **kwargs)
    body = kwargs.get("json")
    if response.status_code != 400 or not isinstance(body, dict):
        return response
    if str(body.get("model") or "").lower() != "minimax-h3":
        return response
    try:
        error = response.json()
    except ValueError:
        return response
    if not isinstance(error, dict) or error.get("code") != "plugin_usage_invalid" or extract_video_task_id(error):
        return response
    metadata = body.get("metadata")
    resolution = metadata.get("resolution") if isinstance(metadata, dict) else None
    alternatives = {"480p": "480P", "768p": "768P", "480P": "480p", "768P": "768p"}
    if resolution not in alternatives:
        return response
    retry_body = {**body, "metadata": {**metadata, "resolution": alternatives[resolution]}}
    return await request_call(client, method, url, **{**kwargs, "json": retry_body})

# 方舟原生异步视频任务前缀
ARK_VIDEO_TASK_PREFIX = "/contents/generations/tasks"
# TokenFree OpenAI Videos 兼容前缀（相对 /v1）
NEWAPI_VIDEO_TASK_PREFIX = "/videos"
# 任务成功态（方舟 + New API / OpenAI Videos）
VIDEO_SUCCESS_STATUSES = {"succeeded", "success", "completed", "complete"}
# 任务失败态
VIDEO_FAILED_STATUSES = {"failed", "cancelled", "canceled", "expired", "failure"}


def uses_tokenfree_video(*, base_url: str = "", channel_id: str = "") -> bool:
    """视频只走 TokenFree / New API，不再按主机切方舟原生。"""
    del base_url, channel_id
    return True


def remap_video_path(path: str, *, base_url: str = "", channel_id: str = "") -> str:
    """TokenFree 上将方舟任务路径改写成 /videos 与 /videos/{id}。"""
    normalized = path if str(path).startswith("/") else f"/{path}"
    if not uses_tokenfree_video(base_url=base_url, channel_id=channel_id):
        return normalized
    if normalized == ARK_VIDEO_TASK_PREFIX or normalized.startswith(ARK_VIDEO_TASK_PREFIX + "/"):
        return NEWAPI_VIDEO_TASK_PREFIX + normalized[len(ARK_VIDEO_TASK_PREFIX) :]
    return normalized


def tokenfree_video_content_url(base_url: str, task_id: str) -> str:
    """拼接 GET /v1/videos/{task_id}/content 下载地址。"""
    base = (base_url or "").rstrip("/")
    tid = (task_id or "").strip().lstrip("/")
    return f"{base}/videos/{tid}/content"


def is_tokenfree_content_url(url: str) -> bool:
    """是否为 TokenFree /videos/:id/content 拉取地址（下载需带 Bearer）。"""
    raw = (url or "").strip().lower()
    if "/videos/" not in raw:
        return False
    return raw.rstrip("/").endswith("/content")


async def resolve_tokenfree_media_download_url(
    url: str,
    *,
    api_key: str,
    timeout: float = 30.0,
) -> str:
    """探测 TokenFree content：若 302 到 TOS/CDN 直链则改走直链（避免经网关拉大文件中断）。"""
    import httpx

    raw = (url or "").strip()
    if not raw or not is_tokenfree_content_url(raw):
        return raw
    key = (api_key or "").strip()
    if not key:
        return raw
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=min(20.0, float(timeout)), read=float(timeout), write=30.0, pool=20.0),
            follow_redirects=False,
        ) as client:
            async with client.stream("GET", raw, headers=headers) as resp:
                loc = (resp.headers.get("location") or "").strip()
                if resp.status_code in {301, 302, 303, 307, 308} and loc.startswith(("http://", "https://")):
                    return loc
    except Exception:  # noqa: BLE001
        return raw
    return raw


def _media_url_from_item(item: dict[str, Any], key: str) -> str | None:
    """从 content 项取出 image_url / audio_url 的公网地址。"""
    raw = item.get(key)
    url = raw.get("url") if isinstance(raw, dict) else None
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def wrap_seedance_payload_for_newapi(payload: dict[str, Any]) -> dict[str, Any]:
    """把方舟 Seedance body 转成 TokenFree POST /v1/videos 请求体。

    正确形状（与 New API doubao 插件一致）：
    `{model, prompt, seconds, metadata:{content:[图/音…], ratio, resolution, …}}`
    禁止再包 `metadata.input`——插件会把嵌套 input 原样丢进上游，顶层 content 只剩 prompt 文本。
    """
    from app.services.media_model_presets import resolve_preset_alias
    from app.services.tokenfree_pricing import canonicalize_channel_model_id

    src = dict(payload)
    # 预设别名（如 2-5→2.5、mini→2.0）后再规范化目录 id
    if src.get("model"):
        aliased = resolve_preset_alias(str(src["model"])) or str(src["model"])
        src["model"] = canonicalize_channel_model_id(aliased)
    content = src.get("content")
    texts: list[str] = []
    media: list[dict[str, Any]] = []
    seen_images: set[tuple[str, str]] = set()
    if isinstance(content, list):
        # Unlabelled legacy single-image calls mean image-to-video. A set
        # of images without roles represents references, never several first frames.
        image_count = sum(isinstance(item, dict) and item.get("type") == "image_url" for item in content)
        for item in content:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "text":
                if piece := str(item.get("text") or "").strip():
                    texts.append(piece)
            elif kind == "image_url":
                url = _media_url_from_item(item, "image_url")
                role = str(item.get("role") or ("first_frame" if image_count == 1 else "reference_image"))
                if url and (role, url) not in seen_images:
                    seen_images.add((role, url))
                    media.append({**item, "role": role})
            elif kind in {"video_url", "audio_url"}:
                media.append(item)
    prompt = "\n".join(texts) or str(src.get("prompt") or "").strip() or "."
    duration = src.get("duration")
    duration_text = ""
    if duration is not None:
        try:
            duration_text = str(int(duration))
        except (TypeError, ValueError):
            duration_text = str(duration).strip()
    ratio = str(src.get("ratio") or "").strip()
    # The gateway creates a first_frame for top-level image. Send all roles
    # exclusively via metadata.content so the gateway cannot add it twice.
    metadata: dict[str, Any] = {"content": media} if media else {}
    if duration_text:
        try:
            metadata["duration"] = int(duration_text)
        except (TypeError, ValueError):
            metadata["duration"] = duration_text
    if ratio and ratio.lower() != "adaptive":
        # 方舟字段名是 ratio，不是 aspect_ratio
        metadata["ratio"] = ratio
    resolution = str(src.get("resolution") or "").strip()
    if resolution:
        metadata["resolution"] = resolution
    if "generate_audio" in src:
        metadata["generate_audio"] = bool(src.get("generate_audio"))
    if "watermark" in src:
        metadata["watermark"] = bool(src.get("watermark"))
    if "return_last_frame" in src:
        metadata["return_last_frame"] = bool(src.get("return_last_frame"))

    out: dict[str, Any] = {
        "model": src.get("model"),
        "prompt": prompt,
        "metadata": metadata,
    }
    if duration_text:
        out["seconds"] = duration_text
    return out


def prepare_video_create_body(
    body: dict[str, Any],
    *,
    base_url: str = "",
    channel_id: str = "",
) -> dict[str, Any]:
    """一律包装成 TokenFree POST /v1/videos 请求体。"""
    del base_url, channel_id
    return wrap_seedance_payload_for_newapi(body)


def unwrap_video_task_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    """摊平 New API `{data: {...}}` 包装，便于取 status / url / task_id。"""
    if not isinstance(data, dict):
        return {}
    inner = data.get("data")
    if isinstance(inner, dict) and any(
        key in inner for key in ("status", "url", "content", "task_id", "id", "video_url")
    ):
        merged = dict(data)
        merged.update(inner)
        return merged
    return data


def _scalar_task_id(value: Any) -> str | None:
    """把标量任务 ID 收成非空字符串；忽略明显不是 ID 的状态词。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int)) and str(value).strip():
        text = str(value).strip()
        if text.lower() in {"success", "ok", "true", "none", "null", "0"}:
            return None
        return text
    return None


def extract_video_task_id(data: dict[str, Any] | None) -> str | None:
    """从创建/查询响应取出轮询用任务 ID。

    New API 可能同时给 `id`（视频对象）和 `task_id`（查询用）；优先 task_id。
    部分网关把 ID 放在字符串 `data` 里。
    """
    if not isinstance(data, dict):
        return None
    payload = unwrap_video_task_payload(data)
    for key in ("task_id", "taskId"):
        found = _scalar_task_id(payload.get(key))
        if found:
            return found
    found = _scalar_task_id(data.get("data"))
    if found:
        return found
    return _scalar_task_id(payload.get("id"))


def format_video_task_error(err: Any) -> str:
    """把上游 error 对象收成可读短句。"""
    if isinstance(err, dict):
        for key in ("message", "msg", "error"):
            value = err.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = format_video_task_error(value)
                if nested:
                    return nested
        return "视频生成失败"
    text = str(err or "").strip()
    return text or "视频生成失败"


def extract_video_result_url(data: dict[str, Any]) -> str | None:
    """从任务成功响应中取视频 URL（New API `url` 或方舟 `content.video_url`）。"""
    for key in ("url", "video_url"):
        value = data.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://", "/")):
            return value.strip()
    content = data.get("content")
    if isinstance(content, dict):
        for key in ("video_url", "url"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def normalize_video_task_status(status: str) -> str:
    """把上游状态归一成 running/succeeded/failed。"""
    raw = (status or "").strip().lower()
    if raw in VIDEO_SUCCESS_STATUSES:
        return "succeeded"
    if raw in VIDEO_FAILED_STATUSES:
        return "failed"
    return "running"
