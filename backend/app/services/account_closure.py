"""账号注销：保留必要账务记录，立即永久移除登录资料。"""
from datetime import datetime, timezone
import secrets

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models_tasks import TaskRun
from app.models_teams import Team, TeamMember
from app.services.auth import hash_password, verify_password

ACCOUNT_CONFIRMATION_WORD = "DELETE"
UNFINISHED_TASK_STATUSES = (
    "pending",
    "leased",
    "running",
    "awaiting_poll",
    "awaiting_review",
    "cancel_requested",
    "finalizing",
)


async def _ensure_can_close(db: AsyncSession, user_id: int) -> None:
    """避免留下无所有者的团队，或注销后仍产生任务费用。"""
    owned_team = await db.scalar(select(Team.id).where(Team.owner_user_id == user_id).limit(1))
    if owned_team is not None:
        raise HTTPException(status_code=409, detail="请先转让或删除名下团队，再注销账号")

    unfinished_task = await db.scalar(
        select(TaskRun.id)
        .where(
            or_(TaskRun.requested_by == user_id, TaskRun.billing_payer_user_id == user_id),
            TaskRun.status.in_(UNFINISHED_TASK_STATUSES),
        )
        .limit(1)
    )
    if unfinished_task is not None:
        raise HTTPException(status_code=409, detail="还有未结束的生成任务，请等待完成或取消任务后再注销")


async def close_account(
    db: AsyncSession,
    *,
    user: User,
    password: str,
    confirmation: str,
) -> dict[str, bool]:
    """校验身份后原子匿名化资料；旧 JWT 会因注销墓碑而立即失效。"""
    if confirmation != ACCOUNT_CONFIRMATION_WORD:
        raise HTTPException(status_code=400, detail=f"请输入 {ACCOUNT_CONFIRMATION_WORD} 确认注销")
    if not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")

    # 锁定账号，防止两个注销请求同时通过身份校验。
    locked_user = await db.scalar(select(User).where(User.id == user.id).with_for_update())
    if locked_user is None or locked_user.closed_at is not None:
        raise HTTPException(status_code=401, detail="登录已失效")
    await _ensure_can_close(db, int(user.id))

    closed_at = datetime.now(timezone.utc)
    anonymous_local_part = f"deleted-{user.id}-{secrets.token_hex(8)}"
    locked_user.email = f"{anonymous_local_part}@deleted.printfilm.invalid"
    locked_user.nickname = "已注销用户"
    locked_user.phone = ""
    locked_user.avatar_url = ""
    locked_user.hashed_password = hash_password(secrets.token_urlsafe(48))
    locked_user.closed_at = closed_at

    # 保留成员历史和外键，但立即撤销其团队工作区访问资格。
    await db.execute(
        update(TeamMember)
        .where(TeamMember.user_id == user.id, TeamMember.active.is_(True))
        .values(active=False)
    )
    await db.commit()
    return {"ok": True}
