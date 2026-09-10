"""密码重置：token 存取、冷却与一次性消费（mock Redis）。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import password_reset as pr


class FakeRedis:
    """最小 Redis 替身：支持 get/setex/delete/pipeline/ping。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = str(value)
        self.ttls[key] = int(ttl)
        return True

    def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                self.ttls.pop(key, None)
                n += 1
        return n

    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def setex(self, key: str, ttl: int, value: str) -> "FakePipeline":
        self.ops.append(("setex", (key, ttl, value)))
        return self

    def execute(self) -> list[bool]:
        out: list[bool] = []
        for name, args in self.ops:
            if name == "setex":
                out.append(self.redis.setex(*args))
        return out


def test_create_and_consume_reset_token_roundtrip():
    # 签发后可消费一次，第二次失败
    r = FakeRedis()
    token = pr.create_reset_token(r, user_id=42)
    assert token
    assert r.get(pr._user_key(42))
    user_id = pr.consume_reset_token(r, token)
    assert user_id == 42
    assert r.get(pr._token_key(pr._token_hash(token))) is None
    with pytest.raises(pr.InvalidTokenError):
        pr.consume_reset_token(r, token)


def test_new_token_invalidates_old():
    # 同用户新 token 会使旧 token 失效
    r = FakeRedis()
    old = pr.create_reset_token(r, user_id=7)
    new = pr.create_reset_token(r, user_id=7)
    assert old != new
    with pytest.raises(pr.InvalidTokenError):
        pr.consume_reset_token(r, old)
    assert pr.consume_reset_token(r, new) == 7


def test_consume_empty_or_unknown_token():
    r = FakeRedis()
    with pytest.raises(pr.InvalidTokenError):
        pr.consume_reset_token(r, "")
    with pytest.raises(pr.InvalidTokenError):
        pr.consume_reset_token(r, "not-a-real-token")


@pytest.mark.asyncio
async def test_request_password_reset_cooldown_skips_resend():
    # 冷却期内第二次请求不重发、不重写 token
    fake = FakeRedis()
    user = MagicMock(id=9, email="a@example.com")
    db = AsyncMock()

    with (
        patch.object(pr, "get_redis_client", return_value=fake),
        patch.object(pr, "get_user_by_email", AsyncMock(return_value=user)) as get_user,
        patch.object(pr, "send_email", AsyncMock(return_value=True)) as send,
        patch.object(pr, "get_settings") as settings,
    ):
        settings.return_value.public_base_url = "https://www.printfilm.com"
        first = await pr.request_password_reset(db, "A@Example.com")
        assert first["ok"] is True
        assert send.await_count == 1
        assert get_user.await_count == 1
        token_keys = [k for k in fake.store if k.startswith("pwdreset:") and not k.startswith("pwdreset:cd:") and not k.startswith("pwdreset:user:")]
        assert len(token_keys) == 1

        second = await pr.request_password_reset(db, "a@example.com")
        assert second["ok"] is True
        assert send.await_count == 1
        assert get_user.await_count == 1


@pytest.mark.asyncio
async def test_request_password_reset_unknown_email_still_ok():
    # 未注册邮箱仍返回统一成功文案
    fake = FakeRedis()
    db = AsyncMock()
    with (
        patch.object(pr, "get_redis_client", return_value=fake),
        patch.object(pr, "get_user_by_email", AsyncMock(return_value=None)),
        patch.object(pr, "send_email", AsyncMock(return_value=True)) as send,
    ):
        res = await pr.request_password_reset(db, "nobody@example.com")
        assert res["ok"] is True
        assert res["message"] == pr.GENERIC_OK_MESSAGE
        send.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_password_reset_updates_hash():
    fake = FakeRedis()
    token = pr.create_reset_token(fake, user_id=3)
    user = MagicMock(id=3, hashed_password="old")
    db = AsyncMock()

    with (
        patch.object(pr, "get_redis_client", return_value=fake),
        patch.object(pr, "get_user_by_id", AsyncMock(return_value=user)),
        patch.object(pr, "hash_password", return_value="new-hash") as hp,
    ):
        await pr.apply_password_reset(db, token=token, new_password="secret1")
        hp.assert_called_once_with("secret1")
        assert user.hashed_password == "new-hash"
        db.commit.assert_awaited()
        with pytest.raises(pr.InvalidTokenError):
            await pr.apply_password_reset(db, token=token, new_password="again12")
