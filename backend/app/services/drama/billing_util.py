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


# 按分镜时长估算 Seedance 视频 token（与科普 pipeline 一致）
def seedance_video_billing_tokens(duration_sec: int | float | None) -> int:
    settings = get_settings()
    dur = max(float(duration_sec or 8), 2.0)
    return int(dur * settings.billing_est_seedance_tokens_per_sec)


def seedance_billing_key(*, generate_audio: bool = True) -> str:
    return "seedance2:video0" if generate_audio else "seedance2:video1"


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
    provider_task_id: str | None = None,
    drama_project_id: int | None = None,
    project_id: int | None = None,
    shot_id: int | None = None,
) -> UsageEvent:
    """按官方任务 usage / 成本或时长估算写入 Seedance 视频用量行。

    幂等：同 task_run+billing_key，或同 provider_task_id 已有行时直接返回，避免并发收尾双记。
    """
    tid = get_current_task_run_id()
    provider_id = (provider_task_id or "").strip()

    if tid is not None:
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
    raw: dict[str, Any] | None = None
    if raw_usage:
        raw = {"usage": dict(raw_usage)}
    elif provider_id:
        raw = {"usage": {}}
    if provider_id:
        raw = {**(raw or {}), "provider_task_id": provider_id}

    from app.services.billing.pricing import parse_upstream_cost_fen

    upstream_cost = parse_upstream_cost_fen(raw) if raw else None
    if upstream_cost is not None and raw is not None:
        raw["usage"] = {**(raw.get("usage") or {}), "cost_fen": upstream_cost}

    if total_tokens > 0 or upstream_cost:
        return await record_line(
            db,
            user_id=user_id,
            billing_key=billing_key,
            model=model,
            tokens=total_tokens,
            completion_tokens=completion_tokens,
            estimated=False,
            raw=raw,
            project_id=project_id,
            drama_project_id=drama_project_id,
            shot_id=shot_id,
            domain=domain,
        )

    fallback_tokens = 0
    if fallback_duration_sec is not None:
        fallback_tokens = seedance_video_billing_tokens(fallback_duration_sec)

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
) -> UsageEvent:
    """按 Seedream 响应 usage / 成本写入图片用量行；缺失时回退估算 token。"""
    total_tokens = int(getattr(image_result, "total_tokens", 0) or 0)
    completion_tokens = int(getattr(image_result, "completion_tokens", 0) or 0)
    prompt_tokens = int(getattr(image_result, "prompt_tokens", 0) or 0)
    raw_usage = getattr(image_result, "raw_usage", None)
    upstream_cost = getattr(image_result, "upstream_cost_fen", None)

    raw: dict[str, Any] = dict(extra_raw or {})
    if raw_usage:
        raw["usage"] = dict(raw_usage)
    if upstream_cost is not None:
        raw["usage"] = {**(raw.get("usage") or {}), "cost_fen": int(upstream_cost)}

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
