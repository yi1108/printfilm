"""Explicit, non-destructive legacy canvas migration. No generation or asset writes."""
from __future__ import annotations

from copy import deepcopy
from collections import defaultdict
from hashlib import sha256
import json
import uuid

from sqlalchemy import insert, select, update

from app.models_drama import DramaAsset, DramaProject
from app.models_printfilm_studio import PrintfilmStudioCanvasDocument
from .codec import decode_canvas_document

MIGRATION = "legacy_canvas_v1"
CONVERTER_VERSION = 2
PROJECT = DramaProject.__table__
ASSET = DramaAsset.__table__
CANVAS = PrintfilmStudioCanvasDocument.__table__


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def repair_duplicate_nodes(nodes, repairs):
    """Keep the last occurrence under the original ID, as the legacy renderer did.

    Equal normalized snapshots share that node; distinct variants get stable IDs.
    Neither the input nor its source rows are changed. Original edge endpoints
    continue to point at the last occurrence rather than an arbitrary variant.
    """
    groups = defaultdict(list)
    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise ValueError("node id is required; cannot infer missing identifiers")
        node["id"] = node_id
        groups[node_id].append(index)
    reserved = set(groups)
    removed = set()
    for node_id, indices in groups.items():
        if len(indices) < 2:
            continue
        canonical_index = indices[-1]
        variants = {fingerprint(nodes[canonical_index]): (node_id, canonical_index)}
        for index in reversed(indices[:-1]):
            node = nodes[index]
            key = fingerprint(node)
            if key in variants:
                target_id, target_index = variants[key]
                removed.add(index)
                repairs.append({"kind": "duplicate_node_collapsed", "source_index": index, "node_id": node_id, "target_id": target_id, "target_source_index": target_index})
                continue
            suffix = 1
            new_id = f"{node_id}--legacy-{index + 1}"
            while new_id in reserved:
                new_id = f"{node_id}--legacy-{index + 1}-{suffix}"
                suffix += 1
            reserved.add(new_id)
            variants[key] = (new_id, index)
            node["id"] = new_id
            node["data"]["legacyNodeId"] = node_id
            node["data"]["legacySourceIndex"] = index
            repairs.append({"kind": "duplicate_node_renamed", "source_index": index, "node_id": node_id, "target_id": new_id, "edge_target_source_index": canonical_index})
    return [node for index, node in enumerate(nodes) if index not in removed]


def convert_legacy_canvas(content, assets, *, repair_legacy=False, missing_asset_ids=frozenset()):
    """Preserve graph IDs/layout/extensions, resolve media from project-owned assets."""
    content = content if isinstance(content, dict) else {}
    raw_nodes = content.get("canvas_nodes", [])
    raw_edges = content.get("canvas_edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("legacy nodes and edges must be arrays")
    by_id = {a["id"]: a for a in assets}
    by_node = {}
    for asset in assets:
        key = (asset.get("params") or {}).get("canvas_node_id")
        if key:
            by_node.setdefault(str(key), []).append(asset)
    nodes, repairs = [], []
    for index, raw in enumerate(raw_nodes):
        node = deepcopy(raw)
        if not isinstance(node, dict) or not isinstance(node.get("data", {}), dict):
            raise ValueError("invalid legacy node")
        data = node.setdefault("data", {})
        if "position" not in node:
            node["position"] = {"x": node.get("x", 0), "y": node.get("y", 0)}
        if node.get("label") and not data.get("label"):
            data["label"] = node["label"]
        asset = None
        if data.get("assetId") is not None:
            raw_id = data["assetId"]
            if isinstance(raw_id, bool) or not str(raw_id).isdigit():
                raise ValueError(f"node {node.get('id')}: invalid asset ID")
            asset = by_id.get(int(raw_id))
            if asset is None:
                if not repair_legacy or int(raw_id) not in missing_asset_ids:
                    raise ValueError(f"node {node.get('id')}: asset missing or belongs to another project")
                # Only detach IDs confirmed absent from the entire assets table.
                # Never resolve/copy another project's asset or invent missing media.
                data.pop("assetId")
                data["legacyMissingAssetId"] = int(raw_id)
                repairs.append({"kind": "missing_asset_detached", "source_index": index, "node_id": node.get("id"), "asset_id": int(raw_id), "has_media_snapshot": bool(data.get("mediaUrl") or data.get("url") or data.get("cover"))})
        else:
            matches = by_node.get(str(node.get("id")), [])
            if len(matches) > 1:
                raise ValueError(f"node {node.get('id')}: ambiguous asset association")
            asset = matches[0] if matches else None
        params = (asset.get("params") or {}) if asset else {}
        kind = data.get("kind") or (asset.get("asset_type") if asset else None) or node.get("type")
        if kind in {"character", "scene", "prop", "image", "asset", "none"}:
            kind = "image"
        if kind in {"voice", "voiceover"}:
            kind = "audio"
        if kind not in {"image", "video", "audio", "text", "group"}:
            raise ValueError(f"node {node.get('id')}: unsupported legacy kind {kind}")
        node["type"] = kind
        data["mediaType"] = kind
        data.setdefault("legacyKind", (raw.get("data") or {}).get("kind"))
        data.setdefault("label", (asset.get("name") if asset else None) or "节点")
        if asset:
            data.update(assetId=asset["id"], mediaUrl=asset.get("url"), url=asset.get("url"), cover=asset.get("cover"), asset_type=asset.get("asset_type"))
        prompt = data.get("prompt") or data.get("promptHint") or params.get("prompt") or params.get("visualPrompt") or ""
        data["prompt"] = prompt
        if kind == "text":
            data["text"] = data.get("text") or data.get("textContent") or params.get("textContent") or prompt
        option_key = "videoOptions" if kind == "video" else "imageOptions"
        options = data.get(option_key) or params.get(option_key) or {}
        if not isinstance(options, dict):
            raise ValueError(f"node {node.get('id')}: invalid generation options")
        for old_key, new_key in (("model_id", "modelId"), ("aspect_ratio", "ratio"), ("resolution", "resolution"), ("duration_sec", "duration"), ("duration", "duration"), ("generate_audio", "generateAudio")):
            value = options.get(old_key, params.get(old_key))
            if value is not None:
                data.setdefault(new_key, value)
        # An old UI snapshot is not a live job. Never resume generation on import.
        data["generating"] = False
        for key in ("selected", "dragging", "resizing"):
            node.pop(key, None)
        nodes.append(node)
    if repair_legacy:
        nodes = repair_duplicate_nodes(nodes, repairs)
    document = decode_canvas_document({"nodes": nodes, "edges": deepcopy(raw_edges), "viewport": content.get("canvas_viewport") or {"x": 0, "y": 0, "zoom": 1}})
    if repairs:
        document["legacyRepairs"] = repairs
    return document


async def migrate_project(db, project_id, *, apply=False, write_backup=None, repair_legacy=False):
    """Caller owns transaction. Lock in the same project -> document order as saves."""
    query = select(PROJECT).where(PROJECT.c.id == project_id)
    if apply:
        query = query.with_for_update()
    project = (await db.execute(query)).mappings().one_or_none()
    if project is None:
        raise ValueError(f"project {project_id} does not exist")
    query = select(CANVAS).where(CANVAS.c.project_id == project_id)
    if apply:
        query = query.with_for_update()
    target = (await db.execute(query)).mappings().one_or_none()
    current = target["document"] if target else {}
    if not isinstance(current, dict):
        raise ValueError("target canvas must be an object")
    report = {"project_id": project_id, "target_version": target["document_version"] if target else None, "target_hash": fingerprint(current) if target else None}
    marker = current.get("legacyMigration") or {}
    if isinstance(marker, dict) and marker.get("name") == MIGRATION:
        return {**report, "status": "already_migrated"}
    if current.get("nodes") or current.get("edges"):
        return {**report, "status": "skipped_nonempty_target"}
    assets = [dict(a) for a in (await db.execute(select(ASSET).where(ASSET.c.project_id == project_id).order_by(ASSET.c.id))).mappings()]
    content = project["content"] if isinstance(project["content"], dict) else {}
    referenced = {int(n["data"]["assetId"]) for n in content.get("canvas_nodes", [])
                  if isinstance(n, dict) and isinstance(n.get("data"), dict)
                  and str(n["data"].get("assetId", "")).isdigit()}
    missing = referenced - {a["id"] for a in assets}
    if repair_legacy and missing:
        # The absence check also prevents silently importing another owner's media.
        existing = set((await db.scalars(select(ASSET.c.id).where(ASSET.c.id.in_(missing)))).all())
        missing -= existing
    document = convert_legacy_canvas(project["content"], assets, repair_legacy=repair_legacy, missing_asset_ids=missing)
    if not document["nodes"]:
        return {**report, "status": "no_legacy_nodes"}
    document = {**deepcopy(current), **document}
    repairs = document.pop("legacyRepairs", [])
    document["legacyMigration"] = {"name": MIGRATION, "converterVersion": CONVERTER_VERSION, "projectId": project_id, "sourceHash": fingerprint(project["content"]), "repairs": repairs}
    report.update(source_nodes=len(content.get("canvas_nodes", [])), nodes=len(document["nodes"]), edges=len(document["edges"]), repairs=repairs, linked_assets=len({n["data"]["assetId"] for n in document["nodes"] if n["data"].get("assetId")}))
    if not apply:
        return {**report, "status": "ready"}
    if write_backup is None:
        raise ValueError("apply requires a backup writer")
    version = target["document_version"] + 1 if target else 1
    backup = {"migration": MIGRATION, "converter_version": CONVERTER_VERSION, "project_id": project_id, "source_content": project["content"], "source_assets": assets, "previous_document": dict(target) if target else None, "applied_version": version, "applied_hash": fingerprint(document), "repairs": repairs}
    backup_path = write_backup(backup)
    values = dict(document=document, document_version=version, updated_by=project["user_id"])
    if target:
        result = await db.execute(update(CANVAS).where(CANVAS.c.id == target["id"], CANVAS.c.document_version == target["document_version"]).values(**values))
        if result.rowcount != 1:
            raise ValueError("canvas changed during migration")
    else:
        await db.execute(insert(CANVAS).values(id=str(uuid.uuid4()), project_id=project_id, team_id=project["team_id"], created_by=project["user_id"], **values))
    return {**report, "status": "migrated", "target_version": version, "target_hash": fingerprint(document), "backup": str(backup_path)}


async def verify_backup(db, backup):
    """Read-only post-deployment check of source, asset rows and target snapshot."""
    if backup.get("migration") != MIGRATION:
        raise ValueError("not a legacy canvas migration backup")
    project_id = backup["project_id"]
    project = (await db.execute(select(PROJECT).where(PROJECT.c.id == project_id))).mappings().one_or_none()
    assets = [dict(a) for a in (await db.execute(select(ASSET).where(ASSET.c.project_id == project_id).order_by(ASSET.c.id))).mappings()]
    target = (await db.execute(select(CANVAS).where(CANVAS.c.project_id == project_id))).mappings().one_or_none()
    checks = {
        "legacy_unchanged": project is not None and project["content"] == backup["source_content"],
        "assets_unchanged": json.loads(json.dumps(assets, default=str)) == json.loads(json.dumps(backup["source_assets"], default=str)),
        "target_matches": target is not None and fingerprint(target["document"]) == backup["applied_hash"],
        "version_matches": target is not None and target["document_version"] == backup["applied_version"],
    }
    return {"project_id": project_id, "status": "verified" if all(checks.values()) else "verification_failed", **checks}


async def restore_project(db, backup):
    """Forward restore: refuse if users have edited since migration; advance version."""
    if backup.get("migration") != MIGRATION:
        raise ValueError("not a legacy canvas migration backup")
    project_id = backup["project_id"]
    await db.execute(select(PROJECT.c.id).where(PROJECT.c.id == project_id).with_for_update())
    current = (await db.execute(select(CANVAS).where(CANVAS.c.project_id == project_id).with_for_update())).mappings().one()
    if current["document_version"] != backup["applied_version"] or fingerprint(current["document"]) != backup["applied_hash"]:
        raise ValueError("canvas has changed since migration; refusing restore")
    previous = backup["previous_document"]
    document = previous["document"] if previous else decode_canvas_document({})
    await db.execute(update(CANVAS).where(CANVAS.c.id == current["id"]).values(document=document, document_version=current["document_version"] + 1, updated_by=previous["updated_by"] if previous else current["updated_by"]))
    return {"project_id": project_id, "status": "restored", "target_version": current["document_version"] + 1}
