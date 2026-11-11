"""Printfilm Studio canvas API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.printfilm_studio import ensure_enabled
from app.printfilm_studio.canvas.service import get_or_create, get_project, list_assets, save
from app.printfilm_studio.integration.assets import asset_out, import_asset, upload_asset

router = APIRouter(prefix="/printfilm-studio", tags=["printfilm-studio-canvas"])


async def writable_project(project_id: Annotated[int, Path(gt=0)], db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), edit_session_id: str | None = Header(default=None, alias='X-Edit-Session'), edit_lock_token: str | None = Header(default=None, alias='X-Edit-Token'), edit_lock_version: int | None = Header(default=None, alias='X-Edit-Version')):
    ensure_enabled()
    project = await get_project(db, project_id, user)
    return project


@router.post('/projects/{project_id}/canvas/assets/upload')
async def upload_canvas_asset(project=Depends(writable_project), file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> dict:
    return asset_out(await upload_asset(db, project, file))


@router.post('/projects/{project_id}/canvas/assets/{asset_id}/import')
async def import_canvas_asset(asset_id: int, project=Depends(writable_project), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return asset_out(await import_asset(db, project, user, asset_id))


class CanvasSaveRequest(BaseModel):
    document: dict
    expected_version: int = Field(ge=1)


class StoryRepairRequest(BaseModel):
    script_node_id: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=1)


@router.post('/projects/{project_id}/canvas/story/repair')
async def repair_story(body: StoryRepairRequest, project=Depends(writable_project), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.printfilm_studio.agent.story_graph import repair_story_graph
    row = await get_or_create(db, project, user)
    if row.document_version != body.expected_version:
        raise HTTPException(409, '画布已变化，请刷新后重试')
    try:
        document = repair_story_graph(row.document, body.script_node_id)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return _response(await save(db, project, user, document, body.expected_version))


def _response(row) -> dict:
    return {"document": row.document, "version": row.document_version, "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at}


@router.get("/projects/{project_id}/canvas")
async def read_canvas(project_id: Annotated[int, Path(gt=0)], db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_enabled()
    project = await get_project(db, project_id, user)
    row = await get_or_create(db, project, user)
    await db.commit()
    return _response(row)


@router.put("/projects/{project_id}/canvas")
async def write_canvas(project_id: Annotated[int, Path(gt=0)], body: CanvasSaveRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), edit_session_id: str | None = Header(default=None, alias="X-Edit-Session"), edit_lock_token: str | None = Header(default=None, alias="X-Edit-Token"), edit_lock_version: int | None = Header(default=None, alias="X-Edit-Version")) -> dict:
    ensure_enabled()
    project = await get_project(db, project_id, user)
    return _response(await save(db, project, user, body.document, body.expected_version))


@router.post("/projects/{project_id}/canvas/reset")
async def reset_canvas(project_id: Annotated[int, Path(gt=0)], db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), edit_session_id: str | None = Header(default=None, alias="X-Edit-Session"), edit_lock_token: str | None = Header(default=None, alias="X-Edit-Token"), edit_lock_version: int | None = Header(default=None, alias="X-Edit-Version")) -> dict:
    ensure_enabled()
    project = await get_project(db, project_id, user)
    row = await get_or_create(db, project, user)
    return _response(await save(db, project, user, {"version": 1, "nodes": [], "edges": []}, row.document_version))


@router.get("/projects/{project_id}/canvas/assets")
async def read_assets(project_id: Annotated[int, Path(gt=0)], db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_enabled()
    project = await get_project(db, project_id, user)
    assets = await list_assets(db, project)
    return {"assets": [{"id": a.id, "name": a.name, "type": a.type, "asset_type": a.asset_type, "url": a.url, "cover": a.cover, "params": a.params} for a in assets]}
