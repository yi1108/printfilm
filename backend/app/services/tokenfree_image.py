"""TokenFree / New API 生图：Seedream 与 GPT Image 2 走 POST /v1/responses，不是方舟 /images/generations。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.tokenfree_video import uses_tokenfree_video

logger = logging.getLogger(__name__)

# 全进程只留一个观察位，避免 New API「Too many active task observations」
_image_slot: asyncio.Semaphore | None = None
# 429 后等待秒数（槽位不释放，避免其它镜继续撞限）
TOKENFREE_IMAGE_RETRY_DELAYS = (3.0, 6.0, 12.0, 20.0)

_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def uses_tokenfree_image(*, base_url: str = "", channel_id: str = "") -> bool:
    """与视频相同：TokenFree 主机或 tokenfree 渠道。"""
    return uses_tokenfree_video(base_url=base_url, channel_id=channel_id)


def is_seedream_family(model: str) -> bool:
    """模型名是否属于 Seedream 族（计费/尺寸钳制用）。"""
    mid = (model or "").strip().lower()
    return "seedream" in mid


def gpt_image_caps_at_2k(model: str) -> bool:
    """GPT Image 2 仅 1K/2K；2.5 支持到 4K，不降档。"""
    mid = (model or "").strip().lower()
    if "gpt-image" not in mid:
        return False
    return "2.5" not in mid and "2-5" not in mid


def is_gpt_image_25(model: str) -> bool:
    """GPT Image 2.5：TokenFree 只在 image-generation 渠道放行，不走 /responses。"""
    mid = (model or "").strip().lower()
    return "gpt-image-2.5" in mid or "gpt-image-2-5" in mid


def gpt_image_resolution_tier(size: str) -> str:
    """把 1K/2K/4K 或像素面积收成计费档（价目表达式读 resolution）。"""
    raw = (size or "").strip().upper().replace(" ", "")
    if raw in {"1K", "2K", "4K"}:
        return raw
    if "X" not in raw:
        return "2K"
    left, _, right = raw.partition("X")
    if not left.isdigit() or not right.isdigit():
        return "2K"
    width, height = int(left), int(right)
    longest = max(width, height)
    if longest >= 3000:
        return "4K"
    if longest >= 1600:
        return "2K"
    return "1K"


def build_tokenfree_openai_image_body(
    *,
    model: str,
    prompt: str,
    size: str = "",
    aspect_ratio: str = "",
    ref_urls: list[str] | None = None,
    style_ref_urls: list[str] | None = None,
) -> dict[str, Any]:
    """GPT Image 2.5：POST /images/generations（openai 渠道），并带上 resolution 供计费。"""
    narrative = build_tokenfree_image_body(
        model=model,
        prompt=prompt,
        size=size,
        aspect_ratio=aspect_ratio,
        ref_urls=ref_urls,
        style_ref_urls=style_ref_urls,
    )
    pixel = (size or "").strip()
    if not _is_pixel_size(pixel):
        pixel = "1024x1024"
    return {
        "model": narrative["model"],
        "prompt": narrative["input"],
        "size": pixel,
        "n": 1,
        "resolution": gpt_image_resolution_tier(size),
        "response_format": "url",
    }


def tokenfree_working_image_model(model: str) -> str:
    """原样返回渠道/路由配置的上游模型名，不做改写。"""
    return (model or "").strip()


def _aspect_ratio_orientation(ratio: str) -> str:
    """根据 w:h 返回横/竖/方构图标签；无法解析则空串。"""
    try:
        left, _, right = (ratio or "").strip().partition(":")
        w, h = float(left), float(right)
    except ValueError:
        return ""
    if w <= 0 or h <= 0:
        return ""
    if w > h:
        return "横构图"
    if h > w:
        return "竖构图"
    return "方形构图"


def _is_pixel_size(size: str) -> bool:
    """是否为 WxH 像素串（非 1K/2K 档位）。"""
    raw = (size or "").strip().lower()
    if not raw or raw in {"1k", "2k", "3k", "4k"}:
        return False
    if "x" not in raw:
        return False
    left, _, right = raw.partition("x")
    return left.isdigit() and right.isdigit()


def build_tokenfree_image_body(
    *,
    model: str,
    prompt: str,
    size: str = "",
    aspect_ratio: str = "",
    ref_urls: list[str] | None = None,
    style_ref_urls: list[str] | None = None,
    structured_refs: bool = False,
) -> dict[str, Any]:
    """线上成功体只要 model + 自然语言 input，不要 size: 这种协议字段。

    画幅必须单独写入自然语言（GPT Image /responses 无结构化 size 字段），
    否则角色设定板等竖向提示词会盖过 UI 所选比例。
    """
    text = (prompt or "").strip() or "画面清晰，主体稳定"
    ratio = (aspect_ratio or "").strip()
    if ratio and ratio.lower() != "auto":
        orient = _aspect_ratio_orientation(ratio)
        frame = f"输出画幅必须为{ratio}"
        if orient:
            frame += f"（{orient}，整张画布严格按该比例，禁止改成其他比例）"
        else:
            frame += "（整张画布严格按该比例，禁止改成其他比例）"
        text = f"{text}。{frame}"
    size_s = (size or "").strip()
    if size_s:
        if _is_pixel_size(size_s):
            text = f"{text}。目标像素约{size_s}"
        else:
            text = f"{text}。输出清晰度{size_s}"
    refs = [u.strip() for u in (ref_urls or []) if (u or "").strip()]
    style_refs = [u.strip() for u in (style_ref_urls or []) if (u or "").strip()]
    if style_refs:
        text = f"{text}。画风参考图（只借色调、笔触、光影，禁止抄主体与构图）：{' '.join(style_refs)}"
    if refs:
        text = f"{text}。构图与主体参考：{' '.join(refs)}"
    mid = tokenfree_working_image_model(model)
    if structured_refs and (refs or style_refs):
        # URLs in plain text are not image inputs. Responses-compatible channels
        # must receive input_image blocks to actually inspect the references.
        content = [{'type': 'input_text', 'text': text}]
        content.extend({'type': 'input_image', 'image_url': url} for url in [*refs, *style_refs])
        return {'model': mid, 'input': [{'role': 'user', 'content': content}]}
    return {"model": mid, "input": text}


def extract_tokenfree_image_url(data: dict[str, Any]) -> str | None:
    """从 /v1/responses 或兼容包里抽出图片 URL。"""
    if not isinstance(data, dict):
        return None
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            url = block.get("url")
            image_url = block.get("image_url")
            if not url and isinstance(image_url, dict):
                url = image_url.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url.strip()
            text = str(block.get("text") or "")
            img = _IMG_SRC_RE.search(text)
            if img:
                return img.group(1).strip()
            # _URL_RE 无捕获组，必须用 group(0)
            bare = _URL_RE.search(text)
            if bare:
                return bare.group(0).strip()
    if data.get("data"):
        first = data["data"][0]
        if isinstance(first, dict):
            raw = first.get("url")
            if isinstance(raw, str) and raw.startswith("http"):
                return raw.strip()
    return None


def _parse_json_object(body: str) -> dict[str, Any] | None:
    """解析 JSON 对象；失败返回 None。"""
    text = (body or "").strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def is_tokenfree_image_task_failed(data: dict[str, Any]) -> bool:
    """/v1/responses HTTP 200 也可能 status=failed（无 output）。"""
    if not isinstance(data, dict):
        return False
    status = str(data.get("status") or "").lower()
    if status in {"failed", "cancelled"}:
        return True
    meta = data.get("metadata")
    if isinstance(meta, dict) and str(meta.get("task_status") or "").lower() in {"failed", "cancelled"}:
        return True
    err = data.get("error")
    if isinstance(err, dict) and (err.get("code") or err.get("message")):
        output = data.get("output")
        if not output:
            return True
    return False


def tokenfree_image_failed_task_message(data: dict[str, Any]) -> str:
    """/responses status=failed 时给用户的中文短句，不含 JSON / resp_id。"""
    err = data.get("error") if isinstance(data.get("error"), dict) else {}
    body = json.dumps(data, ensure_ascii=False)
    if is_tokenfree_input_text_sensitive(status_code=200, body=body):
        return "生图文案未通过内容审核（可能含敏感或历史名人相关表述），请修改提示词后重试。"
    code = str((err or {}).get("code") or "").lower()
    msg = str((err or {}).get("message") or "")
    if code in {"server_error", "internal_error"} or "task failed" in msg.lower():
        return "出图上游任务失败，请稍后再点「生成画面」"
    snippet = (msg or code or "failed")[:200]
    return f"出图失败：{snippet}"


def raise_tokenfree_image_if_failed(data: dict[str, Any]) -> None:
    """任务失败时抛中文短句，不把 resp_id / JSON 丢给用户。"""
    if not is_tokenfree_image_task_failed(data):
        return
    err = data.get("error") if isinstance(data.get("error"), dict) else {}
    logger.warning(
        "TokenFree 生图任务失败 model=%s code=%s message=%s",
        data.get("model"),
        (err or {}).get("code"),
        str((err or {}).get("message") or "")[:160],
    )
    raise RuntimeError(tokenfree_image_failed_task_message(data))


def is_tokenfree_rate_limit(*, status_code: int = 0, body: str = "") -> bool:
    """429，或明确的观察位/限流错误体；2xx 成功体里的 rate_limit 字段不算。"""
    if int(status_code or 0) == 429:
        return True
    text = body or ""
    if "too many active task observations" in text.lower():
        return True
    try:
        payload = json.loads(text) if text.strip().startswith("{") else None
    except json.JSONDecodeError:
        payload = None
    err = payload.get("error") if isinstance(payload, dict) else None
    code = ""
    if isinstance(err, dict):
        code = str(err.get("code") or "")
    elif isinstance(payload, dict):
        code = str(payload.get("code") or "")
    return code.lower() == "rate_limit_exceeded"


def is_tokenfree_protocol_error(*, status_code: int = 0, body: str = "") -> bool:
    """New API 任务协议失败（含 Invalid task protocol request）。"""
    text = (body or "").lower()
    if (
        "task_protocol_error" in text
        or "task protocol request failed" in text
        or "invalid task protocol" in text
    ):
        return True
    try:
        payload = json.loads(body) if (body or "").strip().startswith("{") else None
    except json.JSONDecodeError:
        payload = None
    err = payload.get("error") if isinstance(payload, dict) else None
    code = str((err or {}).get("code") or "") if isinstance(err, dict) else ""
    msg = str((err or {}).get("message") or "") if isinstance(err, dict) else ""
    if "invalid task protocol" in msg.lower():
        return True
    return int(status_code or 0) in {400, 502} and code.lower() in {
        "task_protocol_error",
        "invalid_request_error",
    } and "protocol" in (msg or text).lower()


def is_tokenfree_no_distributor(*, status_code: int = 0, body: str = "") -> bool:
    """New API 分组下没有可用 distributor（须 404/502/503 且 model_not_found + 无线路）。"""
    if int(status_code or 0) not in {404, 502, 503}:
        return False
    text = body or ""
    lowered = text.lower()
    if "model_not_found" not in lowered:
        return False
    return "distributor" in lowered or "无可用" in text


def is_tokenfree_retryable_image_error(*, status_code: int = 0, body: str = "") -> bool:
    """限流，或 HTTP 200 的上游 server_error 可退避；协议/无线路立刻失败。"""
    if is_tokenfree_rate_limit(status_code=status_code, body=body):
        return True
    if int(status_code or 0) != 200:
        return False
    payload = _parse_json_object(body)
    if not payload or not is_tokenfree_image_task_failed(payload):
        return False
    err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(err.get("code") or "").lower()
    return code in {"server_error", "internal_error"}


def tokenfree_image_channel_dead(*, status_code: int = 0, body: str = "") -> bool:
    """TokenFree 出图通道当前不可用（协议失败或无 distributor）。"""
    return is_tokenfree_protocol_error(status_code=status_code, body=body) or is_tokenfree_no_distributor(
        status_code=status_code, body=body
    )


def is_tokenfree_input_text_sensitive(*, status_code: int = 0, body: str = "") -> bool:
    """文案审核拦截；协议失败、限流、无线路不算，才能走 compact/style_only。"""
    if is_tokenfree_rate_limit(status_code=status_code, body=body):
        return False
    if tokenfree_image_channel_dead(status_code=status_code, body=body):
        return False
    text = body or ""
    if "InputTextSensitive" in text or "InputTextSensitiveContentDetected" in text:
        return True
    lowered = text.lower()
    if any(token in lowered for token in ("content_filter", "content_policy", "text sensitive", "sensitive content")):
        return True
    return "内容审核" in text or "敏感内容" in text


def tokenfree_image_user_error(*, model: str = "", status_code: int = 0, body: str = "") -> str:
    """用户可见的 TokenFree 出图失败文案；通道挂了不再误导改模型。"""
    if is_tokenfree_rate_limit(status_code=status_code, body=body):
        return "出图通道繁忙，同时进行的任务过多，请稍后再点「生成画面」"
    if is_tokenfree_protocol_error(status_code=status_code, body=body):
        if is_seedream_family(model):
            # Seedream 走 /responses 时协议失败多为该模型通道问题，勿当成全站挂死
            return (
                "当前 Seedream 出图协议失败，请稍后重试；"
                "若持续失败，可在管理端将默认图模改为 GPT Image"
            )
        return "出图通道暂时失败，请稍后再点「生成画面」"
    if is_tokenfree_no_distributor(status_code=status_code, body=body):
        who = (model or "该图像模型").strip() or "该图像模型"
        return (
            f"当前 TokenFree 分组未开通 {who}（无可用渠道）。"
            "请在 TokenFree 控制台为 default 分组配置该模型后再生成。"
        )
    payload = _parse_json_object(body)
    if payload and is_tokenfree_image_task_failed(payload):
        return tokenfree_image_failed_task_message(payload)
    snippet = (body or "")[:800]
    return f"出图失败 {status_code}: {snippet}"


def tokenfree_image_slot() -> asyncio.Semaphore:
    """全进程 TokenFree 生图互斥（默认 1 路）。"""
    global _image_slot
    if _image_slot is None:
        from app.config import get_settings

        n = max(1, int(getattr(get_settings(), "tokenfree_image_concurrency", 1) or 1))
        _image_slot = asyncio.Semaphore(n)
    return _image_slot


async def post_until_not_rate_limited(
    post: Callable[[], Awaitable[Any]],
    *,
    delays: tuple[float, ...] = TOKENFREE_IMAGE_RETRY_DELAYS,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> Any:
    """POST 遇观察位限流或 HTTP 200+server_error 则退避重试；仍失败则返回最后一次响应。"""
    last: Any = None
    for attempt in range(len(delays) + 1):
        last = await post()
        status = int(getattr(last, "status_code", 0) or 0)
        body = str(getattr(last, "text", "") or "")
        if not is_tokenfree_retryable_image_error(status_code=status, body=body):
            return last
        if attempt >= len(delays):
            break
        wait = delays[attempt]
        logger.warning("TokenFree 生图暂不可用，%.0fs 后重试（%s/%s）", wait, attempt + 1, len(delays))
        await sleep(wait)
    return last


def is_tokenfree_image_url(url: str) -> bool:
    """TokenFree 任务产物地址，下载建议带 Bearer。"""
    raw = (url or "").strip().lower()
    if "tokenfree.com" not in raw:
        return False
    return "/tasks/" in raw or "/responses/" in raw or "/artifacts/" in raw
