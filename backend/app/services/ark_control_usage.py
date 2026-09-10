"""火山方舟管控面 GetInferenceUsage 客户端（HMAC 签名）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

HOST = "open.volcengineapi.com"
SERVICE = "ark"
VERSION = "2024-01-01"
ACTION = "GetInferenceUsage"


def volc_usage_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(
        s.volc_ark_usage_enabled
        and (s.volc_access_key_id or "").strip()
        and (s.volc_secret_access_key or "").strip()
    )


def _hash_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(secret_key.encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "request")


def _canonical_query(action: str, version: str) -> str:
    params = [("Action", action), ("Version", version)]
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params))


def _signed_headers(
    *,
    method: str,
    query: str,
    body: str,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
) -> dict[str, str]:
    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = _hash_sha256(body)
    canonical_headers = (
        f"host:{HOST}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{amz_date}\n"
    )
    signed_headers = "host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        [
            method.upper(),
            "/",
            query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{region}/{service}/request"
    string_to_sign = "\n".join(
        [
            "HMAC-SHA256",
            amz_date,
            credential_scope,
            _hash_sha256(canonical_request),
        ]
    )
    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f"HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Host": HOST,
        "Content-Type": "application/json; charset=utf-8",
        "X-Date": amz_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }


def parse_inference_usage_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """把 GetInferenceUsage 的 Fields/Data 表结构解析为行 dict。"""
    fields = result.get("Fields") or []
    data = result.get("Data") or []
    names: list[str] = []
    for field in fields:
        if isinstance(field, dict):
            names.append(str(field.get("Name") or ""))
    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, list):
            continue
        row = {names[i]: item[i] for i in range(min(len(names), len(item))) if names[i]}
        rows.append(row)
    return rows


def aggregate_usage_by_day(rows: list[dict[str, Any]]) -> dict[str, int]:
    """按日聚合 token（优先 Value / TotalTokens 字段）。"""
    daily: dict[str, int] = {}
    for row in rows:
        day_raw = row.get("Day") or row.get("Date") or row.get("day")
        if not day_raw:
            continue
        day_key = str(day_raw)[:10]
        model_name = str(row.get("ModelName") or row.get("Model") or row.get("Endpoint") or "").lower()
        if model_name and "seedance" not in model_name and "video" not in model_name:
            # 未标注模型时仍计入；有模型名则尽量只统计视频
            if any(token in model_name for token in ("gpt", "llm", "chat", "seedream", "tts", "text")):
                continue
        value = row.get("Value")
        if value is None:
            value = row.get("TotalTokens") or row.get("Tokens") or row.get("Token") or 0
        try:
            tokens = int(value or 0)
        except (TypeError, ValueError):
            tokens = 0
        if tokens <= 0:
            continue
        daily[day_key] = daily.get(day_key, 0) + tokens
    return daily


def build_inference_usage_request_body(start_date: str, end_date: str) -> dict[str, Any]:
    """构造 GetInferenceUsage 请求体（按日粒度）。"""
    return {
        "StartTime": start_date,
        "EndTime": end_date,
        "QueryInterval": "Day",
    }


async def get_inference_usage(
    start_date: str,
    end_date: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """调用方舟 GetInferenceUsage，返回原始 Result 与按日 token 聚合。"""
    s = settings or get_settings()
    if not volc_usage_configured(s):
        raise RuntimeError("请先在后台「支付计费 → 上游成本监控」配置火山 Access Key")

    body_obj = build_inference_usage_request_body(start_date, end_date)
    body = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
    query = _canonical_query(ACTION, VERSION)
    headers = _signed_headers(
        method="POST",
        query=query,
        body=body,
        access_key=s.volc_access_key_id.strip(),
        secret_key=s.volc_secret_access_key.strip(),
        region=(s.volc_ark_region or "cn-beijing").strip(),
        service=SERVICE,
    )
    url = f"https://{HOST}/?{query}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, content=body.encode("utf-8"), headers=headers)
    if resp.status_code >= 400:
        raise RuntimeError(f"GetInferenceUsage HTTP {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()
    metadata = payload.get("ResponseMetadata") or {}
    if metadata.get("Error"):
        err = metadata["Error"]
        raise RuntimeError(f"GetInferenceUsage error: {err}")
    result = payload.get("Result") or {}
    rows = parse_inference_usage_rows(result)
    daily_tokens = aggregate_usage_by_day(rows)
    return {
        "result": result,
        "rows": rows,
        "daily_tokens": daily_tokens,
        "request_id": metadata.get("RequestId"),
    }
