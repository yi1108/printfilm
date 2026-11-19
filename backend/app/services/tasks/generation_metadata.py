"""Credential-free generation parameters captured from immutable task evidence."""

from __future__ import annotations

import math
from urllib.parse import urlsplit

from app.schemas_tools import MAX_GENERATION_PROMPT_CHARS

PUBLIC_PARAMETERS = frozenset({
    "prompt", "negative", "negative_prompt", "model_id", "model", "ratio", "aspect_ratio", "resolution",
    "duration", "duration_sec", "seconds", "voice", "voice_id", "phase", "video_mode", "mode", "strength",
    "motion", "pack", "image_style_id", "episode_number", "generate_audio", "seed", "size", "count", "n",
    "watermark", "camera_fixed", "speaker",
})


def public_generation_params(data) -> dict:
    """Copy bounded public primitives, then normalize provider aliases without exposing references."""
    params = {key: value for key, value in (data.items() if isinstance(data, dict) else [])
              if key in PUBLIC_PARAMETERS and isinstance(value, (str, int, float, bool))
              and len(str(value)) <= (MAX_GENERATION_PROMPT_CHARS if key == "prompt" else 7000)
              and (not isinstance(value, float) or math.isfinite(value))}
    for canonical, aliases in (("model_id", ("model_id", "model")),
                               ("aspect_ratio", ("aspect_ratio", "ratio")),
                               ("duration", ("duration", "duration_sec", "seconds")),
                               ("count", ("count", "n")),
                               ("negative", ("negative", "negative_prompt"))):
        value = next((params[key] for key in aliases if params.get(key) not in (None, "")), None)
        if value is not None:
            params[canonical] = value
    return params


def submitted_generation_params(body) -> dict:
    """Project actual OpenAI/Seedance request bodies, including text-only content slots."""
    metadata = body.get("metadata") if isinstance(body, dict) else None
    dimensions = {key: metadata[key] for key in (
        "duration", "resolution", "ratio", "aspect_ratio", "generate_audio", "seed", "watermark", "return_last_frame",
        "camera_fixed", "speaker",
    ) if isinstance(metadata, dict) and key in metadata}
    params = merge_generation_params(dimensions, body)
    if isinstance(body, dict) and not params.get("prompt") and isinstance(body.get("content"), list):
        text = "\n\n".join(item["text"] for item in body["content"]
                           if isinstance(item, dict) and item.get("type") == "text"
                           and isinstance(item.get("text"), str))
        if text:
            params["prompt"] = text[:MAX_GENERATION_PROMPT_CHARS]
    if isinstance(body, dict) and not params.get("prompt") and isinstance(body.get("input"), str):
        params["prompt"] = body["input"][:7000]
    return params


def merge_generation_params(*sources) -> dict:
    """Merge oldest to newest evidence while keeping public aliases consistent."""
    params = {}
    for source in sources:
        params.update(public_generation_params(source))
    for canonical, aliases in (("model_id", ("model",)), ("aspect_ratio", ("ratio",)),
                               ("duration", ("duration_sec", "seconds")), ("count", ("n",))):
        if canonical in params:
            for alias in aliases:
                if alias in params:
                    params[alias] = params[canonical]
    return params


def prepared_generation_params(prepared) -> dict:
    """Retain final preparation parameters after the private request context is discarded."""
    if not isinstance(prepared, dict):
        return {}
    return merge_generation_params(prepared, submitted_generation_params(prepared.get("seedance_body")))


def planned_generation_params(task, kind: str) -> dict:
    """Use only a single matching operation; composite tasks have no one global parameter set."""
    snapshot = getattr(task, "billing_snapshot", None)
    items = snapshot.get("items", []) if isinstance(snapshot, dict) else []
    operations = [item for item in (items if isinstance(items, list) else [])
                  if isinstance(item, dict) and item.get("capability") == kind]
    if len(operations) != 1:
        return {}
    operation = operations[0]
    return merge_generation_params(operation.get("params"), {"model_id": operation.get("model_id")})


def saved_generation_references(task, kind: str) -> list[dict] | None:
    """Read one immutable generation's inputs, without resolving current asset URLs."""
    from app.services.tasks.generation_references import public_references

    result = task.result_payload if isinstance(task.result_payload, dict) else {}
    payload = task.payload if isinstance(task.payload, dict) else {}
    for value in (result.get("references"), payload.get("generation_references")):
        if isinstance(value, list):
            return public_references(value)
    prepared = payload.get("prepared")
    if isinstance(prepared, dict):
        return public_references(prepared)
    snapshot = getattr(task, "billing_snapshot", None)
    items = snapshot.get("items", []) if isinstance(snapshot, dict) else []
    operations = [item for item in (items if isinstance(items, list) else [])
                  if isinstance(item, dict) and item.get("capability") == kind]
    return public_references(operations[0].get("params")) if len(operations) == 1 else None


def request_matches_generation(kind: str, endpoint, *, is_video_submit=False) -> bool:
    """Ignore helper images and text calls when recovering a media task's submitted parameters."""
    if kind == "video":
        return bool(is_video_submit)
    if kind != "image" or not isinstance(endpoint, str):
        return False
    try:
        path = urlsplit(endpoint).path.rstrip("/")
    except ValueError:
        return False
    return path.endswith(("/images/generations", "/images/edits", "/responses"))
