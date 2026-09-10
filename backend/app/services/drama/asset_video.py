"""画布视频资产：按提示词与参考图调用 Seedance 生成成片。"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import User
from app.models_drama import DramaAsset, DramaProject
from app.services.ark import get_ark
from app.services.drama.billing_util import record_seedance_video_usage, seedance_billing_key
from app.services.drama.build_seedance_generate_body import (
    build_seedance_generate_body,
    drama_asset_to_payload,
)
from app.services.drama.generation import (
    ensure_reference_assets_public_urls,
    extract_asset_ids_from_content,
)

logger = logging.getLogger(__name__)


# 合并正文 @asset:id 与显式传入的参考资产 ID（去重、排除自身）
def merge_reference_asset_ids(
    prompt: str,
    extra_ids: list[int] | None,
    *,
    self_asset_id: int,
) -> list[int]:
    merged: list[int] = []
    seen: set[int] = set()
    for asset_id in [*extract_asset_ids_from_content(prompt), *(extra_ids or [])]:
        if asset_id == self_asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        merged.append(asset_id)
    return merged


# 按项目加载参考资产，忽略跨项目或已删除的 ID
async def load_reference_assets(
    db: AsyncSession,
    project_id: int,
    asset_ids: list[int],
) -> list[DramaAsset]:
    assets: list[DramaAsset] = []
    for asset_id in asset_ids:
        asset = await db.get(DramaAsset, asset_id)
        if not asset or asset.project_id != project_id:
            continue
        assets.append(asset)
    return assets


async def generate_asset_video(
    db: AsyncSession,
    user: User,
    project: DramaProject,
    asset: DramaAsset,
    prompt: str,
    *,
    model_id: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    duration_sec: int | None = None,
    image_style_id: str | None = None,
    reference_asset_ids: list[int] | None = None,
) -> DramaAsset:
    """为画布 video 资产生成 Seedance 视频（不是 Seedream 静帧）。"""
    settings = get_settings()
    ark = get_ark()
    # content 用户提示词（保留 @asset:id 供 Seedance 替换）
    # duration 夹紧到官方时长区间
    # style_id 画面风格
    content = (prompt or "").strip() or "短剧镜头"
    duration = int(duration_sec or 8)
    duration = max(settings.seedance_duration_min, min(duration, settings.seedance_duration_max))
    style_id = (image_style_id or "").strip() or str(
        (project.params or {}).get("image_style_id") or ""
    ).strip() or None
    ratio = (aspect_ratio or "").strip() or "9:16"
    res = (resolution or "").strip() or "720p"

    ref_ids = merge_reference_asset_ids(
        content,
        reference_asset_ids,
        self_asset_id=asset.id,
    )
    ref_assets = await load_reference_assets(db, project.id, ref_ids)
    ref_assets = await ensure_reference_assets_public_urls(db, ref_assets)
    ref_payloads = [drama_asset_to_payload(item) for item in ref_assets]

    t0 = time.time()
    body = build_seedance_generate_body(
        {
            "content": content,
            "reference": ref_payloads,
            "model_id": model_id,
            "video_style_id": style_id,
            "aspect_ratio": ratio,
            "resolution": res,
            "duration_fallback": duration,
        }
    )
    local_video, local_last_frame, task_result = await ark.gen_and_wait_seedance_body(
        body,
        project_id=project.id,
        shot_no=asset.id,
    )

    from app.services import storage as storage_svc

    video_url = storage_svc.republish_url(local_video, sync=True) or local_video
    cover_url = ""
    video_path = storage_svc.local_path_from_url(local_video)
    if video_path is None and isinstance(local_video, str) and not local_video.startswith("http"):
        candidate = Path(local_video)
        if candidate.exists():
            video_path = candidate
    if video_path and video_path.exists():
        from app.services.ffmpeg_compose import extract_video_poster_frame

        poster_dest = storage_svc.project_dir(project.id) / f"asset_{asset.id}_cover.jpg"
        if extract_video_poster_frame(video_path, poster_dest):
            cover_src = storage_svc.rel_static_url(poster_dest)
            cover_url = storage_svc.republish_url(cover_src, sync=True) or cover_src
    if local_last_frame and not cover_url:
        cover_url = storage_svc.republish_url(local_last_frame, sync=True) or local_last_frame

    asset.url = video_url
    asset.cover = cover_url or asset.cover or ""
    asset.asset_type = "video"
    params = dict(asset.params or {})
    params["visualPrompt"] = content
    params["generation"] = {"status": "done"}
    params["videoOptions"] = {
        "model_id": model_id or "seedance-2.5",
        "aspect_ratio": ratio,
        "resolution": res,
        "duration_sec": duration,
        "image_style_id": style_id,
    }
    asset.params = params

    await record_seedance_video_usage(
        db,
        user_id=user.id,
        billing_key=seedance_billing_key(generate_audio=True),
        model=settings.model_video,
        domain="drama",
        task_result=task_result,
        fallback_duration_sec=duration,
        provider_task_id=getattr(task_result, "provider_task_id", None),
        drama_project_id=project.id,
    )
    await db.commit()
    await db.refresh(asset)
    logger.info(
        "画布资产生视频完成 project_id=%s asset_id=%s secs=%.1f url=%s refs=%s",
        project.id,
        asset.id,
        time.time() - t0,
        (video_url or "")[:80],
        [item.id for item in ref_assets],
    )
    return asset
