# -*- coding: utf-8 -*-
"""用量行写入：唯一写 usage_events 的入口。"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import UsageEvent
from app.services.billing.context import get_current_task_run_id
from app.services.billing.pricing import billing_key_to_capability, charge_fen_for_usage


async def record_line(
    db: AsyncSession,
    *,
    user_id: int,
    billing_key: str,
    model: str = "",
    tokens: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    estimated: bool = False,
    raw: dict | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    shot_id: int | None = None,
    provider: str = "ark",
    task_run_id: int | None = None,
    domain: str | None = None,
) -> UsageEvent:
    s = get_settings()
    tid = task_run_id if task_run_id is not None else get_current_task_run_id()
    total = int(tokens) or (int(prompt_tokens) + int(completion_tokens))
    if total <= 0:
        if billing_key == "llm_chat":
            total = s.billing_est_llm_tokens
            estimated = True
        elif billing_key == "seedream":
            total = s.billing_est_seedream_tokens
            estimated = True
        elif billing_key == "tts":
            total = s.billing_est_tts_tokens
            estimated = True
        elif billing_key.startswith("seedance"):
            total = s.billing_est_seedance_tokens_per_sec * 5
            estimated = True
    cost, charge, from_upstream = charge_fen_for_usage(
        total, billing_key, raw_usage=raw, settings=s
    )
    if from_upstream:
        estimated = False
    elif total > 0 and not estimated:
        pass
    elif total > 0 and estimated and raw:
        usage_parsed = raw.get("usage") if isinstance(raw.get("usage"), dict) else raw
        if isinstance(usage_parsed, dict) and int(usage_parsed.get("total_tokens") or 0) > 0:
            estimated = False
    capability = billing_key_to_capability(billing_key)
    ev = UsageEvent(
        user_id=user_id,
        project_id=project_id,
        drama_project_id=drama_project_id,
        task_run_id=tid,
        domain=domain,
        capability=capability,
        shot_id=shot_id,
        provider=provider,
        billing_key=billing_key,
        model=model or "",
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(completion_tokens),
        total_tokens=total,
        cost_fen=cost,
        charge_fen=charge,
        estimated=estimated,
        settled=False,
        raw_usage_json=json.dumps(raw, ensure_ascii=False)[:4000] if raw else None,
    )
    db.add(ev)
    await db.flush()
    return ev


async def record_llm_chat_line(
    db: AsyncSession,
    *,
    user_id: int,
    domain: str,
    drama_project_id: int | None = None,
    project_id: int | None = None,
    tokens: int | None = None,
) -> UsageEvent | None:
    """在 billing_scope 内记录一次 LLM 调用；无 scope 时跳过（由调用方聚合计费）。"""
    if get_current_task_run_id() is None:
        return None
    s = get_settings()
    return await record_line(
        db,
        user_id=user_id,
        billing_key="llm_chat",
        model=s.model_llm,
        tokens=int(tokens or 0),
        estimated=True,
        project_id=project_id,
        drama_project_id=drama_project_id,
        domain=domain,
    )


# 兼容旧调用名
async def record_usage(
    db: AsyncSession,
    *,
    user_id: int,
    project_id: int | None,
    billing_key: str,
    model: str = "",
    tokens: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    estimated: bool = False,
    raw: dict | None = None,
    shot_id: int | None = None,
    provider: str = "ark",
    drama_project_id: int | None = None,
    domain: str | None = None,
    task_run_id: int | None = None,
) -> UsageEvent:
    return await record_line(
        db,
        user_id=user_id,
        billing_key=billing_key,
        model=model,
        tokens=tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated=estimated,
        raw=raw,
        project_id=project_id,
        drama_project_id=drama_project_id,
        shot_id=shot_id,
        provider=provider,
        domain=domain,
        task_run_id=task_run_id,
    )
