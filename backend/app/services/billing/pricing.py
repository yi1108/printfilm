# -*- coding: utf-8 -*-
"""Token 单价与费用换算。"""
from __future__ import annotations

import math
from typing import Any

from app.config import Settings, get_settings

SKUS: list[dict[str, Any]] = [
    {"id": "topup_10", "name": "体验充值", "amount_fen": 10000, "credit_fen": 10000},
    {"id": "topup_49", "name": "基础充值", "amount_fen": 49000, "credit_fen": 49000},
    {"id": "topup_99", "name": "进阶充值", "amount_fen": 99000, "credit_fen": 104000, "recommended": True},
    {"id": "topup_199", "name": "专业充值", "amount_fen": 199000, "credit_fen": 220000},
]

ORDER_EXPIRE_SECONDS = 300


def provider_yuan_per_m(billing_key: str, settings: Settings | None = None) -> float:
    s = settings or get_settings()
    table = {
        "seedance2:video0": s.billing_seedance_video0,
        "seedance2:video1": s.billing_seedance_video1,
        "llm_chat": s.billing_llm_per_m,
        "seedream": s.billing_seedream_per_m,
        "tts": s.billing_tts_per_m,
    }
    return float(table.get(billing_key, s.billing_llm_per_m))


def charge_fen_for_tokens(
    tokens: int,
    billing_key: str,
    *,
    settings: Settings | None = None,
) -> tuple[int, int]:
    """Return (cost_fen, charge_fen) with markup."""
    s = settings or get_settings()
    t = max(0, int(tokens))
    yuan_per_m = provider_yuan_per_m(billing_key, s)
    cost = math.ceil(t / 1_000_000 * yuan_per_m * 100) if t else 0
    charge = math.ceil(cost * float(s.billing_markup)) if cost else 0
    if t > 0 and charge < 1:
        charge = 1
        cost = max(cost, 1)
    return cost, charge


def parse_upstream_cost_fen(data: dict[str, Any] | None) -> int | None:
    """从火山 usage / 响应块解析上游成本（分）；无则 None。"""
    if not data:
        return None
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else data
    if not isinstance(usage, dict):
        return None
    for key in ("cost_fen", "cost_cents"):
        if usage.get(key) is not None:
            try:
                return max(0, int(usage[key]))
            except (TypeError, ValueError):
                pass
    for key in ("cost", "total_cost", "amount", "cost_yuan", "total_cost_yuan"):
        if usage.get(key) is not None:
            try:
                return max(0, int(math.ceil(float(usage[key]) * 100)))
            except (TypeError, ValueError):
                pass
    return None


def charge_fen_for_usage(
    tokens: int,
    billing_key: str,
    *,
    raw_usage: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> tuple[int, int, bool]:
    """按火山返回的实际成本或 token 用量计算 (cost_fen, charge_fen, used_upstream_cost)。"""
    s = settings or get_settings()
    upstream_cost = parse_upstream_cost_fen(raw_usage)
    if upstream_cost is not None and upstream_cost > 0:
        cost = upstream_cost
        charge = math.ceil(cost * float(s.billing_markup))
        if charge < 1:
            charge = 1
        return cost, charge, True
    cost, charge = charge_fen_for_tokens(tokens, billing_key, settings=s)
    return cost, charge, False


def parse_usage_dict(data: dict[str, Any] | None) -> dict[str, int]:
    if not data:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else data
    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("generated_tokens")
        or 0
    )
    total = int(usage.get("total_tokens") or (prompt + completion) or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def billing_key_to_capability(billing_key: str) -> str:
    key = (billing_key or "").strip().lower()
    if key == "llm_chat":
        return "llm"
    if key == "seedream":
        return "image"
    if key.startswith("seedance"):
        return "video"
    if key == "tts":
        return "tts"
    return "other"


def billing_key_label(billing_key: str) -> str:
    cap = billing_key_to_capability(billing_key)
    labels = {"llm": "LLM 对话", "image": "图片生成", "video": "视频生成", "tts": "语音合成"}
    return labels.get(cap, billing_key or "其他")


def sku_by_id(sku_id: str) -> dict[str, Any] | None:
    for item in SKUS:
        if item["id"] == sku_id:
            return item
    return None
