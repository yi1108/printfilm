"""漫剧计费辅助：Seedance token 估算、Seed LLM 用量聚合。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import UsageEvent, User
from app.services.billing import record_line
from app.services.billing.context import get_current_task_run_id
from app.services.drama.seed import SeedAssetsResult

if TYPE_CHECKING:
    from app.services.ark import ImageResult, TaskResult


# 按分镜时长×清晰度估算 Seedance 视频 token（1080p≈5 万/秒，与计价一致）
def seedance_video_billing_tokens(
    duration_sec: int | float | None,
    resolution: str = "",
) -> int:
    from app.services.tokenfree_pricing import estimate_seedance_billing_tokens

    return estimate_seedance_billing_tokens(
        max(float(duration_sec or 8), 2.0),
        resolution=resolution,
        settings=get_settings(),
    )


def seedance_billing_key(*, generate_audio: bool = True) -> str:
    return "seedance2:video0" if generate_audio else "seedance2:video1"


def _stamp_video_billing_facts(
    raw: dict[str, Any] | None,
    *,
    seconds: float | None,
    resolution: str,
    tokens: int | None = None,
) -> dict[str, Any] | None:
    """把时长/清晰度/tokens 写进 usage，供 TokenFree 表达式结算。"""
    try:
        secs = float(seconds) if seconds is not None else 0.0
    except (TypeError, ValueError):
        secs = 0.0
    res = (resolution or "").strip().lower()
    try:
        tok = int(tokens or 0)
    except (TypeError, ValueError):
        tok = 0
    if secs <= 0 and not res and tok <= 0:
        return raw
    body = dict(raw or {})
    usage = dict(body.get("usage") or {}) if isinstance(body.get("usage"), dict) else {}
    if secs > 0:
        usage.setdefault("seconds", secs)
    if res:
        usage.setdefault("resolution", res)
    if tok > 0:
        usage.setdefault("tokens", tok)
    usage.setdefault("input_video_seconds", float(usage.get("input_video_seconds") or 0))
    body["usage"] = usage
    return body


# 匹配 raw JSON 中的 provider_task_id 字段（带 key，避免裸 ID 子串误伤；兼容 dumps 空格）
def _provider_task_id_match(provider_id: str):
    pid = provider_id.replace("\\", "\\\\").replace('"', '\\"')
    return or_(
        UsageEvent.raw_usage_json.contains(f'"provider_task_id": "{pid}"'),
        UsageEvent.raw_usage_json.contains(f'"provider_task_id":"{pid}"'),
    )


async def record_seedance_video_usage(
    db: AsyncSession,
    *,
    user_id: int,
    billing_key: str,
    model: str,
    domain: str,
    task_result: TaskResult | None = None,
    fallback_duration_sec: float | None = None,
    resolution: str = "",
    provider_task_id: str | None = None,
    delivered: bool = True,
    drama_project_id: int | None = None,
    project_id: int | None = None,
    shot_id: int | None = None,
) -> UsageEvent:
    """按官方任务 usage / 成本或时长估算写入 Seedance 视频用量行。

    幂等：同 task_run+billing_key，或同 provider_task_id 已有行时直接返回，避免并发收尾双记。
    """
    from app.services.tokenfree_pricing import canonicalize_channel_model_id

    # 落库 id 规范到 TokenFree 目录（seedance-2-5 → seedance-2.5），避免按错误档位计价
    model = canonicalize_channel_model_id((model or "").strip()) or (model or "").strip() or "seedance-2.5"
    tid = get_current_task_run_id()
    provider_id = (provider_task_id or "").strip()

    from app.services.media_models.runtime import current_snapshot, operation_for
    fixed = bool((current_snapshot.get() or {}).get("mode") == "fixed_media")
    if tid is not None and not fixed:
        existing = (
            await db.execute(
                select(UsageEvent)
                .where(
                    UsageEvent.task_run_id == int(tid),
                    UsageEvent.billing_key == billing_key,
                )
                .order_by(UsageEvent.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    # 无 billing_scope 时仍可按上游任务 ID 精确去重
    if provider_id:
        by_provider = (
            await db.execute(
                select(UsageEvent)
                .where(
                    UsageEvent.user_id == int(user_id),
                    UsageEvent.billing_key == billing_key,
                    UsageEvent.raw_usage_json.is_not(None),
                    _provider_task_id_match(provider_id),
                )
                .order_by(UsageEvent.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if by_provider is not None:
            return by_provider

    if (
        (not task_result or int(getattr(task_result, "total_tokens", 0) or 0) <= 0)
        and provider_id
    ):
        from app.services.ark import get_ark

        try:
            refreshed = await get_ark().fetch_task_once(provider_id)
            if int(getattr(refreshed, "total_tokens", 0) or 0) > 0 or refreshed.raw_usage:
                task_result = refreshed
        except Exception:  # noqa: BLE001
            pass

    total_tokens = int(getattr(task_result, "total_tokens", 0) or 0)
    completion_tokens = int(getattr(task_result, "completion_tokens", 0) or 0)
    raw_usage = getattr(task_result, "raw_usage", None)
    upstream_from_result = getattr(task_result, "upstream_cost_fen", None)
    # TaskResult.raw_usage 可能是整包 {usage:{...}} 或已是 usage 块
    raw: dict[str, Any] | None = None
    if isinstance(raw_usage, dict):
        raw = dict(raw_usage)
        usage_block = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        merged_usage = dict(usage_block) if usage_block else {}
        if not merged_usage and any(k in raw for k in ("total_tokens", "completion_tokens", "tokens", "quota")):
            for key in (
                "total_tokens",
                "completion_tokens",
                "tokens",
                "prompt_tokens",
                "quota",
                "quota_consumed",
                "consumed_quota",
                "cost_fen",
            ):
                if raw.get(key) is not None:
                    merged_usage[key] = raw.get(key)
        if "creditsConsumed" in raw and "creditsConsumed" not in merged_usage:
            merged_usage["creditsConsumed"] = raw.get("creditsConsumed")
        if upstream_from_result is not None:
            merged_usage["cost_fen"] = int(upstream_from_result)
        elif raw.get("cost_fen") is not None:
            merged_usage["cost_fen"] = int(raw["cost_fen"])
        if total_tokens > 0:
            merged_usage.setdefault("total_tokens", total_tokens)
            merged_usage.setdefault("tokens", total_tokens)
        if completion_tokens > 0:
            merged_usage.setdefault("completion_tokens", completion_tokens)
        if merged_usage:
            raw["usage"] = merged_usage
    elif provider_id:
        raw = {"usage": {}}
    if provider_id:
        raw = {**(raw or {}), "provider_task_id": provider_id}
    if fixed:
        operation = operation_for("video", target=shot_id, model=model)
        raw = {**(raw or {}), "media_operation_id": operation["operation_id"]}
        if delivered and task_result is not None and task_result.status == "succeeded":
            # Callers record only after saving and associating the result.
            raw["delivery_id"] = provider_id or getattr(task_result, "url", None)

    fallback_tokens = 0
    if fallback_duration_sec is not None:
        fallback_tokens = seedance_video_billing_tokens(
            fallback_duration_sec, resolution=resolution
        )
    # 无上游 token 时把时长估算 token 写入 usage，避免表达式按秒价表低估
    stamp_tokens = total_tokens or fallback_tokens or None
    raw = _stamp_video_billing_facts(
        raw,
        seconds=fallback_duration_sec,
        resolution=resolution,
        tokens=stamp_tokens,
    )
    if total_tokens <= 0 and fallback_tokens > 0 and raw is not None:
        # 标明 tokens 是按时长本地估算，record_line 不得据此把用量判成上游实测
        raw = {**raw, "usage": {**(raw.get("usage") or {}), "tokens_estimated": True}}

    from app.services.billing.pricing import parse_upstream_cost_fen

    upstream_cost = None
    if upstream_from_result is not None:
        try:
            upstream_cost = max(0, int(upstream_from_result))
        except (TypeError, ValueError):
            upstream_cost = None
    if upstream_cost is None:
        upstream_cost = parse_upstream_cost_fen(raw) if raw else None
    if upstream_cost is not None and raw is not None:
        raw["usage"] = {**(raw.get("usage") or {}), "cost_fen": upstream_cost}

    if total_tokens > 0 or upstream_cost:
        return await record_line(
            db,
            user_id=user_id,
            billing_key=billing_key,
            model=model,
            tokens=total_tokens or fallback_tokens,
            completion_tokens=completion_tokens,
            estimated=False,
            raw=raw,
            project_id=project_id,
            drama_project_id=drama_project_id,
            shot_id=shot_id,
            domain=domain,
            provider="ark",
        )

    return await record_line(
        db,
        user_id=user_id,
        billing_key=billing_key,
        model=model,
        tokens=fallback_tokens,
        estimated=True,
        raw=raw,
        project_id=project_id,
        drama_project_id=drama_project_id,
        shot_id=shot_id,
        domain=domain,
        provider="ark",
    )


async def record_seedream_image_usage(
    db: AsyncSession,
    *,
    user_id: int,
    model: str,
    domain: str,
    image_result: ImageResult | None = None,
    project_id: int | None = None,
    drama_project_id: int | None = None,
    shot_id: int | None = None,
    extra_raw: dict[str, Any] | None = None,
    delivered: bool = True,
) -> UsageEvent:
    """按 Seedream 响应 usage / 成本写入图片用量行；缺失时回退估算 token。"""
    total_tokens = int(getattr(image_result, "total_tokens", 0) or 0)
    completion_tokens = int(getattr(image_result, "completion_tokens", 0) or 0)
    prompt_tokens = int(getattr(image_result, "prompt_tokens", 0) or 0)
    raw_usage = getattr(image_result, "raw_usage", None)
    upstream_cost = getattr(image_result, "upstream_cost_fen", None)

    raw: dict[str, Any] = dict(extra_raw or {})
    if delivered and image_result is not None and image_result.local_url:
        raw["delivery_id"] = image_result.local_url
    if raw_usage and isinstance(raw_usage, dict):
        nested = raw_usage.get("usage") if isinstance(raw_usage.get("usage"), dict) else None
        if nested is not None:
            for key, value in raw_usage.items():
                if key != "usage":
                    raw[key] = value
            raw["usage"] = {**(raw.get("usage") or {}), **nested}
        else:
            raw["usage"] = {**(raw.get("usage") or {}), **raw_usage}
    if upstream_cost is not None:
        raw["usage"] = {**(raw.get("usage") or {}), "cost_fen": int(upstream_cost)}
    if delivered and image_result is not None:
        # Each call records one delivered image, even when the provider omits usage.
        raw["usage"] = {**(raw.get("usage") or {}), "image_count": 1}
    if not delivered:
        raw.pop("delivery_id", None)
        if isinstance(raw.get("usage"), dict):
            raw["usage"] = {key: value for key, value in raw["usage"].items() if key != "delivery_id"}

    if total_tokens > 0 or upstream_cost:
        return await record_line(
            db,
            user_id=user_id,
            billing_key="seedream",
            model=model,
            tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated=False,
            raw=raw or None,
            project_id=project_id,
            drama_project_id=drama_project_id,
            shot_id=shot_id,
            domain=domain,
            provider="ark",
        )

    return await record_line(
        db,
        user_id=user_id,
        billing_key="seedream",
        model=model,
        estimated=True,
        raw=raw or None,
        project_id=project_id,
        drama_project_id=drama_project_id,
        shot_id=shot_id,
        domain=domain,
        provider="ark",
    )


async def record_seed_assets_llm_usage(
    db: AsyncSession,
    user: User,
    drama_project_id: int,
    result: SeedAssetsResult,
) -> None:
    """按 seed 结果聚合 LLM 调用次数写入 usage_events（需在 billing_scope 内）。"""
    settings = get_settings()
    llm_calls = int(result.llm_calls_props or 0) + int(result.prompts_refreshed or 0)
    if llm_calls <= 0:
        return
    if llm_calls == 1:
        await record_line(
            db,
            user_id=user.id,
            project_id=None,
            drama_project_id=drama_project_id,
            billing_key="llm_chat",
            model=settings.model_llm,
            estimated=True,
            domain="drama",
        )
        return
    await record_line(
        db,
        user_id=user.id,
        project_id=None,
        drama_project_id=drama_project_id,
        billing_key="llm_chat",
        model=settings.model_llm,
        tokens=settings.billing_est_llm_tokens * llm_calls,
        estimated=True,
        domain="drama",
    )
