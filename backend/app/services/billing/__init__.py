# -*- coding: utf-8 -*-
"""统一任务计费：预扣 → 记录用量 → 任务结束结算。"""
from __future__ import annotations

from app.services.billing.context import billing_scope, get_current_task_run_id, set_current_task_run_id
from app.services.billing.ephemeral import (
    create_ephemeral_task_row,
    run_billed_ephemeral,
    run_billed_ephemeral_deferred,
    run_with_registered_handler,
    settle_deferred_video_poll,
)
from app.services.billing.estimates import estimate_phase_fen, estimate_task_fen
from app.services.kepu_stages import resolve_kepu_billing_phase
from app.services.billing.pricing import (
    ORDER_EXPIRE_SECONDS,
    SKUS,
    billing_key_label,
    billing_key_to_capability,
    charge_fen_for_tokens,
    parse_usage_dict,
    provider_yuan_per_m,
    sku_by_id,
)
from app.services.billing.settlement import (
    billing_active,
    close_expired_pending_orders,
    credit_topup,
    ensure_balance_for_task,
    ensure_balance_for_task_batch,
    freeze_for_task,
    get_task_billing_summary,
    get_task_usage_lines,
    pending_task_commitment_fen,
    settle_project,
    settle_task,
    settle_usage_charge,
)
from app.services.billing.usage import record_line, record_llm_chat_line, record_usage

__all__ = [
    "ORDER_EXPIRE_SECONDS",
    "SKUS",
    "billing_active",
    "billing_key_label",
    "billing_key_to_capability",
    "billing_scope",
    "charge_fen_for_tokens",
    "close_expired_pending_orders",
    "create_ephemeral_task_row",
    "credit_topup",
    "estimate_phase_fen",
    "estimate_task_fen",
    "resolve_kepu_billing_phase",
    "ensure_balance_for_task",
    "ensure_balance_for_task_batch",
    "freeze_for_task",
    "get_current_task_run_id",
    "get_task_billing_summary",
    "get_task_usage_lines",
    "parse_usage_dict",
    "pending_task_commitment_fen",
    "provider_yuan_per_m",
    "record_line",
    "record_llm_chat_line",
    "record_usage",
    "run_billed_ephemeral",
    "run_billed_ephemeral_deferred",
    "run_with_registered_handler",
    "settle_deferred_video_poll",
    "set_current_task_run_id",
    "settle_project",
    "settle_task",
    "settle_usage_charge",
    "sku_by_id",
]
