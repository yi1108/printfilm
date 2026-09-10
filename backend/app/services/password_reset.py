# -*- coding: utf-8 -*-
"""邮箱找回密码：Redis 一次性 token + SMTP 重置链接。"""
from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.auth import get_user_by_email, get_user_by_id, hash_password
from app.services.email import send_email

logger = logging.getLogger(__name__)

# token TTL / 同邮箱冷却
TOKEN_TTL_SECONDS = 30 * 60
COOLDOWN_SECONDS = 60

GENERIC_OK_MESSAGE = "若该邮箱已注册，将收到重置邮件"


class PasswordResetError(Exception):
    """找回/重置密码业务错误。"""


class RedisUnavailableError(PasswordResetError):
    """Redis 不可用，无法签发或校验重置 token。"""


class InvalidTokenError(PasswordResetError):
    """重置 token 无效或已过期。"""


def _token_hash(token: str) -> str:
    # 只存 sha256，明文 token 仅出现在邮件链接里
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_key(token_hash: str) -> str:
    return f"pwdreset:{token_hash}"


def _user_key(user_id: int) -> str:
    return f"pwdreset:user:{user_id}"


def _cooldown_key(email: str) -> str:
    return f"pwdreset:cd:{email}"


def get_redis_client() -> Any:
    """连接 Redis；失败则抛 RedisUnavailableError（不做内存回退）。"""
    try:
        import redis

        client = redis.Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("password reset redis unavailable: %s", exc)
        raise RedisUnavailableError("服务暂时不可用，请稍后再试") from exc


def create_reset_token(redis_client: Any, user_id: int) -> str:
    """签发一次性 token，并使该用户旧 token 失效。"""
    old_hash = redis_client.get(_user_key(user_id))
    if old_hash:
        redis_client.delete(_token_key(str(old_hash)))

    token = secrets.token_urlsafe(32)
    th = _token_hash(token)
    pipe = redis_client.pipeline()
    pipe.setex(_token_key(th), TOKEN_TTL_SECONDS, str(user_id))
    pipe.setex(_user_key(user_id), TOKEN_TTL_SECONDS, th)
    pipe.execute()
    return token


def consume_reset_token(redis_client: Any, token: str) -> int:
    """校验并删除 token，返回 user_id；无效则抛 InvalidTokenError。"""
    raw = (token or "").strip()
    if not raw:
        raise InvalidTokenError("重置链接无效或已过期")
    th = _token_hash(raw)
    key = _token_key(th)
    user_id_raw = redis_client.get(key)
    if not user_id_raw:
        raise InvalidTokenError("重置链接无效或已过期")
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError) as exc:
        redis_client.delete(key)
        raise InvalidTokenError("重置链接无效或已过期") from exc

    redis_client.delete(key, _user_key(user_id))
    return user_id


def build_reset_link(token: str) -> str:
    # 用户端 Auth 页：?mode=reset&token=...
    base = str(get_settings().public_base_url or "").rstrip("/")
    return f"{base}/auth?mode=reset&token={token}"


async def request_password_reset(db: AsyncSession, email: str) -> dict[str, Any]:
    """
    发起找回：写 Redis token 并尝试发信。
    始终返回统一成功文案（防枚举）；Redis 不可用时抛错。
    """
    redis_client = get_redis_client()
    email_norm = str(email or "").strip().lower()
    cd_key = _cooldown_key(email_norm)

    # 60 秒冷却：重复请求直接成功、不重发
    if redis_client.get(cd_key):
        return {"ok": True, "message": GENERIC_OK_MESSAGE}

    redis_client.setex(cd_key, COOLDOWN_SECONDS, "1")

    user = await get_user_by_email(db, email_norm)
    if not user:
        return {"ok": True, "message": GENERIC_OK_MESSAGE}

    token = create_reset_token(redis_client, int(user.id))
    link = build_reset_link(token)
    body = (
        "您正在重置 PRINTFILM 账号密码。\n\n"
        f"请在 30 分钟内打开以下链接设置新密码：\n{link}\n\n"
        "如非本人操作，请忽略本邮件。"
    )
    sent = await send_email(
        to_addrs=[email_norm],
        subject="PRINTFILM 密码重置",
        body=body,
    )
    if not sent:
        logger.warning(
            "password reset email not sent (smtp off or failed) user_id=%s email=%s",
            user.id,
            email_norm,
        )
    return {"ok": True, "message": GENERIC_OK_MESSAGE}


async def apply_password_reset(
    db: AsyncSession,
    *,
    token: str,
    new_password: str,
) -> None:
    """校验 token 后更新密码；token 一次性消费。"""
    redis_client = get_redis_client()
    user_id = consume_reset_token(redis_client, token)
    user = await get_user_by_id(db, user_id)
    if not user:
        raise InvalidTokenError("重置链接无效或已过期")
    user.hashed_password = hash_password(new_password)
    await db.commit()
