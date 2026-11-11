"""Project and drama write integrations used by Printfilm Studio Agent tools.

The Agent executor intentionally calls these functions instead of changing ORM
rows inline.  This keeps project validation and the write boundary in one
place, while preserving the existing drama data model and version fields.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models_drama import DramaEpisode, DramaEpisodeFragment, DramaScript
from app.services.drama.build_fragments import prepare_fragment_content
from app.services.teams.script_updates import locked_script, patch_episode_body


def _project_id(canvas: Any) -> int:
    project_id = int(getattr(getattr(canvas, "project", None), "id", 0) or 0)
    if project_id <= 0:
        raise ValueError("项目不存在")
    return project_id


async def update_script(canvas: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Update project script metadata or one episode body atomically.

    ``episode_number`` uses the same patch semantics as the public drama API;
    without it only project-level fields are accepted.  Unknown fields are
    ignored so a model can safely pass optional UI metadata.
    """

    db = canvas.db
    project_id = _project_id(canvas)
    episode_number = payload.get("episode_number")
    if episode_number is not None:
        try:
            number = int(episode_number)
        except (TypeError, ValueError):
            raise ValueError("无效的分集编号") from None
        if not 1 <= number <= 120:
            raise ValueError("无效的分集编号")
        patch = {
            key: payload[key]
            for key in ("title", "creative", "summary", "body", "version")
            if key in payload and payload[key] is not None
        }
        if not patch:
            raise ValueError("没有可更新的剧本字段")
        result = await patch_episode_body(db, project_id, number, patch)
        return {"ok": True, "episode_number": number, "script": result}

    fields = {key: payload[key] for key in ("source", "summary", "episode_content", "name") if key in payload}
    image_style_id = payload.get("image_style_id")
    if image_style_id is not None:
        fields["image_style_id"] = image_style_id
    if not fields:
        raise ValueError("没有可更新的剧本字段")
    script = await locked_script(db, project_id)
    if "source" in fields:
        script.source = str(fields["source"] or "")
    if "summary" in fields:
        summary = fields["summary"]
        if not isinstance(summary, dict):
            raise ValueError("summary 必须是对象")
        script.summary = summary
        series_title = str(summary.get("seriesTitle") or summary.get("title") or "").strip()
        if series_title:
            script.name = series_title[:200]
            canvas.project.title = series_title[:200]
    if "episode_content" in fields:
        content = fields["episode_content"]
        if not isinstance(content, (dict, list)):
            raise ValueError("episode_content 必须是对象或数组")
        script.episode_content = content
    if "name" in fields:
        script.name = str(fields["name"] or "剧本")[:200]
    if "image_style_id" in fields:
        style = str(fields["image_style_id"] or "").strip()
        script_params = dict(script.params or {})
        script_params["image_style_id"] = style
        script.params = script_params
        project_params = dict(canvas.project.params or {})
        project_params["image_style_id"] = style
        canvas.project.params = project_params
    await db.flush()
    return {
        "ok": True,
        "script": {
            "id": script.id,
            "name": script.name,
            "source": script.source or "",
            "summary": script.summary or {},
            "episode_content": script.episode_content or {},
        },
    }


async def update_shot(canvas: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Update a drama storyboard fragment belonging to the current project."""

    db = canvas.db
    project_id = _project_id(canvas)
    fragment_id = payload.get("fragment_id", payload.get("shot_id"))
    fragment: DramaEpisodeFragment | None = None
    if fragment_id is not None:
        try:
            fragment = await db.scalar(select(DramaEpisodeFragment).where(DramaEpisodeFragment.id == int(fragment_id)))
        except (TypeError, ValueError):
            raise ValueError("无效的分镜编号") from None
    else:
        episode_id = payload.get("episode_id")
        sort_order = payload.get("sort_order", payload.get("shot_no"))
        if episode_id is None or sort_order is None:
            raise ValueError("需要 fragment_id，或同时提供 episode_id 和 sort_order")
        try:
            fragment = await db.scalar(
                select(DramaEpisodeFragment).where(
                    DramaEpisodeFragment.episode_id == int(episode_id),
                    DramaEpisodeFragment.sort_order == int(sort_order),
                )
            )
        except (TypeError, ValueError):
            raise ValueError("无效的分集或镜头编号") from None
    if fragment is None:
        raise ValueError("分镜不存在")
    episode = await db.get(DramaEpisode, fragment.episode_id)
    if episode is None or int(episode.project_id) != project_id:
        raise ValueError("分镜不属于当前项目")
    changed = False
    if "content" in payload:
        fragment.content = prepare_fragment_content(str(payload.get("content") or ""), duration_sec=payload.get("duration_sec"), is_opening=int(fragment.sort_order or 0) == 0)
        changed = True
    for key in ("cover", "video"):
        if key in payload:
            setattr(fragment, key, str(payload.get(key) or "")[:1024])
            changed = True
    if "duration_sec" in payload:
        value = payload.get("duration_sec")
        fragment.duration_sec = int(value) if value is not None else None
        changed = True
    if "sort_order" in payload:
        fragment.sort_order = int(payload["sort_order"])
        changed = True
    if "params" in payload:
        if payload["params"] is not None and not isinstance(payload["params"], dict):
            raise ValueError("params 必须是对象")
        fragment.params = payload["params"]
        changed = True
    if not changed:
        raise ValueError("没有可更新的分镜字段")
    await db.flush()
    return {"ok": True, "shot": {"id": fragment.id, "episode_id": fragment.episode_id, "sort_order": fragment.sort_order, "content": fragment.content, "cover": fragment.cover, "video": fragment.video, "duration_sec": fragment.duration_sec, "params": fragment.params or {}}}


async def estimate_generation_price(canvas: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a read-only quote using the same media price rules as billing."""

    from app.config import get_settings
    from app.services.billing.pricing import charge_fen_for_tokens
    from app.services.media_models.prices import active_book, quote_items
    from app.services.tokenfree_pricing import charge_fen_official_image, charge_fen_official_video

    settings = get_settings()
    kind = str(payload.get("kind") or payload.get("media_type") or "image").strip().lower()
    if kind not in {"image", "video", "audio"}:
        raise ValueError("kind 必须是 image、video 或 audio")
    from app.printfilm_studio.agent.node_defaults import canvas_context
    preferred = (canvas_context(canvas).get("studio_node_defaults") or {}).get(kind)
    model = str(preferred or payload.get("model_id") or (settings.model_image if kind == "image" else settings.model_video if kind == "video" else settings.model_audio) or "").strip()
    count = max(1, min(int(payload.get("count") or 1), 100))
    resolution = str(payload.get("resolution") or payload.get("size") or ("2K" if kind == "image" else "720p")).strip()
    ratio = str(payload.get("ratio") or payload.get("aspect_ratio") or ("1:1" if kind == "image" else "9:16")).strip()
    duration = max(2, min(int(payload.get("duration") or payload.get("seconds") or 8), 30))
    if kind in {"image", "video"}:
        book = await active_book(canvas.db)
        if book:
            try:
                params: dict[str, Any] = {"prompt": str(payload.get("prompt") or ""), "resolution": resolution, "aspect_ratio": ratio, "count": count}
                if kind == "video":
                    from app.services.studio_generation import video_audio_enabled
                    params["generate_audio"] = video_audio_enabled(model, payload.get("generate_audio"))
                    params["duration"] = duration
                quote = quote_items([{"model_id": model, "params": params}], book)
                return {"ok": True, "kind": kind, "model_id": model, "price_version": quote.get("price_version"), "total_fen": quote["total_fen"], "total_yuan": round(quote["total_fen"] / 100, 2), "items": quote["items"]}
            except Exception:  # fall back to the same official-rate estimate used by task billing
                pass
        if kind == "image":
            total_fen = int(charge_fen_official_image(settings, model=model, size=resolution)) * count
        else:
            total_fen = int(charge_fen_official_video(float(duration), settings, model=model, resolution=resolution)) * count
    else:
        _, total_fen = charge_fen_for_tokens(max(int(getattr(settings, "billing_est_tts_tokens", 5000)), len(str(payload.get("prompt") or "")) * 20), "tts", settings=settings)
    return {"ok": True, "kind": kind, "model_id": model, "total_fen": max(1, int(total_fen)), "total_yuan": round(max(1, int(total_fen)) / 100, 2), "estimated": True}
