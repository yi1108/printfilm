"""Toonflow-compatible canvas codec used only at the Printfilm Studio boundary."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

SUPPORTED_NODE_TYPES = {"text", "image", "video", "audio", "script", "asset", "task", "group"}


def _as_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("canvas document must be an object")
    return deepcopy(value)


def _coordinate(value: Any) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError('canvas coordinates must be finite')
    return number


def decode_canvas_document(raw: Any) -> dict[str, Any]:
    """Normalize a document without dropping unknown fields for forward compatibility."""
    document = _as_dict(raw)
    if "version" not in document:
        document["version"] = 1
    if document["version"] != 1:
        raise ValueError("unsupported canvas document version")
    if "toonflowCanvas" in document and document["toonflowCanvas"] is not True:
        raise ValueError("toonflowCanvas must be true when provided")
    document["toonflowCanvas"] = True
    nodes = document.get("nodes", [])
    edges = document.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("nodes and edges must be arrays")
    node_ids: set[str] = set()
    normalized_nodes: list[dict[str, Any]] = []
    for raw_node in nodes:
        node = _as_dict(raw_node)
        node_id = str(node.get("id") or "").strip()
        if not node_id or node_id in node_ids:
            raise ValueError("node id is required and must be unique")
        node_ids.add(node_id)
        node["id"] = node_id
        node["type"] = str(node.get("type") or "text")
        if not isinstance(node.get("data"), dict):
            node["data"] = {}
        position = node.get("position")
        if not isinstance(position, dict):
            node["position"] = {"x": 0, "y": 0}
        else:
            node["position"] = {**position, "x": _coordinate(position.get("x", 0)), "y": _coordinate(position.get("y", 0))}
        normalized_nodes.append(node)
    normalized_edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()
    for raw_edge in edges:
        edge = _as_dict(raw_edge)
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if not source or not target or source not in node_ids or target not in node_ids:
            raise ValueError("edge source and target must reference existing nodes")
        edge["id"] = str(edge.get("id") or f"{source}->{target}")
        if source == target or edge['id'] in edge_ids:
            raise ValueError('edge must have a unique id and distinct endpoints')
        edge_ids.add(edge['id'])
        edge["source"], edge["target"] = source, target
        normalized_edges.append(edge)
    viewport = document.get("viewport")
    if not isinstance(viewport, dict):
        viewport = {}
    document["nodes"] = normalized_nodes
    document["edges"] = normalized_edges
    document["viewport"] = {
        **viewport,
        "x": _coordinate(viewport.get("x", 0)),
        "y": _coordinate(viewport.get("y", 0)),
        "zoom": max(0.05, min(4.0, _coordinate(viewport.get("zoom", 1)))),
    }
    return document


def encode_canvas_document(document: Any) -> dict[str, Any]:
    """Validate and copy a document before persistence or API output."""
    return decode_canvas_document(document)
