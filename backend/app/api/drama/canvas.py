"""Drama canvas persistence (nodes stored as project content + none-type assets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_drama import DramaAsset
from app.schemas_drama import DramaCanvasSaveRequest
from app.services.drama.access import get_owned_drama_project

router = APIRouter()


@router.get("/canvas/{project_id}")
async def get_canvas(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = await get_owned_drama_project(db, project_id, user, with_assets=True)
    content = project.content if isinstance(project.content, dict) else {}
    return {
        "project_id": project_id,
        "nodes": content.get("canvas_nodes") or [],
        "edges": content.get("canvas_edges") or [],
    }


@router.post("/canvas")
async def save_canvas(
    body: DramaCanvasSaveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project = await get_owned_drama_project(db, body.project_id, user, with_assets=True)
    content = dict(project.content) if isinstance(project.content, dict) else {}
    content["canvas_nodes"] = body.nodes
    content["canvas_edges"] = body.edges
    project.content = content

    # Upsert canvas nodes as type=none assets keyed by node id in params
    existing = {
        str((a.params or {}).get("canvas_node_id")): a
        for a in (project.assets or [])
        if a.type == "none" and (a.params or {}).get("canvas_node_id")
    }
    seen: set[str] = set()
    for node in body.nodes:
        nid = str(node.get("id") or "")
        if not nid:
            continue
        seen.add(nid)
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        name = str(data.get("label") or data.get("name") or f"节点 {nid}")
        url = data.get("mediaUrl") or data.get("url") or data.get("cover")
        kind = str(data.get("kind") or "none")
        asset_type = str(
            data.get("asset_type")
            or ("video" if kind == "video" else "audio" if kind == "audio" else "image")
        )
        # Prefer matching by explicit assetId, then by canvas_node_id
        asset_id_raw = data.get("assetId")
        matched = None
        if asset_id_raw is not None:
            try:
                aid = int(asset_id_raw)
            except (TypeError, ValueError):
                aid = None
            if aid is not None:
                matched = next((a for a in (project.assets or []) if a.id == aid), None)
        if matched is None:
            matched = existing.get(nid)

        if matched is not None:
            asset = matched
            asset.name = name
            if kind and kind != "none":
                asset.type = kind
            asset.asset_type = asset_type
            if url:
                asset.url = str(url)
                asset.cover = str(url)
            params = dict(asset.params or {})
            params["canvas"] = node
            params["canvas_node_id"] = nid
            asset.params = params
            existing[nid] = asset
        else:
            db.add(
                DramaAsset(
                    project_id=project.id,
                    type=kind if kind else "none",
                    asset_type=asset_type,
                    name=name,
                    cover=str(url) if url else None,
                    url=str(url) if url else None,
                    params={"canvas_node_id": nid, "canvas": node},
                )
            )
    await db.commit()
    return {"ok": True, "nodes": len(body.nodes), "edges": len(body.edges)}
