"""Drama asset endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_drama import DramaAsset, DramaProject
from app.schemas_drama import DramaAssetCreate, DramaAssetOut, DramaAssetUpdate, SeedAssetsFromScriptOut
from app.services.drama.access import get_owned_drama_project
from app.services.billing import run_billed_ephemeral
from app.services.billing.http import http_exception_for_value_error
from app.services.drama.billing_util import record_seed_assets_llm_usage
from app.services.drama.jobs import dispatch_seed_assets_job
from app.services.drama.seed import (
    _asset_dedupe_key,
    _normalize_asset_name,
    purge_voice_like_character_assets,
    seed_assets_from_script,
)

router = APIRouter()


@router.get("/assets", response_model=list[DramaAssetOut])
async def list_assets(
    project_id: int | None = None,
    library_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DramaAssetOut]:
    # Global library = all assets of user's drama projects; optional project filter
    from app.services.drama.seed import merge_duplicate_library_assets

    q = (
        select(DramaAsset)
        .join(DramaProject, DramaAsset.project_id == DramaProject.id)
        .where(DramaProject.user_id == user.id)
        .order_by(DramaAsset.updated_at.desc())
    )
    if project_id is not None:
        await get_owned_drama_project(db, project_id, user)
        # 进入资产库时顺带合并同名重复，并清掉误入角色的音色名
        removed = await merge_duplicate_library_assets(db, int(project_id))
        purged = await purge_voice_like_character_assets(db, int(project_id))
        if removed or purged:
            await db.commit()
        q = q.where(DramaAsset.project_id == project_id)
    rows = list((await db.execute(q)).scalars().all())
    if library_only:
        canvas_only_types = {"video", "audio", "text"}
        rows = [
            asset
            for asset in rows
            if (asset.type or "").lower() not in canvas_only_types
            and (asset.asset_type or "").lower() != "video"
        ]
    return [DramaAssetOut.model_validate(a) for a in rows]


@router.post("/assets", response_model=DramaAssetOut)
async def create_asset(
    body: DramaAssetCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaAssetOut:
    await get_owned_drama_project(db, body.project_id, user)
    # 同类型同名已存在则直接返回，避免手动/并发再造重复卡
    want_name = _normalize_asset_name(body.name or "")
    if want_name:
        want_key = _asset_dedupe_key(body.type or "", want_name)
        existing_rows = list(
            (
                await db.execute(
                    select(DramaAsset).where(DramaAsset.project_id == body.project_id)
                )
            )
            .scalars()
            .all()
        )
        for row in existing_rows:
            key = _asset_dedupe_key(row.type or "", _normalize_asset_name(row.name or ""))
            if key == want_key:
                return DramaAssetOut.model_validate(row)
    asset = DramaAsset(
        project_id=body.project_id,
        type=body.type,
        asset_type=body.asset_type,
        name=body.name,
        cover=body.cover,
        url=body.url,
        params=body.params,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return DramaAssetOut.model_validate(asset)


@router.patch("/assets/{asset_id}", response_model=DramaAssetOut)
async def update_asset(
    asset_id: int,
    body: DramaAssetUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaAssetOut:
    from app.models_drama import DramaProject

    result = await db.execute(
        select(DramaAsset)
        .join(DramaProject, DramaAsset.project_id == DramaProject.id)
        .where(DramaAsset.id == asset_id, DramaProject.user_id == user.id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    for field in ("type", "asset_type", "name", "cover", "url", "params"):
        val = getattr(body, field)
        if val is not None:
            setattr(asset, field, val)
    await db.commit()
    await db.refresh(asset)
    return DramaAssetOut.model_validate(asset)


@router.post("/assets/{asset_id}/upload", response_model=DramaAssetOut)
async def upload_asset_media(
    asset_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DramaAssetOut:
    """Upload image/media for a drama asset directly to OSS (no local persist)."""
    from app.models_drama import DramaProject
    from app.services import oss as oss_svc

    if not oss_svc.oss_enabled():
        raise HTTPException(status_code=503, detail="OSS 未启用，无法上传资产媒体")

    result = await db.execute(
        select(DramaAsset)
        .join(DramaProject, DramaAsset.project_id == DramaProject.id)
        .where(DramaAsset.id == asset_id, DramaProject.user_id == user.id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")

    content_type = (file.content_type or "").lower()
    allowed = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    ext = allowed.get(content_type)
    if not ext:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            ext = ".jpg" if suffix == ".jpeg" else suffix
            content_type = {
                ".jpg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(ext, "application/octet-stream")
        else:
            raise HTTPException(status_code=400, detail="仅支持 JPG / PNG / WebP / GIF")

    # 直接检查上传临时文件大小，避免先把整文件读入内存。
    upload_fp = file.file
    try:
        upload_fp.seek(0, 2)
        size = upload_fp.tell()
        upload_fp.seek(0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"无法读取上传文件：{exc}") from exc
    if size <= 0:
        raise HTTPException(status_code=400, detail="空文件")
    if size > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 20MB")

    object_key = (
        f"{oss_svc.folder_prefix()}/generated/p{asset.project_id}/"
        f"asset_{asset.id}_{uuid.uuid4().hex[:10]}{ext}"
    )
    try:
        # OSS SDK 为同步阻塞 IO，放到线程池里避免阻塞事件循环。
        url = await run_in_threadpool(
            oss_svc.upload_fileobj,
            upload_fp,
            object_key,
            content_type=content_type or "application/octet-stream",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"OSS 上传失败：{exc}") from exc

    asset.url = url
    asset.cover = url
    if not asset.asset_type or asset.asset_type == "none":
        asset.asset_type = "image"
    params = dict(asset.params or {})
    gen = params.get("generation")
    if isinstance(gen, dict):
        params["generation"] = {**gen, "status": "done", "source": "upload"}
    else:
        params["generation"] = {"status": "done", "source": "upload"}
    asset.params = params
    await db.commit()
    await db.refresh(asset)
    return DramaAssetOut.model_validate(asset)


@router.delete("/assets/{asset_id}")
async def delete_asset(
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    from app.models_drama import DramaProject

    result = await db.execute(
        select(DramaAsset)
        .join(DramaProject, DramaAsset.project_id == DramaProject.id)
        .where(DramaAsset.id == asset_id, DramaProject.user_id == user.id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    await db.delete(asset)
    await db.commit()
    return {"ok": True}


@router.post("/assets/seed_from_script", response_model=SeedAssetsFromScriptOut)
async def seed_assets(
    project_id: int,
    refresh_prompts: bool = False,
    reextract_props: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SeedAssetsFromScriptOut:
    project = await get_owned_drama_project(db, project_id, user, with_script=True)
    heavy = bool(refresh_prompts or reextract_props)

    # 行锁：防止空库并发 seed 插入同名角色
    locked = (
        await db.execute(
            select(DramaProject).where(DramaProject.id == project.id).with_for_update()
        )
    ).scalar_one()
    params = dict(locked.params or {}) if isinstance(locked.params, dict) else {}
    if str(params.get("assets_seed_status") or "") == "generating":
        existing = list(
            (await db.execute(select(DramaAsset).where(DramaAsset.project_id == locked.id)))
            .scalars()
            .all()
        )
        return SeedAssetsFromScriptOut(
            assets=[DramaAssetOut.model_validate(a) for a in existing],
            status="generating",
            message="资产抽取进行中，请稍候刷新",
        )

    if heavy:
        params["assets_seed_status"] = "generating"
        params["assets_seed_generating_at"] = datetime.now(timezone.utc).isoformat()
        params.pop("assets_seed_error", None)
        locked.params = params
        try:
            await dispatch_seed_assets_job(
                db,
                user,
                project_id,
                refresh_prompts=refresh_prompts,
                reextract_props=reextract_props,
            )
        except ValueError as exc:
            await db.rollback()
            raise http_exception_for_value_error(exc) from exc
        existing = list(
            (await db.execute(select(DramaAsset).where(DramaAsset.project_id == locked.id)))
            .scalars()
            .all()
        )
        return SeedAssetsFromScriptOut(
            assets=[DramaAssetOut.model_validate(a) for a in existing],
            status="generating",
            message="资产抽取任务已提交，请稍候刷新",
        )

    params["assets_seed_status"] = "generating"
    params["assets_seed_generating_at"] = datetime.now(timezone.utc).isoformat()
    params.pop("assets_seed_error", None)
    locked.params = params
    await db.commit()
    try:
        async def _do_sync_seed():
            project_inner = await get_owned_drama_project(db, project_id, user, with_script=True)
            seed_result = await seed_assets_from_script(
                db,
                project_inner,
                refresh_prompts=refresh_prompts,
                reextract_props=reextract_props,
            )
            await record_seed_assets_llm_usage(db, user, project_id, seed_result)
            return seed_result

        _task, result = await run_billed_ephemeral(
            db,
            user,
            domain="drama",
            task_type="seed_assets",
            executor=_do_sync_seed,
            drama_project_id=project_id,
            payload={"sync": True, "refresh_prompts": refresh_prompts, "reextract_props": reextract_props},
            commit=False,
        )
        project = await get_owned_drama_project(db, project_id, user, with_script=True)
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "done"
        params.pop("assets_seed_error", None)
        params.pop("assets_seed_generating_at", None)
        project.params = params
        await db.commit()
    except ValueError as exc:
        project = await get_owned_drama_project(db, project_id, user, with_script=True)
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "failed"
        params["assets_seed_error"] = str(exc)[:500]
        params.pop("assets_seed_generating_at", None)
        project.params = params
        await db.commit()
        raise http_exception_for_value_error(exc) from exc
    except HTTPException:
        raise
    except RuntimeError as exc:
        project = await get_owned_drama_project(db, project_id, user, with_script=True)
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "failed"
        params["assets_seed_error"] = str(exc)[:500]
        params.pop("assets_seed_generating_at", None)
        project.params = params
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc
    except Exception:
        project = await get_owned_drama_project(db, project_id, user, with_script=True)
        params = dict(project.params or {}) if isinstance(project.params, dict) else {}
        params["assets_seed_status"] = "failed"
        params["assets_seed_error"] = "资产抽取失败"
        params.pop("assets_seed_generating_at", None)
        project.params = params
        await db.commit()
        raise
    return SeedAssetsFromScriptOut(
        assets=[DramaAssetOut.model_validate(a) for a in result.assets],
        created_count=result.created_count,
        prompts_refreshed=result.prompts_refreshed,
        props_updated=result.props_updated,
        llm_errors=result.llm_errors,
        status="done",
    )
