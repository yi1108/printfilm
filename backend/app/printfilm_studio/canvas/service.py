"""Canvas persistence and access checks."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models_drama import DramaAsset, DramaProject
from app.models_printfilm_studio import PrintfilmStudioCanvasDocument
from app.printfilm_studio.sharing import require_canvas_access
from .codec import decode_canvas_document


async def get_project(db: AsyncSession, project_id: int, user: User) -> DramaProject:
    project = await db.get(DramaProject, project_id, populate_existing=True)
    if not project:
        raise HTTPException(status_code=404, detail="漫剧项目不存在")
    await require_canvas_access(db, project, user.id)
    return project


async def get_or_create(db: AsyncSession, project: DramaProject, user: User) -> PrintfilmStudioCanvasDocument:
    row = await db.scalar(select(PrintfilmStudioCanvasDocument).where(PrintfilmStudioCanvasDocument.project_id == project.id))
    if row:
        return row
    row = PrintfilmStudioCanvasDocument(project_id=project.id, team_id=project.team_id, document=decode_canvas_document({}), document_version=1, created_by=user.id, updated_by=user.id)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # Another reader may initialize the same project's unique document first.
        row = await db.scalar(select(PrintfilmStudioCanvasDocument).where(PrintfilmStudioCanvasDocument.project_id == project.id))
        if row is None:
            raise
    return row


async def save(db: AsyncSession, project: DramaProject, user: User, document: dict, expected_version: int) -> PrintfilmStudioCanvasDocument:
    from app.printfilm_studio.sharing import project_for
    await project_for(db, project.id, user, lock=True)
    # 项目成员权限与文档版本分别防止越权和并发覆盖。
    try:
        normalized = decode_canvas_document(document)
    except (ValueError, TypeError, OverflowError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    asset_ids = set()
    for node in normalized['nodes']:
        asset_id = node['data'].get('assetId')
        if asset_id is None:
            continue
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id <= 0:
            raise HTTPException(status_code=422, detail='节点资产 ID 无效')
        asset_ids.add(asset_id)
    if asset_ids:
        allowed = set((await db.scalars(select(DramaAsset.id).where(DramaAsset.project_id == project.id, DramaAsset.id.in_(asset_ids)))).all())
        if asset_ids != allowed:
            raise HTTPException(status_code=422, detail='节点引用了当前项目以外或不存在的资产')
    row = await get_or_create(db, project, user)
    # Compare and increment inside the same SQL statement; an ORM check followed
    # by a normal UPDATE permits concurrent clients to overwrite each other.
    saved_id = await db.scalar(update(PrintfilmStudioCanvasDocument).where(
        PrintfilmStudioCanvasDocument.id == row.id,
        PrintfilmStudioCanvasDocument.document_version == expected_version,
    ).values(document=normalized, document_version=expected_version + 1, updated_by=user.id).returning(PrintfilmStudioCanvasDocument.id).execution_options(synchronize_session=False))
    if saved_id is None:
        await db.refresh(row)
        raise HTTPException(status_code=409, detail={"message": "画布版本已变化，请刷新后重试", "version": row.document_version})
    await db.commit()
    await db.refresh(row)
    return row


async def list_assets(db: AsyncSession, project: DramaProject) -> list[DramaAsset]:
    return list((await db.scalars(select(DramaAsset).where(DramaAsset.project_id == project.id).order_by(DramaAsset.updated_at.desc(), DramaAsset.id.desc()))).all())
