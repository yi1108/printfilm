from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.admin.users import router
from app.database import get_db
from app.services.auth import create_access_token, verify_password
from tests.conftest import make_user


@pytest.mark.asyncio
async def test_admin_reset_targets_only_active_regular_users(db_session):
    admin = await make_user(db_session)
    admin.role = "admin"
    member = await make_user(db_session)
    await db_session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db_session
    password = "new-test-password"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async def reset(target, actor=None, value=password):
            headers = {"Authorization": f"Bearer {create_access_token(str(actor.id))}"} if actor else {}
            return await client.post(f"/users/{target.id}/reset-password", headers=headers, json={"new_password": value})

        assert (await reset(member)).status_code == 401
        assert (await reset(member, member)).status_code == 403
        assert (await reset(admin, admin)).status_code == 403
        assert (await reset(member, admin, "汉" * 25)).status_code == 400
        assert member.hashed_password == "test"
        result = await reset(member, admin)
        assert result.status_code == 200 and result.json() == {"ok": True}
        await db_session.refresh(member)
        assert verify_password(password, member.hashed_password)
        stored_hash = member.hashed_password
        member.closed_at = datetime.now(timezone.utc)
        await db_session.commit()
        assert (await reset(member, admin)).status_code == 404
        await db_session.refresh(member)
        assert member.hashed_password == stored_hash
