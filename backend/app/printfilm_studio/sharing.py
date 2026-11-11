"""Canvas-only membership and revocable invitation links.

These grants never authorize drama, team, billing or project administration APIs.
"""
from datetime import UTC, datetime, timedelta
import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, select, delete
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, get_db
from app.deps import get_current_user
from app.models import User
from app.models_drama import DramaProject
from app.printfilm_studio import ensure_enabled


class CanvasMember(Base):
    __tablename__ = 'printfilm_studio_canvas_members'
    __table_args__ = (UniqueConstraint('project_id', 'user_id', name='uq_studio_canvas_member'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[int] = mapped_column(ForeignKey('drama_projects.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CanvasInvitation(Base):
    __tablename__ = 'printfilm_studio_canvas_invitations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[int] = mapped_column(ForeignKey('drama_projects.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def require_canvas_access(db, project, user_id):
    if project.user_id == user_id:
        return
    member = await db.scalar(select(CanvasMember.id).where(CanvasMember.project_id == project.id, CanvasMember.user_id == user_id))
    if not member:
        raise HTTPException(404, '画布不存在或你已不在成员列表中')


async def project_for(db, project_id, user, *, owner=False, lock=False):
    ensure_enabled()
    stmt = select(DramaProject).where(DramaProject.id == project_id).execution_options(populate_existing=True)
    if lock:
        stmt = stmt.with_for_update()
    project = await db.scalar(stmt)
    if not project:
        raise HTTPException(404, '画布不存在')
    await require_canvas_access(db, project, user.id)
    if owner and project.user_id != user.id:
        raise HTTPException(403, '仅画布所有者可以管理邀请和成员')
    return project


router = APIRouter(prefix='/printfilm-studio', tags=['printfilm-studio-sharing'])


@router.get('/projects/{project_id}/info')
async def canvas_info(project_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    project = await project_for(db, project_id, user)
    return {'id': project.id, 'title': project.title, 'is_owner': project.user_id == user.id}


@router.get('/shared-canvases')
async def shared_canvases(db=Depends(get_db), user=Depends(get_current_user)):
    ensure_enabled()
    rows = (await db.scalars(select(DramaProject).join(CanvasMember, CanvasMember.project_id == DramaProject.id).where(CanvasMember.user_id == user.id).order_by(DramaProject.updated_at.desc()))).all()
    return {'items': [{'id': p.id, 'title': p.title} for p in rows]}


@router.get('/projects/{project_id}/sharing')
async def sharing(project_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    project = await project_for(db, project_id, user)
    owner = project.user_id == user.id
    people = list((await db.scalars(select(User).where(User.id.in_(select(CanvasMember.user_id).where(CanvasMember.project_id == project.id))))).all())
    creator = await db.get(User, project.user_id)
    if creator:
        people.insert(0, creator)
    links = (await db.scalars(select(CanvasInvitation).where(CanvasInvitation.project_id == project.id).order_by(CanvasInvitation.created_at.desc()).limit(50))).all() if owner else []
    now = datetime.now(UTC)
    return {'is_owner': owner, 'members': [{'id': p.id, 'name': p.nickname or '画布成员', 'role': 'owner' if p.id == project.user_id else 'member'} for p in people],
            'invitations': [{'id': link.id, 'created_at': link.created_at.isoformat(), 'expires_at': link.expires_at.isoformat(), 'status': 'revoked' if link.revoked_at else 'expired' if link.expires_at <= now else 'active'} for link in links]}


class InviteBody(BaseModel):
    expires_days: int = Field(default=7, ge=1, le=30)


@router.post('/projects/{project_id}/sharing/invitations')
async def create_invitation(project_id: int, body: InviteBody, db=Depends(get_db), user=Depends(get_current_user)):
    await project_for(db, project_id, user, owner=True, lock=True)
    active = await db.scalar(select(func.count()).select_from(CanvasInvitation).where(CanvasInvitation.project_id == project_id, CanvasInvitation.revoked_at.is_(None), CanvasInvitation.expires_at > datetime.now(UTC)))
    if active >= 10:
        raise HTTPException(409, '有效邀请链接最多 10 个，请先撤销旧链接')
    token = secrets.token_urlsafe(32)
    row = CanvasInvitation(project_id=project_id, created_by=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=datetime.now(UTC) + timedelta(days=body.expires_days))
    db.add(row)
    await db.commit()
    return {'id': row.id, 'token': token, 'expires_at': row.expires_at.isoformat()}


@router.delete('/projects/{project_id}/sharing/invitations/{invitation_id}')
async def revoke_invitation(project_id: int, invitation_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    await project_for(db, project_id, user, owner=True, lock=True)
    row = await db.scalar(select(CanvasInvitation).where(CanvasInvitation.id == invitation_id, CanvasInvitation.project_id == project_id).with_for_update())
    if not row:
        raise HTTPException(404, '邀请不存在')
    row.revoked_at = datetime.now(UTC)
    await db.commit()
    return {'ok': True}


class AcceptBody(BaseModel):
    token: str = Field(min_length=32, max_length=128)


@router.post('/canvas-invitations/accept')
async def accept_invitation(body: AcceptBody, db=Depends(get_db), user=Depends(get_current_user)):
    ensure_enabled()
    digest = hashlib.sha256(body.token.encode()).hexdigest()
    project_id = await db.scalar(select(CanvasInvitation.project_id).where(CanvasInvitation.token_hash == digest))
    if not project_id:
        raise HTTPException(410, '邀请链接已失效')
    # Consistent project -> invitation lock order serializes revoke, remove and join.
    project = await db.scalar(select(DramaProject).where(DramaProject.id == project_id).with_for_update())
    row = await db.scalar(select(CanvasInvitation).where(CanvasInvitation.token_hash == digest).with_for_update().execution_options(populate_existing=True))
    if not project or not row or row.revoked_at or row.expires_at <= datetime.now(UTC):
        raise HTTPException(410, '邀请链接已撤销或已过期')
    if project.user_id != user.id and not await db.scalar(select(CanvasMember.id).where(CanvasMember.project_id == project.id, CanvasMember.user_id == user.id)):
        db.add(CanvasMember(project_id=project.id, user_id=user.id))
    await db.commit()
    return {'project_id': project.id}


@router.delete('/projects/{project_id}/sharing/members/{member_id}')
async def remove_member(project_id: int, member_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    project = await project_for(db, project_id, user, owner=True, lock=True)
    if member_id == project.user_id:
        raise HTTPException(422, '不能移除画布所有者')
    await db.execute(delete(CanvasMember).where(CanvasMember.project_id == project.id, CanvasMember.user_id == member_id))
    await db.commit()
    return {'ok': True}
