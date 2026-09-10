"""计费/管理端集成测试：PostgreSQL + 开启 billing。"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings
from app.database import Base
from app.models import User
from app.models_tasks import TaskRun


@pytest.fixture
def billing_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试环境强制开启计费，buffer=1 便于断言。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "billing_estimate_buffer", 1.0)


@pytest_asyncio.fixture
async def db_session(billing_enabled: None) -> AsyncIterator[AsyncSession]:
    """每个用例外层事务回滚；session.commit 只提交 savepoint，不落库。"""
    # 注册全部 ORM 表
    import app.models  # noqa: F401
    import app.models_agent  # noqa: F401
    import app.models_api  # noqa: F401
    import app.models_drama  # noqa: F401
    import app.models_settings  # noqa: F401
    import app.models_tasks  # noqa: F401

    url = (get_settings().database_url or "").strip()
    if not url.startswith("postgresql"):
        raise RuntimeError("集成测试需要 PostgreSQL DATABASE_URL（postgresql+asyncpg://...）")

    engine = create_async_engine(url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 增量列（与 main._apply_schema_patches 保持一致）
        from sqlalchemy import text

        result = await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'users'"
            )
        )
        ucols = {row[0] for row in result.fetchall()}
        if "billing_alert_last_milestone_fen" not in ucols:
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN billing_alert_last_milestone_fen INTEGER DEFAULT 0")
            )

    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()

    await engine.dispose()


async def make_user(
    db: AsyncSession,
    *,
    balance_fen: int = 100_000,
    frozen_fen: int = 0,
) -> User:
    """创建测试用户。"""
    user = User(
        email=f"billing-{uuid.uuid4().hex[:10]}@test.local",
        hashed_password="test",
        balance_fen=balance_fen,
        frozen_fen=frozen_fen,
    )
    db.add(user)
    await db.flush()
    return user


async def make_task(
    db: AsyncSession,
    user: User,
    *,
    domain: str = "api",
    task_type: str = "v1_image",
    status: str = "pending",
    billing_status: str = "none",
    provider_task_id: str | None = None,
) -> TaskRun:
    """创建测试 TaskRun（无业务 FK）。"""
    task = TaskRun(
        domain=domain,
        task_type=task_type,
        status=status,
        requested_by=user.id,
        provider_task_id=provider_task_id,
        billing_status=billing_status,
        payload={},
    )
    db.add(task)
    await db.flush()
    return task
