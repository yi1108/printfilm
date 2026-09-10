"""火山方舟 /v1/models 目录拉取（管理端选模型）。"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.model_routing_config import infer_model_capability, normalize_model_name

logger = logging.getLogger(__name__)

ARK_DEFAULT_BASE = "https://ark.cn-beijing.volces.com/api/v3"


def _model_id(item: dict[str, Any]) -> str:
    for key in ("id", "name", "model"):
        raw = item.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


async def _resolve_ark_credentials(
    db: AsyncSession | None,
    *,
    api_key_override: str | None = None,
) -> tuple[str, str]:
    key = (api_key_override or "").strip()
    base = (get_settings().ark_base_url or ARK_DEFAULT_BASE).rstrip("/")
    if key:
        return key, base
    settings = get_settings()
    key = (settings.ark_api_key or "").strip()
    if key:
        return key, base
    if db is not None:
        from app.services.model_settings import _load_channels

        channels = await _load_channels(db, runtime=True)
        for channel in channels:
            if channel.protocol != "ark" or not channel.enabled:
                continue
            candidate = (channel.api_key or "").strip()
            if candidate:
                return candidate, (channel.base_url or base).rstrip("/")
    return "", base


async def list_ark_models(
    db: AsyncSession | None = None,
    *,
    capability: str = "all",
    api_key_override: str | None = None,
) -> list[dict[str, str]]:
    """拉取方舟模型列表，并按 image/video 过滤。"""
    api_key, base = await _resolve_ark_credentials(db, api_key_override=api_key_override)
    if not api_key:
        raise RuntimeError("请先在「模型路由 → 火山方舟」配置 API Key")

    headers = {"Authorization": f"Bearer {api_key}"}
    models: list[dict[str, Any]] = []
    url: str | None = f"{base}/models"
    async with httpx.AsyncClient(timeout=60.0) as client:
        while url:
            resp = await client.get(url, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"拉取模型目录失败 HTTP {resp.status_code}: {resp.text[:300]}")
            payload = resp.json()
            data = payload.get("data")
            if isinstance(data, list):
                models.extend([item for item in data if isinstance(item, dict)])
            url = payload.get("next_page") or payload.get("next_page_url")
            if isinstance(url, str) and not url.strip():
                url = None

    cap_filter = (capability or "all").strip().lower()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in models:
        model_id = _model_id(item)
        if not model_id:
            continue
        cap = infer_model_capability(model_id)
        if cap_filter in {"image", "video"} and cap != cap_filter:
            continue
        if cap_filter == "all" and cap not in {"image", "video"}:
            continue
        key = normalize_model_name(model_id)
        if key in seen:
            continue
        seen.add(key)
        label = str(item.get("display_name") or item.get("object") or model_id)
        out.append({"id": model_id, "label": label, "capability": cap})
    out.sort(key=lambda row: row["id"])
    return out
