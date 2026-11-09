"""账号注销：密码与确认词、立即匿名化、账务保留及旧凭证失效。"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.auth import login, register, router as auth_router
from app.database import get_db
from app.deps import _user_from_bearer
from app.models import User, WalletLedger
from app.models_tasks import TaskRun
from app.models_teams import Team, TeamMember
from app.schemas import CloseAccountRequest, LoginRequest, RegisterRequest
from app.services.account_closure import (
    ACCOUNT_CONFIRMATION_WORD,
    UNFINISHED_TASK_STATUSES,
    close_account,
)
from app.services.auth import create_access_token, get_user_by_email, hash_password
from app.services.password_reset import InvalidTokenError, apply_password_reset


async def make_closable_user(db, **overrides) -> User:
    """建立带真实密码哈希及可识别资料的测试用户。"""
    values = {
        "email": f"closure-{uuid.uuid4().hex[:10]}@example.com",
        "nickname": "待注销用户",
        "phone": "+86 138 0000 0000",
        "avatar_url": "https://cdn.example.com/avatar.jpg",
        "hashed_password": hash_password("correct-password"),
        "balance_fen": 12345,
        "frozen_fen": 678,
    }
    values.update(overrides)
    user = User(**values)
    db.add(user)
    await db.flush()
    return user


async def test_close_account_requires_exact_confirmation_word(db_session):
    """确认词不匹配时不得匿名化或修改密码。"""
    user = await make_closable_user(db_session)
    original_hash = user.hashed_password

    with pytest.raises(HTTPException) as exc_info:
        await close_account(db_session, user=user, password="correct-password", confirmation="delete")

    assert exc_info.value.status_code == 400
    assert "DELETE" in exc_info.value.detail
    assert user.closed_at is None
    assert user.hashed_password == original_hash


async def test_close_account_rejects_wrong_password(db_session):
    """密码不正确返回明确错误，且不产生部分写入。"""
    user = await make_closable_user(db_session)
    original_email = user.email

    with pytest.raises(HTTPException) as exc_info:
        await close_account(
            db_session,
            user=user,
            password="wrong-password",
            confirmation=ACCOUNT_CONFIRMATION_WORD,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "当前密码不正确"
    assert user.closed_at is None
    assert user.email == original_email


@pytest.mark.parametrize("password", ["", "x" * 65])
def test_close_account_request_rejects_invalid_password_lengths(password):
    """密码边界在请求模型统一校验。"""
    with pytest.raises(ValueError):
        CloseAccountRequest(password=password, confirmation=ACCOUNT_CONFIRMATION_WORD)


async def test_close_account_anonymizes_profile_and_invalidates_all_credentials(db_session):
    """成功后资料匿名、账务不变，旧 JWT/邮箱登录均立即失效。"""
    user = await make_closable_user(db_session)
    original_email = user.email
    user_id = user.id
    old_token = create_access_token(str(user_id))
    ledger = WalletLedger(
        user_id=user_id,
        delta_fen=100,
        balance_after=12345,
        kind="charge",
        ref_type="test",
        ref_id="closure",
        note="legally retained billing record",
    )
    db_session.add(ledger)
    await db_session.flush()

    result = await close_account(
        db_session,
        user=user,
        password="correct-password",
        confirmation=ACCOUNT_CONFIRMATION_WORD,
    )
    await db_session.refresh(user)

    assert result == {"ok": True}
    assert user.closed_at is not None
    assert user.email != original_email
    assert user.email.endswith("@deleted.printfilm.invalid")
    assert original_email not in user.email
    assert user.nickname == "已注销用户"
    assert user.phone == ""
    assert user.avatar_url == ""
    assert user.balance_fen == 12345
    assert user.frozen_fen == 678
    assert ledger.user_id == user_id
    assert await _user_from_bearer(db_session, old_token) is None
    assert await get_user_by_email(db_session, original_email) is None
    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(email=original_email, password="correct-password"), db_session)
    assert exc_info.value.status_code == 401


async def test_close_account_blocks_owned_team(db_session):
    """名下团队未转让或删除时返回 409，账号资料保持不变。"""
    user = await make_closable_user(db_session)
    original_email = user.email
    db_session.add(Team(name="待处理团队", owner_user_id=user.id))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await close_account(
            db_session,
            user=user,
            password="correct-password",
            confirmation=ACCOUNT_CONFIRMATION_WORD,
        )

    assert exc_info.value.status_code == 409
    assert "团队" in exc_info.value.detail
    assert user.closed_at is None
    assert user.email == original_email


@pytest.mark.parametrize("status", UNFINISHED_TASK_STATUSES)
async def test_close_account_blocks_every_unfinished_task_status(db_session, status):
    """所有非终态任务都阻止注销，避免匿名账号继续生成或扣费。"""
    user = await make_closable_user(db_session)
    db_session.add(
        TaskRun(
            domain="studio",
            task_type="tool_image",
            queue_type="image",
            requested_by=user.id,
            status=status,
            payload={},
        )
    )
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await close_account(
            db_session,
            user=user,
            password="correct-password",
            confirmation=ACCOUNT_CONFIRMATION_WORD,
        )

    assert exc_info.value.status_code == 409
    assert "任务" in exc_info.value.detail
    assert user.closed_at is None


async def test_close_account_blocks_task_billed_to_user(db_session):
    """即使任务由他人发起，当前用户作为付款人也必须先等待任务结束。"""
    user = await make_closable_user(db_session)
    requester = await make_closable_user(db_session)
    db_session.add(
        TaskRun(
            domain="studio",
            task_type="tool_image",
            queue_type="image",
            requested_by=requester.id,
            billing_payer_user_id=user.id,
            status="running",
            payload={},
        )
    )
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await close_account(
            db_session,
            user=user,
            password="correct-password",
            confirmation=ACCOUNT_CONFIRMATION_WORD,
        )

    assert exc_info.value.status_code == 409
    assert user.closed_at is None


async def test_close_account_allows_terminal_tasks_and_deactivates_memberships(db_session):
    """终态账务任务和成员历史保留，但团队成员资格立即失效。"""
    user = await make_closable_user(db_session)
    owner = await make_closable_user(db_session)
    team = Team(name="历史团队", owner_user_id=owner.id)
    db_session.add(team)
    await db_session.flush()
    membership = TeamMember(team_id=team.id, user_id=user.id, role="member", active=True)
    task = TaskRun(
        domain="studio",
        task_type="tool_image",
        queue_type="image",
        requested_by=user.id,
        status="succeeded",
        billing_charged_fen=100,
        payload={},
    )
    db_session.add_all([membership, task])
    await db_session.flush()
    membership_id = membership.id
    task_id = task.id

    assert await close_account(
        db_session,
        user=user,
        password="correct-password",
        confirmation=ACCOUNT_CONFIRMATION_WORD,
    ) == {"ok": True}
    await db_session.refresh(membership)
    await db_session.refresh(task)

    assert membership.id == membership_id
    assert membership.active is False
    assert task.id == task_id
    assert task.billing_charged_fen == 100


async def test_close_account_http_endpoint_invalidates_bearer_token(db_session):
    """真实 HTTP 路由成功后返回 ok，同一 Bearer 随后只能得到 401。"""
    user = await make_closable_user(db_session)
    token = create_access_token(str(user.id))
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")

    async def override_db():
        """把路由事务绑定到当前回滚测试会话。"""
        yield db_session

    app.dependency_overrides[get_db] = override_db
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/close-account",
            headers=headers,
            json={"password": "correct-password", "confirmation": "DELETE"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        old_token_response = await client.get("/api/auth/me", headers=headers)
        assert old_token_response.status_code == 401
        repeated_response = await client.post(
            "/api/auth/close-account",
            headers=headers,
            json={"password": "correct-password", "confirmation": "DELETE"},
        )
        assert repeated_response.status_code == 401
        anonymous_response = await client.post(
            "/api/auth/close-account",
            json={"password": "correct-password", "confirmation": "DELETE"},
        )
        assert anonymous_response.status_code == 401


async def test_original_email_can_register_a_distinct_account_after_closure(db_session):
    """原邮箱可注册全新账号，但不会恢复已注销账号的身份或凭证。"""
    user = await make_closable_user(db_session)
    original_email = user.email
    closed_user_id = user.id
    await close_account(
        db_session,
        user=user,
        password="correct-password",
        confirmation=ACCOUNT_CONFIRMATION_WORD,
    )

    token = await register(
        RegisterRequest(email=original_email, password="new-password", nickname="新账号"),
        db_session,
    )
    new_user = await get_user_by_email(db_session, original_email)

    assert new_user is not None
    assert new_user.id != closed_user_id
    assert token.access_token
    assert user.closed_at is not None
    assert user.email.endswith("@deleted.printfilm.invalid")


async def test_password_reset_token_issued_before_closure_cannot_restore_access(
    db_session, monkeypatch
):
    """注销前签发的重置 token 不得恢复账号或改密码。"""
    user = await make_closable_user(db_session)
    user_id = user.id
    original_hash = user.hashed_password
    await close_account(
        db_session,
        user=user,
        password="correct-password",
        confirmation=ACCOUNT_CONFIRMATION_WORD,
    )

    class FakeRedis:
        pass

    monkeypatch.setattr("app.services.password_reset.get_redis_client", lambda: FakeRedis())
    monkeypatch.setattr("app.services.password_reset.consume_reset_token", lambda _redis, _token: user_id)
    closed_hash = user.hashed_password
    assert closed_hash != original_hash

    with pytest.raises(InvalidTokenError):
        await apply_password_reset(db_session, token="issued-before-closure", new_password="new-password")
    assert user.hashed_password == closed_hash
