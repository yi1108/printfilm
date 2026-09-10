"""漫剧 Agent 文字 LLM（Kimi / OpenAI 兼容，对齐 manju agents/llm.ts）。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.llm_client import (
    DEFAULT_MAX_TOKENS,
    LlmUnavailableError,
    chat_completions,
)

logger = logging.getLogger(__name__)

# 兼容旧引用
DramaLlmUnavailableError = LlmUnavailableError

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_JSON_FENCE_TAIL_RE = re.compile(r"\s*```$")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_SMART_QUOTE_MAP = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
    }
)


def _strip_json_fences(text: str) -> str:
    # 去掉 markdown 代码围栏
    raw = (text or "").strip()
    raw = _JSON_FENCE_RE.sub("", raw)
    raw = _JSON_FENCE_TAIL_RE.sub("", raw)
    return raw.strip()


def _repair_json_text(raw: str) -> str:
    # 常见 LLM JSON 瑕疵：智能引号、尾逗号
    repaired = raw.translate(_SMART_QUOTE_MAP)
    repaired = _TRAILING_COMMA_RE.sub(r"\1", repaired)
    return repaired


def _extract_json(text: str) -> Any:
    # 从模型输出解析 JSON（去围栏、修复常见格式错误）
    raw = _strip_json_fences(text)
    candidates = [raw, _repair_json_text(raw)]

    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
    if m and m.group(1) not in candidates:
        snippet = m.group(1)
        candidates.extend([snippet, _repair_json_text(snippet)])

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error
    raise json.JSONDecodeError("empty JSON payload", text or "", 0)


def _ensure_json_word_in_prompt(system: str, user: str) -> tuple[str, str]:
    """DeepSeek 等要求 response_format=json_object 时 prompt 须含 json 字样。"""
    blob = f"{system or ''}\n{user or ''}".lower()
    if "json" in blob:
        return system, user
    suffix = "\n\n请只输出合法 JSON 对象，不要 markdown 代码围栏。"
    return (system or "").rstrip() + suffix, user


async def drama_chat_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.6,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Any:
    """Call text LLM and parse JSON from the reply."""
    system, user = _ensure_json_word_in_prompt(system, user)
    json_format = {"type": "json_object"}
    try:
        content = await chat_completions(
            system,
            user,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=300.0,
            response_format=json_format,
        )
    except RuntimeError as exc:
        # 部分兼容网关不支持 response_format，降级为普通调用
        if "response_format" not in str(exc).lower() and "json_object" not in str(exc).lower():
            raise
        logger.warning("LLM 不支持 response_format，降级普通调用: %s", exc)
        content = await chat_completions(
            system,
            user,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=300.0,
        )

    try:
        return _extract_json(content)
    except json.JSONDecodeError as first_error:
        logger.warning(
            "JSON 解析失败，重试一次 err=%s content_head=%s",
            first_error,
            (content or "")[:200],
        )
        retry_user = (
            f"{user}\n\n"
            "【重要】上次输出不是合法 JSON。请只输出一个完整、可 json.loads 的 JSON 对象，"
            "不要 markdown、不要代码围栏、字符串内不要未转义换行。"
        )
        content = await chat_completions(
            system,
            retry_user,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=300.0,
            response_format=json_format,
        )
        return _extract_json(content)


async def drama_chat_text(
    system: str,
    user: str,
    *,
    temperature: float = 0.6,
    max_tokens: int = 8192,
) -> str:
    """Call text LLM and return plain text."""
    return await chat_completions(
        system,
        user,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=180.0,
    )
