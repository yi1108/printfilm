"""上游请求留痕的纯脱敏器：保留业务正文，移除凭据并摘要化二进制媒体。"""

from __future__ import annotations

import re
from itertools import islice
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.schemas_tools import MAX_GENERATION_PROMPT_CHARS

_REDACTED = "[REDACTED]"
_MAX_STRING = 12_000
_MAX_ITEMS = 80
_MAX_DEPTH = 8
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_DATA_URI_RE = re.compile(r"data:([^;,\s]+)(?:;[^,]*)?;base64,([A-Za-z0-9+/=\r\n]+)", re.I)
_DATA_URI_HEADER_RE = re.compile(r"^data:([^;,\s]+)(?:;[^,]*)?;base64,", re.I)
_SECRET_KEYS = frozenset({
    "authorization", "proxyauthorization", "cookie", "setcookie", "apikey", "key",
    "token", "accesstoken", "refreshtoken", "securitytoken", "password", "passwd",
    "secret", "clientsecret", "credential", "credentials", "signature", "sign",
    "ossaccesskeyid", "accesskey", "accesskeyid", "secretaccesskey",
})


def _secret_key(key: str) -> bool:
    """统一大小写与分隔符，识别凭据字段及云存储签名参数。"""
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in _SECRET_KEYS or normalized.endswith((
        "apikey", "token", "signature", "credential", "secret", "password", "authorization",
    ))


def _safe_url(value: str) -> str:
    """脱敏 URL 用户信息、敏感查询参数和含凭据的片段，保留非敏感业务参数。"""
    try:
        parts = urlsplit(value)
        netloc = parts.netloc.rsplit("@", 1)[-1]
        if "@" in parts.netloc:
            netloc = f"{_REDACTED}@{netloc}"
        query = urlencode([
            (key, _REDACTED if _secret_key(key) else _safe_text(val))
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
        ])
        fragment = _REDACTED if any(_secret_key(key) for key, _ in parse_qsl(parts.fragment)) else parts.fragment
        return urlunsplit((parts.scheme, netloc, parts.path, query, fragment))
    except ValueError:
        return "[INVALID URL]"


def _safe_text(value: str, max_length: int = _MAX_STRING) -> str:
    """清理错误等自由文本中的 URL、Bearer 凭据和键值形式的秘密。"""
    text = _URL_RE.sub(lambda match: _safe_url(match[0]), value)
    text = re.sub(r"\bBearer\s+[^\s,;\"']+", f"Bearer {_REDACTED}", text, flags=re.I)
    text = re.sub(
        r"\b(api[-_\s]*key|authorization|access[-_]?token|password|client[-_]?secret|token|signature|cookie|set-cookie)[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s&;,\"']+)",
        lambda match: f"{match[1]}={_REDACTED}", text, flags=re.I,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", _REDACTED, text)
    text = _DATA_URI_RE.sub(lambda match: f"[data:{match[1]};base64 length={len(match[2])}]", text)
    return text if len(text) <= max_length else text[:max_length] + f"…[truncated; length={len(text)}]"


def sanitize_upstream_value(value: Any, *, _depth: int = 0, _key: str = "") -> Any:
    """递归复制并脱敏 JSON/headers；不改变真实请求，限制深度、条数和正文长度。"""
    if _secret_key(_key):
        return _REDACTED
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "bytes", "length": len(value)}
    if isinstance(value, str):
        media = _DATA_URI_HEADER_RE.match(value)
        if media:
            return {"type": "data_uri", "media_type": media[1], "encoding": "base64", "length": len(value) - media.end()}
        if "base64" in _key.lower() or "b64" in _key.lower() or (
            len(value) >= 128 and len(value) % 4 == 0 and re.fullmatch(r"[A-Za-z0-9+/=\r\n]+", value)
        ):
            return {"type": "base64", "length": len(value)}
        limit = MAX_GENERATION_PROMPT_CHARS if _key in {"prompt", "text"} else _MAX_STRING
        return _safe_text(value, limit)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if _depth >= _MAX_DEPTH:
        return {"type": "truncated", "reason": "max_depth"}
    if isinstance(value, Mapping):
        result = {
            str(key): sanitize_upstream_value(item, _depth=_depth + 1, _key=str(key))
            for key, item in islice(value.items(), _MAX_ITEMS)
        }
        if len(value) > _MAX_ITEMS:
            result["_truncated_items"] = len(value) - _MAX_ITEMS
        return result
    if isinstance(value, (list, tuple)):
        result = [sanitize_upstream_value(item, _depth=_depth + 1) for item in value[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            result.append({"_truncated_items": len(value) - _MAX_ITEMS})
        return result
    return {"type": type(value).__name__}
