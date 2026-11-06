"""漫剧整集到市场的显式快照发布。只读原漫剧，写入独立市场表。"""
from __future__ import annotations

import asyncio
import hashlib
import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import selectinload

from app.models_drama import DramaEpisode, DramaEpisodeFragment, DramaProject
from app.models_tasks import TaskRun
from app.services.drama.access import require_drama_project_access
from app.services.drama.project_cover import resolve_drama_project_cover
from .authorization import current as current_authorization
from .dependencies import Actor, DB, storage_ready
from .models import DramaPublishBatch, Handoff, Publication, Rights, Series, SeriesEpisode
from .schemas import DramaPublishEpisode, DramaPublishInput
from .service import ensure_kept, fail

router = APIRouter()
ACTIVE = ("pending", "leased", "running", "awaiting_poll", "awaiting_review")
BUSY = ("queued", "running", "generating", "pending", "leased")


def terminal_source_task(item) -> bool:
    return bool(item and item.status == "failed" and any(code in (item.error or "") for code in (
        "SOURCE_CHANGED", "TARGET_CHANGED", "SOURCE_INCOMPATIBLE", "重新选择分集")))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def episode_number(episode) -> int:
    try:
        return max(0, int((episode.params or {}).get("episodeNumber") or 0))
    except (ValueError, TypeError):
        return 0


async def owned_project(db, owner_id: int, project_id: int):
    project = await db.get(DramaProject, project_id)
    if not project or project.user_id != owner_id:
        fail("漫剧项目不存在或无权访问", 404)
    await require_drama_project_access(db, project, owner_id)
    return project


async def project_cover_snapshot(db, project_id: int, *, known_stamps=None) -> dict:
    """沿用漫剧项目卡片的封面来源，并冻结真实文件身份供市场独立转存。"""
    from .drama_media import source_stamp

    project = (await db.execute(select(DramaProject).where(DramaProject.id == project_id).options(
        selectinload(DramaProject.assets),
        selectinload(DramaProject.episodes).selectinload(DramaEpisode.fragments),
    ).execution_options(populate_existing=True))).scalar_one()
    locator, _ = resolve_drama_project_cover(project)
    if locator:
        try:
            stamp = (known_stamps or {}).get(locator)
            if stamp is None:
                stamp = await asyncio.to_thread(source_stamp, locator)
            return {"project_cover_locator": locator, "project_cover_stamp": stamp}
        except (HTTPException, ValueError, OSError):
            pass
    return {"project_cover_locator": "", "project_cover_stamp": None}


def snapshot_source_version(snapshot: dict, *, include_project_cover: bool = True) -> str:
    """按快照原协议计算来源版本，兼容升级前未包含项目封面的完整分集任务。"""
    from .drama_media import stamp_version

    cover_stamp = snapshot.get("cover_stamp")
    if not include_project_cover and not any(clip.get("cover") for clip in snapshot["clips"]):
        # 旧协议在没有分镜图片时留空，不将新增的视频首帧回退当作源文件变化。
        cover_stamp = None
    payload = {"episode": snapshot["drama_episode_id"], "title": snapshot["title"],
        "episode_number": snapshot["episode_number"], "updated_at": snapshot["episode_updated_at"],
        "cover_stamp": stamp_version(cover_stamp) if cover_stamp else None,
        "clips": [{"id": clip["id"], "sort_order": clip["sort_order"], "updated_at": clip["updated_at"],
                   "stamp": stamp_version(clip["stamp"]), "cover": clip["cover"]} for clip in snapshot["clips"]]}
    if include_project_cover:
        project_stamp = snapshot.get("project_cover_stamp")
        payload["project_cover_stamp"] = stamp_version(project_stamp) if project_stamp else None
    return digest(payload)


def source_matches(snapshot: dict, task: Handoff) -> bool:
    """只放宽新增封面协议字段，真实分镜与原分镜封面发生变化仍拒绝复用。"""
    return snapshot_source_version(snapshot, include_project_cover="project_cover_stamp" in (task.source_snapshot or {})) == task.source_version


async def episode_snapshot(db, owner_id: int, project_id: int, episode_id: int) -> dict:
    """服务端保存有序分镜与实际文件身份，不接受客户端传入视频地址。"""
    from .drama_media import source_stamp

    project = await owned_project(db, owner_id, project_id)
    episode = await db.get(DramaEpisode, episode_id)
    if not episode or episode.project_id != project.id:
        fail("存在不属于该漫剧项目的分集", 404)
    fragments = list((await db.execute(select(DramaEpisodeFragment).where(
        DramaEpisodeFragment.episode_id == episode.id
    ).order_by(DramaEpisodeFragment.sort_order, DramaEpisodeFragment.id))).scalars().all())
    active = (await db.execute(select(TaskRun.id).where(
        TaskRun.domain == "drama", TaskRun.task_type.in_(("fragment_video", "fragment_plan")),
        TaskRun.status.in_(ACTIVE),
        or_(TaskRun.episode_id == episode.id, TaskRun.fragment_id.in_([f.id for f in fragments])),
    ).limit(1))).scalar_one_or_none()
    if active or (episode.params or {}).get("fragment_plan_status") in BUSY:
        fail("MARKETPLACE_SOURCE_NOT_READY:分集正在生成视频或重新分镜，请完成后再发布", 409)
    if not fragments or any(not (fragment.video or "").strip() for fragment in fragments):
        fail("MARKETPLACE_SOURCE_NOT_READY:请先完成这一集的全部分镜视频", 409)
    clips = []
    for fragment in fragments:
        params = fragment.params or {}
        generation = params.get("generation") or params.get("video_gen") or params.get("video_generation") or {}
        if (isinstance(generation, dict) and generation.get("status") in BUSY) or params.get("video_status") in BUSY:
            fail("MARKETPLACE_SOURCE_NOT_READY:分镜视频仍在生成中", 409)
        locator = fragment.video.strip()
        try:
            stamp = await asyncio.to_thread(source_stamp, locator)
        except HTTPException:
            raise
        except (ValueError, OSError) as exc:
            fail(str(exc) if str(exc).startswith("MARKETPLACE_") else "MARKETPLACE_SOURCE_NOT_READY:源视频不可用", 409)
        clips.append({"id": fragment.id, "sort_order": fragment.sort_order, "locator": locator,
                      "stamp": stamp, "updated_at": fragment.updated_at.isoformat(),
                      "cover": fragment.cover or ""})
    known_stamps = {clip["locator"]: clip["stamp"] for clip in clips}
    project_cover = await project_cover_snapshot(db, project.id, known_stamps=known_stamps)
    if project_cover["project_cover_stamp"]:
        known_stamps[project_cover["project_cover_locator"]] = project_cover["project_cover_stamp"]
    snapshot = {"schema_version": 2, "drama_project_id": project.id, "drama_episode_id": episode.id,
                "episode_number": episode_number(episode), "title": episode.name,
                "episode_updated_at": episode.updated_at.isoformat(), "clips": clips,
                **project_cover,
                "cover_locator": next((clip["cover"] for clip in clips if clip["cover"]), "")
                    or project_cover["project_cover_locator"]}
    snapshot["cover_stamp"] = None
    if snapshot["cover_locator"]:
        try:
            snapshot["cover_stamp"] = known_stamps.get(snapshot["cover_locator"])
            if snapshot["cover_stamp"] is None:
                snapshot["cover_stamp"] = await asyncio.to_thread(source_stamp, snapshot["cover_locator"])
        except (HTTPException, ValueError, OSError):
            # A missing cover never selects an unrelated material. The editor asks for one.
            snapshot["cover_locator"] = ""
    snapshot["source_version"] = snapshot_source_version(snapshot)
    return snapshot


async def episode_context(db, owner_id: int, project_id: int, episode, *, source_versions=None) -> dict:
    fragments = list((await db.execute(select(DramaEpisodeFragment).where(DramaEpisodeFragment.episode_id == episode.id))).scalars().all())
    result = {"id": episode.id, "name": episode.name, "episode_number": episode_number(episode),
              "fragment_count": len(fragments), "completed_count": sum(bool((f.video or "").strip()) for f in fragments),
              "ready": False, "reason": "", "source_version": ""}
    try:
        snapshot = await episode_snapshot(db, owner_id, project_id, episode.id)
        result.update(ready=True, source_version=snapshot["source_version"])
        if source_versions is not None:
            source_versions[episode.id] = (snapshot["source_version"], snapshot_source_version(snapshot, include_project_cover=False))
    except HTTPException as exc:
        from .locale_messages import error_message
        error = error_message(str(exc.detail), exc.status_code)[1]
        result.update(reason=f"{error['code']}:{error['message']}",
                      reason_code=error["code"], reason_label=error["message"])
    return result


@router.get(
    "/printfilm/dramas/{project_id}/publish-context", response_model=dict,
    summary='获取漫剧发布到市场的上下文',
    description='仅有权操作源漫剧项目的登录用户可访问。返回分集来源版本、可用目标系列和已有导入映射，同时报告授权函与存储配置状态，供发布前明确选择和确认更新。',
    response_description='项目 project、分集 episodes、目标系列 series、授权与存储状态。',
)
async def publish_context(project_id: int, db: DB, user: Actor):
    from .storage import configured
    project = await owned_project(db, user.id, project_id)
    episodes = list((await db.execute(select(DramaEpisode).where(DramaEpisode.project_id == project.id))).scalars().all())
    episodes.sort(key=lambda row: (episode_number(row), row.id))
    source_versions = {}
    episode_items = [await episode_context(db, user.id, project.id, episode, source_versions=source_versions) for episode in episodes]
    targets = list((await db.execute(select(Series).where(Series.owner_id == user.id,
        Series.deleted_at.is_(None), Series.blocked.is_(False)).order_by(Series.id.desc()))).scalars().all())
    series_items = []
    for target in targets:
        imported = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == target.id))).scalars().all())
        mappings = []
        for episode in imported:
            mapping = episode.source_snapshot or {}
            if mapping.get("source_kind") != "drama_episode":
                continue
            handoff_id = mapping.get("pending_handoff_id") or mapping.get("last_handoff_id")
            handoff = await db.get(Handoff, handoff_id) if handoff_id else (await db.execute(select(Handoff).where(
                Handoff.target_kind == "series_episode", Handoff.target_id == episode.id,
                Handoff.source_kind == "drama_episode").order_by(Handoff.id.desc()).limit(1))).scalar_one_or_none()
            frozen = (handoff.source_snapshot or {}) if handoff else {}
            reusable = bool(handoff and not terminal_source_task(handoff) and frozen.get("schema_version") == 2 and (
                (handoff.status == "ready" and handoff.asset_id == episode.asset_id and mapping.get("last_handoff_id") == handoff.id)
                or (handoff.status in ("pending", "running", "failed") and mapping.get("pending_handoff_id") == handoff.id
                    and frozen.get("target_version") == episode.version and frozen.get("original_asset_id") == episode.asset_id)))
            source_id = mapping.get("drama_episode_id") or mapping.get("source_id")
            version = handoff.source_version if handoff else mapping.get("imported_source_version", "")
            current_versions = source_versions.get(source_id)
            if (reusable and current_versions and "project_cover_stamp" not in frozen and version == current_versions[1]):
                # 向选择弹窗返回可比较的新协议版本，不改写原任务、源快照或已购买发布记录。
                version = current_versions[0]
            mappings.append({"source_episode_id": source_id,
                "episode_id": episode.id, "source_version": version,
                "status": handoff.status if handoff else "legacy", "handoff_id": handoff.id if handoff else None,
                "requires_update": not reusable})
        series_items.append({"id": target.id, "title": target.title, "version": target.version,
                             "series_version": target.version, "listed": target.listed,
                             "audit_status": target.audit_status, "imports": mappings})
    return {"project": {"id": project.id, "title": project.title, "description": project.description or ""},
            "episodes": episode_items,
            "series": series_items, "authorization_ready": bool(await current_authorization(db, user.id)),
            "storage_configured": configured()}


async def pause_sales(db, series):
    ids = select(SeriesEpisode.id).where(SeriesEpisode.series_id == series.id)
    await db.execute(update(Publication).where(Publication.content_type == "series_episode", Publication.content_id.in_(ids)).values(listed=False))
    await db.execute(update(SeriesEpisode).where(SeriesEpisode.series_id == series.id).values(listed=False))
    series.audit_status, series.listed, series.reason = "draft", False, ""


async def ensure_import_rights(db, episode):
    """PrintFilm 分集统一关联账号授权；材料关联绝不等于审核通过。"""
    if episode.source != "printfilm" or not episode.asset_id:
        return
    mapping = episode.source_snapshot or {}
    if episode.source_type == "drama_import":
        if not mapping.get("last_handoff_id"):
            return
        handoff = await db.get(Handoff, mapping["last_handoff_id"])
        if not handoff or handoff.status != "ready" or handoff.asset_id != episode.asset_id or handoff.owner_id != episode.owner_id:
            return
    authorization = await current_authorization(db, episode.owner_id)
    if not authorization:
        return
    rights = (await db.execute(select(Rights).where(Rights.asset_id == episode.asset_id).with_for_update())).scalar_one_or_none()
    if rights and (rights.blocked or str(rights.details.get("authorization_id")) == str(authorization.id)):
        return
    values = {"source": "printfilm", "authorization_id": str(authorization.id),
              "authorization_version": authorization.template_version, "scope": "数字资产市场展示、撮合及经审核的平台投放"}
    if rights is None:
        db.add(Rights(owner_id=episode.owner_id, asset_id=episode.asset_id, details=values))
    else:
        rights.details = values
        rights.version += 1
        rights.basic_status = rights.full_status = "draft"


async def batch_result(db, batch):
    from .handoff import _view
    from .series import _episode_data
    episodes = [await db.get(SeriesEpisode, item_id) for item_id in batch.episode_ids]
    tasks = [await db.get(Handoff, item_id) for item_id in batch.handoff_ids]
    return {"series_id": batch.series_id, "items": [await _episode_data(db, item, private=True) for item in episodes if item],
            "handoffs": [await _view(db, item) for item in tasks if item]}


async def publish_selected(project_id: int, body: DramaPublishInput, db, user):
    from .handoff import _category
    # A transaction lock serializes retries even when creating a brand new series.
    # It doesn't update any upstream user or drama record.
    request_hash = digest({"project_id": project_id, **body.model_dump(exclude={"idempotency_key"})})
    lock_id = int(digest([user.id, body.idempotency_key])[:16], 16)
    if lock_id >= 2**63:
        lock_id -= 2**64
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
    existing = (await db.execute(select(DramaPublishBatch).where(DramaPublishBatch.owner_id == user.id,
        DramaPublishBatch.idempotency_key == body.idempotency_key))).scalar_one_or_none()
    if existing:
        if existing.request_hash != request_hash:
            fail("MARKETPLACE_TARGET_CHANGED:此请求编号已用于其他发布内容", 409)
        return await batch_result(db, existing)
    await storage_ready()  # Must precede all series/episode/task writes.
    project = await owned_project(db, user.id, project_id)
    snapshots = []
    for selected in body.episodes:
        snapshot = await episode_snapshot(db, user.id, project.id, selected.episode_id)
        if selected.source_version != snapshot["source_version"]:
            fail("MARKETPLACE_SOURCE_CHANGED:分集内容已变化，请刷新并重新选择", 409)
        snapshots.append((snapshot, selected.update))
    snapshots.sort(key=lambda entry: (entry[0]["episode_number"], entry[0]["drama_episode_id"]))
    if body.series_id:
        series = (await db.execute(select(Series).where(Series.id == body.series_id).with_for_update())).scalar_one_or_none()
        if not series or series.owner_id != user.id:
            fail("系列不存在或无权访问", 404)
        ensure_kept(series)
        if series.blocked:
            fail("MARKETPLACE_TARGET_CHANGED:系列已封禁", 409)
        stale_target = body.series_version is not None and series.version != body.series_version
    else:
        series = Series(owner_id=user.id, title=(body.title or project.title or "未命名短剧")[:200],
            description=(project.description or "")[:5000], category=await _category(db, "短剧"), sale_type="copyright_contact")
        from .categories import resolve_category
        series.category, series.category_code = await resolve_category(db, series.category)
        db.add(series)
        await db.flush()
        stale_target = False
    episodes = list((await db.execute(select(SeriesEpisode).where(SeriesEpisode.series_id == series.id)
        .order_by(SeriesEpisode.episode_no).with_for_update())).scalars().all())
    next_no = max((episode.episode_no for episode in episodes), default=0) + 1
    targets, tasks = [], []
    changed = False
    for snapshot, confirmed_update in snapshots:
        source_id = snapshot["drama_episode_id"]
        target = next((row for row in episodes if (row.source_snapshot or {}).get("source_kind") == "drama_episode"
            and ((row.source_snapshot or {}).get("drama_episode_id") or (row.source_snapshot or {}).get("source_id")) == source_id), None)
        previous = (await db.execute(select(Handoff).where(Handoff.owner_id == user.id,
            Handoff.series_id == series.id, Handoff.target_id == target.id,
            Handoff.source_kind == "drama_episode", Handoff.source_id == source_id)
            .order_by(Handoff.id.desc()).limit(1))).scalar_one_or_none() if target else None
        previous_snapshot = previous.source_snapshot or {} if previous else {}
        mapping = target.source_snapshot or {} if target else {}
        previous_matches = bool(previous and not terminal_source_task(previous) and ((previous.status == "ready" and previous.asset_id == target.asset_id
                and mapping.get("last_handoff_id") == previous.id)
            or (previous.status in ("pending", "running", "failed") and previous_snapshot.get("target_version") == target.version
                and previous_snapshot.get("original_asset_id") == target.asset_id and mapping.get("pending_handoff_id") == previous.id)))
        if previous_matches and source_matches(snapshot, previous) and previous_snapshot.get("schema_version") == 2:
            targets.append(target)
            tasks.append(previous)
            continue
        if target and not confirmed_update:
            fail("MARKETPLACE_SOURCE_CHANGED:发现新版本或旧版导入记录，请明确确认更新", 409)
        if target and target.blocked:
            fail("MARKETPLACE_TARGET_CHANGED:该分集已封禁", 409)
        if stale_target:
            fail("MARKETPLACE_TARGET_CHANGED:市场系列已修改，请刷新后重试", 409)
        if previous and previous.status in ("pending", "running"):
            previous.status, previous.error = "failed", "MARKETPLACE_TARGET_CHANGED:已有新的同步任务，请查看最新进度"
            previous.lease_token, previous.lease_until = None, None
        if target:
            target.version += 1
            target.audit_status, target.listed, target.reason = "draft", False, ""
            target.preview_status, target.playback_status = "none", "none"
        else:
            target = SeriesEpisode(series_id=series.id, owner_id=user.id, episode_no=next_no,
                title=(snapshot["title"] or f"第{next_no}集")[:200], source="printfilm", source_type="drama_import")
            next_no += 1
            db.add(target)
            await db.flush()
            episodes.append(target)
        # A new request can supersede a prior failed/running task, never its output.
        task = Handoff(owner_id=user.id, idempotency_key=digest(["drama", series.id, target.id, target.version, body.idempotency_key]),
            source_kind="drama_episode", source_id=source_id, source_version=snapshot["source_version"],
            target_kind="series_episode", target_id=target.id, series_id=series.id, status="pending",
            source_snapshot={**snapshot, "phase": "queued", "target_version": target.version,
                             "original_asset_id": target.asset_id,
                             "inherit_series_cover": not bool(body.series_id),
                             "series_cover_version": series.version + 1})
        db.add(task)
        await db.flush()
        target.source = "printfilm"
        target.source_snapshot = {"source_kind": "drama_episode", "source_id": source_id,
            "drama_project_id": project.id, "drama_episode_id": source_id, "source_title": snapshot["title"],
            "source_episode_number": snapshot["episode_number"], "pending_handoff_id": task.id,
            "last_handoff_id": (target.source_snapshot or {}).get("last_handoff_id"),
            "imported_source_version": (target.source_snapshot or {}).get("imported_source_version", "")}
        targets.append(target)
        tasks.append(task)
        changed = True
    if changed:
        series.version += 1
        await pause_sales(db, series)
    batch = DramaPublishBatch(owner_id=user.id, idempotency_key=body.idempotency_key,
        request_hash=request_hash, series_id=series.id, episode_ids=[row.id for row in targets], handoff_ids=[row.id for row in tasks])
    db.add(batch)
    await db.commit()
    return await batch_result(db, batch)


@router.post(
    "/printfilm/dramas/{project_id}/publish", response_model=dict,
    summary='将选中漫剧分集同步到市场草稿',
    description='仅有权操作源项目和目标系列的用户可操作。按选定来源版本冻结分集内容，创建或复用草稿与异步转存任务；已有分集更新须明确确认。幂等键绑定请求内容，来源或目标版本冲突返回 409；请求本身不等待长视频转存。',
    response_description='series_id、目标分集草稿 items 与异步转存任务 handoffs。',
)
async def publish(project_id: int, body: DramaPublishInput, db: DB, user: Actor):
    return await publish_selected(project_id, body, db, user)


async def legacy_import(series_id: int, body, db, user):
    """兼容旧 URL；依然验证整集，绝不选择最后一个镜头。"""
    await storage_ready()
    snapshots = [await episode_snapshot(db, user.id, body.drama_project_id, episode_id) for episode_id in dict.fromkeys(body.episode_ids)]
    key = body.idempotency_key.strip() or digest(["legacy", series_id, [(s["drama_episode_id"], s["source_version"]) for s in snapshots]])
    payload = DramaPublishInput(series_id=series_id, idempotency_key=key,
        episodes=[DramaPublishEpisode(episode_id=s["drama_episode_id"], source_version=s["source_version"],
            update=s["drama_episode_id"] in body.update_episode_ids) for s in snapshots])
    return await publish_selected(body.drama_project_id, payload, db, user)
