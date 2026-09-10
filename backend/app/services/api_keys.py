"""用户 API Key 创建、校验与撤销。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models_api import UserApiKey

API_KEY_PREFIX = "pf_live_"


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """返回 (完整 key, 展示前缀, hash)。"""
    secret = secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:32]
    raw = f"{API_KEY_PREFIX}{secret}"
    prefix = raw[:16]
    return raw, prefix, _hash_key(raw)


async def create_api_key(db: AsyncSession, user: User, name: str) -> tuple[UserApiKey, str]:
    raw, prefix, key_hash = generate_api_key()
    row = UserApiKey(
        user_id=user.id,
        name=(name or "默认 Key").strip()[:64] or "默认 Key",
        key_prefix=prefix,
        key_hash=key_hash,
    )
    db.add(row)
    await db.flush()
    return row, raw


async def list_api_keys(db: AsyncSession, user_id: int) -> list[UserApiKey]:
    result = await db.execute(
        select(UserApiKey)
        .where(UserApiKey.user_id == user_id, UserApiKey.revoked_at.is_(None))
        .order_by(UserApiKey.id.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(db: AsyncSession, user_id: int, key_id: int) -> bool:
    row = await db.get(UserApiKey, key_id)
    if not row or row.user_id != user_id or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return True


async def user_from_api_key(db: AsyncSession, raw_key: str) -> User | None:
    if not raw_key.startswith(API_KEY_PREFIX):
        return None
    key_hash = _hash_key(raw_key.strip())
    result = await db.execute(
        select(UserApiKey, User)
        .join(User, User.id == UserApiKey.user_id)
        .where(UserApiKey.key_hash == key_hash, UserApiKey.revoked_at.is_(None))
    )
    row = result.first()
    if not row:
        return None
    api_key, user = row
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.flush()
    return user
