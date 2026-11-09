"""App 点赞、收藏、评论和举报接口。"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from .app_access import error, require_app_open, require_social_open, current_content
from .app_models import AuthorBlock
from .app_engagement import insert_once, lock_stats, totals
from .dependencies import Actor, DB, Visitor
from .models import Series, SeriesEpisode, Work
from .app_social_models import AppComment, AppCommentAction, AppCommentReport, AppContentStats, AppFavorite, AppLike, AppSocialSetting

from .app_response import AppJSONResponse

router = APIRouter(default_response_class=AppJSONResponse)
TargetType = Literal["work", "works", "series", "episode", "episodes", "series_episode"]
MAX_COMMENT_DEPTH = 5


class CommentInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    parent_id: int | None = Field(default=None, gt=0)


class ReportInput(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class SocialSettingInput(BaseModel):
    comments_enabled: bool


def _kind(target_type: str) -> str:
    if target_type in ("episode", "episodes", "series_episode"):
        return "series_episode"
    return "work" if target_type == "works" else target_type


def _stored_type(target_type: str) -> str:
    return "episode" if target_type in ("episode", "episodes", "series_episode") else "work" if target_type == "works" else target_type


async def _target(db, target_type: str, target_id: int, user_id=None):
    kind = _kind(target_type)
    if kind == "work":
        return kind, (await current_content(db, kind, target_id, user_id))[0]
    if kind == "series":
        item = await db.scalar(select(Series).where(Series.id == target_id))
        if not item:
            error("MARKETPLACE_CONTENT_UNAVAILABLE", "内容不存在或暂不可访问", 404)
        from .app_access import series_query
        if not await db.scalar(series_query(user_id).where(Series.id == target_id)):
            error("MARKETPLACE_CONTENT_UNAVAILABLE", "内容不存在或暂不可访问", 404)
        return kind, item
    item = await db.get(SeriesEpisode, target_id)
    if not item:
        error("MARKETPLACE_CONTENT_UNAVAILABLE", "内容不存在或暂不可访问", 404)
    await current_content(db, "series_episode", target_id, user_id)
    return kind, item


async def _stats(db, target_type: str, target_id: int, user_id=None):
    target_type = _stored_type(target_type)
    row = await db.scalar(select(AppContentStats).where(AppContentStats.target_type == target_type, AppContentStats.target_id == target_id))
    combined = await totals(db, target_type, target_id, row)
    likes = bool(user_id and await db.scalar(select(AppLike.id).where(AppLike.user_id == user_id, AppLike.target_type == target_type, AppLike.target_id == target_id)))
    favorites = bool(user_id and await db.scalar(select(AppFavorite.id).where(AppFavorite.user_id == user_id, AppFavorite.target_type == target_type, AppFavorite.target_id == target_id)))
    settings = await db.scalar(select(AppSocialSetting).where(AppSocialSetting.target_type == target_type, AppSocialSetting.target_id == target_id))
    from .app_settings import get_app_settings
    global_comments = bool(get_app_settings().comments_enabled)
    return {**combined, "comment_count": row.comment_count if row else 0, "liked_by_me": likes,
            "favorited_by_me": favorites, "comments_enabled": bool(global_comments and (settings.comments_enabled if settings else True))}


async def _mutate(db, user, target_type: str, target_id: int, model, enabled: bool):
    stored = _stored_type(target_type)
    await _target(db, stored, target_id, user.id)
    # Writers lock the stable per-target row before changing any detail record.
    stats = await lock_stats(db, stored, target_id)
    existing = await db.scalar(select(model).where(model.user_id == user.id,
        model.target_type == stored, model.target_id == target_id).with_for_update())
    attribute = "like_count" if model is AppLike else "favorite_count"
    if enabled and not existing:
        inserted = await insert_once(db, model, {"user_id": user.id, "target_type": stored,
            "target_id": target_id}, ["user_id", "target_type", "target_id"])
        if inserted:
            setattr(stats, attribute, getattr(stats, attribute) + 1)
    elif not enabled and existing:
        await db.delete(existing)
        setattr(stats, attribute, max(0, getattr(stats, attribute) - 1))
    await db.flush()
    result = await _stats(db, stored, target_id, user.id)
    await db.commit()
    return result


@router.put("/{target_type}/{target_id}/like")
async def like(target_type: TargetType, target_id: int, db: DB, user: Actor):
    require_social_open(); return {"ok": True, "engagement": await _mutate(db, user, target_type, target_id, AppLike, True)}


@router.delete("/{target_type}/{target_id}/like")
async def unlike(target_type: TargetType, target_id: int, db: DB, user: Actor):
    require_social_open(); return {"ok": True, "engagement": await _mutate(db, user, target_type, target_id, AppLike, False)}


@router.put("/{target_type}/{target_id}/favorite")
async def favorite(target_type: TargetType, target_id: int, db: DB, user: Actor):
    require_social_open(); return {"ok": True, "engagement": await _mutate(db, user, target_type, target_id, AppFavorite, True)}


@router.delete("/{target_type}/{target_id}/favorite")
async def unfavorite(target_type: TargetType, target_id: int, db: DB, user: Actor):
    require_social_open(); return {"ok": True, "engagement": await _mutate(db, user, target_type, target_id, AppFavorite, False)}


async def _comments(db, target_type, target_id, user_id, sort, cursor, limit):
    await _target(db, target_type, target_id, user_id)
    query = select(AppComment).where(AppComment.target_type == target_type, AppComment.target_id == target_id, AppComment.status.in_(("visible", "deleted")), AppComment.parent_id.is_(None))
    if sort == "hot": query = query.order_by(AppComment.reply_count.desc(), AppComment.created_at.desc(), AppComment.id.desc())
    else: query = query.order_by(AppComment.created_at.desc(), AppComment.id.desc())
    if cursor and cursor.isdigit():
        query = query.where(AppComment.id < int(cursor))
    rows = list((await db.scalars(query.limit(limit + 1))).all())
    more, rows = len(rows) > limit, rows[:limit]
    return {"items": [{"id": row.id, "user_id": row.user_id, "text": row.text if row.status == "visible" else "评论已删除", "status": row.status, "parent_id": row.parent_id, "reply_count": row.reply_count, "created_at": row.created_at} for row in rows], "has_more": more, "next_cursor": str(rows[-1].id) if more else None}


@router.get("/{target_type}/{target_id}/comments")
async def comments(target_type: TargetType, target_id: int, db: DB, user: Visitor, sort: Literal["hot", "latest"] = "hot", cursor: str = "", limit: int = Query(20, ge=1, le=50)):
    require_social_open(); return await _comments(db, _stored_type(target_type), target_id, user.id if user else None, sort, cursor, limit)


@router.post("/{target_type}/{target_id}/comments")
async def create_comment(target_type: TargetType, target_id: int, body: CommentInput, db: DB, user: Actor):
    require_social_open(); _, item = await _target(db, _stored_type(target_type), target_id, user.id)
    from .app_settings import get_app_settings
    if not get_app_settings().comments_enabled:
        error("MARKETPLACE_COMMENTS_DISABLED", "评论服务暂未开放", 403)
    target_type = _stored_type(target_type)
    setting = await db.scalar(select(AppSocialSetting).where(AppSocialSetting.target_type == target_type, AppSocialSetting.target_id == target_id))
    if setting and not setting.comments_enabled: error("MARKETPLACE_COMMENTS_DISABLED", "该内容已关闭评论", 403)
    depth = 0; parent = None
    if body.parent_id:
        parent = await db.get(AppComment, body.parent_id)
        if not parent or parent.target_type != target_type or parent.target_id != target_id: error("MARKETPLACE_COMMENT_NOT_FOUND", "回复目标不存在", 404)
        depth = 1; current = parent
        while current.parent_id:
            depth += 1; current = await db.get(AppComment, current.parent_id)
        if depth >= MAX_COMMENT_DEPTH: error("MARKETPLACE_COMMENT_DEPTH_EXCEEDED", "评论回复层级已达上限", 422)
    row = AppComment(user_id=user.id, target_type=target_type, target_id=target_id, parent_id=body.parent_id, text=body.text.strip(), publication_id=getattr(item, "publication_id", None))
    db.add(row); await db.flush()
    if parent: parent.reply_count += 1
    stats = await db.scalar(select(AppContentStats).where(AppContentStats.target_type == target_type, AppContentStats.target_id == target_id).with_for_update())
    if not stats: stats = AppContentStats(target_type=target_type, target_id=target_id); db.add(stats); await db.flush()
    stats.comment_count += 1
    from .service import notify
    owner_id = getattr(item, "owner_id", None)
    if owner_id and owner_id != user.id:
        notify(db, owner_id, f"你的内容收到新评论：{row.text[:80]}", f"/marketplace/{target_type}/{target_id}")
    if parent and parent.user_id != user.id and parent.user_id != owner_id:
        notify(db, parent.user_id, f"有人回复了你的评论：{row.text[:80]}", f"/marketplace/{target_type}/{target_id}")
    await db.commit()
    return {"id": row.id, "text": row.text, "status": row.status, "parent_id": row.parent_id, "created_at": row.created_at}


@router.get("/comments/{comment_id}/replies")
async def comment_replies(comment_id: int, db: DB, user: Visitor, cursor: str = "", limit: int = Query(20, ge=1, le=50)):
    """回复按需分页，支持多级树但不一次展开整棵树。"""
    require_social_open()
    parent = await db.get(AppComment, comment_id)
    if not parent:
        error("MARKETPLACE_COMMENT_NOT_FOUND", "评论不存在", 404)
    await _target(db, parent.target_type, parent.target_id, user.id if user else None)
    query = select(AppComment).where(AppComment.parent_id == comment_id, AppComment.status.in_(("visible", "deleted")))
    if cursor and cursor.isdigit():
        query = query.where(AppComment.id < int(cursor))
    rows = list((await db.scalars(query.order_by(AppComment.created_at.asc(), AppComment.id.asc()).limit(limit + 1))).all())
    more, rows = len(rows) > limit, rows[:limit]
    return {"items": [{"id": r.id, "user_id": r.user_id, "text": r.text if r.status == "visible" else "评论已删除", "status": r.status, "parent_id": r.parent_id, "reply_count": r.reply_count, "created_at": r.created_at} for r in rows], "has_more": more, "next_cursor": str(rows[-1].id) if more else None}


@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: int, db: DB, user: Actor):
    row = await db.get(AppComment, comment_id)
    if not row: error("MARKETPLACE_COMMENT_NOT_FOUND", "评论不存在", 404)
    _, target = await _target(db, row.target_type, row.target_id, user.id)
    if row.user_id != user.id and getattr(target, "owner_id", None) != user.id: error("MARKETPLACE_COMMENT_PERMISSION_DENIED", "无权删除该评论", 403)
    was_visible = row.status == "visible"
    row.status, row.deleted_by, row.deleted_reason = "deleted", user.id, "用户或作者删除"
    if was_visible:
        await db.execute(update(AppContentStats).where(AppContentStats.target_type == row.target_type, AppContentStats.target_id == row.target_id).values(comment_count=func.greatest(AppContentStats.comment_count - 1, 0)))
    await db.commit(); return {"ok": True, "status": row.status}


@router.post("/comments/{comment_id}/reports")
async def report_comment(comment_id: int, body: ReportInput, db: DB, user: Actor):
    row = await db.get(AppComment, comment_id)
    if not row: error("MARKETPLACE_COMMENT_NOT_FOUND", "评论不存在", 404)
    existing = await db.scalar(select(AppCommentReport).where(AppCommentReport.comment_id == comment_id, AppCommentReport.user_id == user.id))
    if existing: return {"ok": True, "status": existing.status}
    db.add(AppCommentReport(comment_id=comment_id, user_id=user.id, reason=body.reason)); await db.commit()
    return {"ok": True, "status": "pending"}


@router.get("/me/favorites")
async def my_favorites(db: DB, user: Actor, target_type: TargetType | None = None, limit: int = Query(20, ge=1, le=50)):
    query = select(AppFavorite).where(AppFavorite.user_id == user.id)
    if target_type: query = query.where(AppFavorite.target_type == _stored_type(target_type))
    rows = list((await db.scalars(query.order_by(AppFavorite.created_at.desc()).limit(limit))).all())
    return {"items": [{"target_type": row.target_type, "target_id": row.target_id, "created_at": row.created_at} for row in rows]}


@router.get("/me/liked-content")
async def my_likes(db: DB, user: Actor, target_type: TargetType | None = None, limit: int = Query(20, ge=1, le=50)):
    query = select(AppLike).where(AppLike.user_id == user.id)
    if target_type:
        query = query.where(AppLike.target_type == _stored_type(target_type))
    rows = list((await db.scalars(query.order_by(AppLike.created_at.desc()).limit(limit))).all())
    return {"items": [{"target_type": row.target_type, "target_id": row.target_id, "created_at": row.created_at} for row in rows]}


@router.put("/{target_type}/{target_id}/social-settings")
async def update_social_settings(target_type: TargetType, target_id: int, body: SocialSettingInput, db: DB, user: Actor):
    """创作者控制评论开关；不改变已保存评论。"""
    stored = _stored_type(target_type)
    model = Work if stored == "work" else SeriesEpisode if stored == "episode" else Series
    target = await db.get(model, target_id)
    if not target:
        error("MARKETPLACE_CONTENT_UNAVAILABLE", "内容不存在或暂不可访问", 404)
    if getattr(target, "owner_id", None) != user.id:
        error("MARKETPLACE_COMMENT_PERMISSION_DENIED", "只有创作者可以修改评论设置", 403)
    item = await db.scalar(select(AppSocialSetting).where(AppSocialSetting.target_type == stored, AppSocialSetting.target_id == target_id).with_for_update())
    if not item:
        item = AppSocialSetting(target_type=stored, target_id=target_id, comments_enabled=body.comments_enabled); db.add(item)
    else:
        item.comments_enabled = body.comments_enabled
    await db.commit()
    return {"target_type": stored, "target_id": target_id, "comments_enabled": item.comments_enabled}

