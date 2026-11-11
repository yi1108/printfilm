"""OpenAI 兼容文字模型客户端（任意兼容上游：Kimi / DeepSeek / OpenAI 等）。"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.logical_model_router import (
    resolve_logical_model,
    resolve_logical_model_id,
    resolve_upstream_model,
)
from app.services.tasks.upstream import observed_request

logger = logging.getLogger(__name__)

# DEFAULT_MAX_TOKENS 分集正文等结构化输出需要足够 completion 空间
DEFAULT_MAX_TOKENS = 32768


class LlmUnavailableError(RuntimeError):
    """文字 LLM 未配置或不可用。"""


# 解析 LLM API Key（对齐 manju resolveOpenaiApiKey）
def resolve_llm_api_key() -> str:
    key = (get_settings().openai_api_key or "").strip()
    if not key:
        raise LlmUnavailableError(
            "未配置 OPENAI_API_KEY，无法调用文字模型。"
            "请在管理后台「系统设置 → 模型」填写 TokenFree API Key 并选择文本模型。"
        )
    return key


# 解析 OpenAI 兼容 Base URL
def resolve_llm_base_url() -> str:
    base = (get_settings().openai_base_url or "").strip().rstrip("/")
    if base:
        return base
    return "https://api.openai.com/v1"


# kimi / deepseek-v4 默认 thinking 会占满 token、content 常为空；结构化产出统一关闭
def _llm_extra_body(model: str) -> dict[str, Any]:
    mid = (model or "").strip().lower()
    if mid.startswith("kimi") or mid.startswith("deepseek"):
        return {"thinking": {"type": "disabled"}}
    return {}


# 从 chat/completions 响应提取正文
def _message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if content:
        return str(content)
    # 部分兼容网关把结果放在 reasoning_content
    reasoning = message.get("reasoning_content")
    return str(reasoning or "")


def prepare_chat_request(
    system: str,
    user: str,
    *,
    temperature: float = 0.6,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    response_format: dict[str, Any] | None = None,
    model_id: str | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Resolve the same managed model and request policy for batch and streaming calls."""
    settings = get_settings()
    # Apply managed model switches before falling back to environment credentials.
    try:
        resolve_upstream_model("text", model_id)
    except ValueError as exc:
        raise LlmUnavailableError(str(exc)) from exc
    logical_id = resolve_logical_model_id("text", model_id)
    route = resolve_logical_model("text", logical_id)
    if route:
        api_key = route.api_key
        model = (route.upstream_model or "").strip()
        base = route.base_url.rstrip("/") or resolve_llm_base_url()
    else:
        api_key = resolve_llm_api_key()
        model = (resolve_upstream_model("text", model_id) if model_id else settings.model_llm or "").strip()
        base = resolve_llm_base_url()
    if not model:
        raise LlmUnavailableError(
            "未解析到可用文字模型。请在管理后台填写 TokenFree API Key，拉取并选择文本模型。"
        )
    # kimi 系列仅允许 temperature=0.6，其它值会 400
    effective_temperature = 0.6 if model.lower().startswith("kimi") else temperature

    payload: dict[str, Any] = {
        "model": model,
        "temperature": effective_temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    extra = _llm_extra_body(model)
    if extra:
        payload.update(extra)
    if response_format:
        payload["response_format"] = response_format

    return f"{base}/chat/completions", {
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
    }, payload


# 调用 OpenAI 兼容 chat/completions
async def chat_completions(
    system: str,
    user: str,
    *,
    temperature: float = 0.6,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = 300.0,
    response_format: dict[str, Any] | None = None,
    model_id: str | None = None,
    strict_output: bool = False,
) -> str:
    url, headers, payload = prepare_chat_request(
        system, user, temperature=temperature, max_tokens=max_tokens,
        response_format=response_format, model_id=model_id,
    )
    model, base = payload['model'], url.removesuffix('/chat/completions')

    logger.info(
        "调用文字 LLM model=%s base=%s user_len=%s max_tokens=%s",
        model,
        base,
        len(user or ""),
        max_tokens,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await observed_request(client, "POST",
            url,
            headers=headers,
            json=payload,
        )
        if res.status_code >= 400:
            raise RuntimeError(f"LLM error {res.status_code}: {res.text[:800]}")
        body = (res.text or "").strip()
        if not body:
            raise RuntimeError(f"LLM 返回空响应体 (HTTP {res.status_code})")
        lowered = body[:256].lower()
        if lowered.startswith("<!doctype") or lowered.startswith("<html"):
            raise RuntimeError(
                f"LLM 渠道 Base URL 配置错误（返回了网页 HTML 而非 API JSON）。"
                f"当前 base={base}，请检查管理后台「模型渠道」的 Base URL 是否为 OpenAI 兼容 API 地址"
                f"（如 https://api.deepseek.com 或 https://api.moonshot.cn/v1），而非网站首页。"
            )
        try:
            data = res.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM 响应不是合法 JSON: {body[:200]}") from exc
    if strict_output:
        choice = (data.get('choices') or [{}])[0]
        if choice.get('finish_reason') in {'length', 'content_filter', 'tool_calls'}:
            raise RuntimeError('模型未完成正文，请调整要求后重试')
        if not (choice.get('message') or {}).get('content'):
            raise RuntimeError('模型没有返回正文，请重试')
    content = _message_content(data)
    logger.info("文字 LLM 返回 content_len=%s", len(content))
    return content
