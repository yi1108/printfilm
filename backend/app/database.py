"""Async SQLAlchemy engine / session for API and task runtime（仅 PostgreSQL）。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


def _require_postgres(url: str) -> None:
    """拒绝非 Postgres 连接串，避免误连 SQLite。"""
    if not (url or "").startswith("postgresql"):
        raise RuntimeError(
            "仅支持 PostgreSQL。请设置 DATABASE_URL=postgresql+asyncpg://..."
            f"（当前：{(url or '')[:48]!r}）"
        )


def _postgres_pool_kwargs() -> dict:
    """Build QueuePool kwargs for Postgres."""
    return {
        "pool_pre_ping": True,
        "pool_size": max(1, int(settings.db_pool_size)),
        "max_overflow": max(0, int(settings.db_max_overflow)),
        "pool_recycle": max(60, int(settings.db_pool_recycle_sec)),
        "pool_timeout": max(5, int(settings.db_pool_timeout_sec)),
    }


_require_postgres(settings.database_url)

_engine_kwargs: dict = {"echo": bool(settings.sql_echo)}
_engine_kwargs.update(_postgres_pool_kwargs())

engine = create_async_engine(settings.database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401
    from app import models_agent  # noqa: F401
    from app import models_drama  # noqa: F401
    from app import models_api  # noqa: F401
    from app import models_settings  # noqa: F401
    from app import models_tasks  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Drop pooled connections so the next asyncio.run can bind a fresh loop.

    Long-running scripts that call asyncio.run repeatedly should dispose between
    runs; otherwise asyncpg/SQLAlchemy futures stay attached to a closed loop.
    """
    await engine.dispose()


def pool_status() -> dict | None:
    """Snapshot SQLAlchemy pool counters for /api/health."""
    pool = engine.pool
    return {
        "role": "api",
        "size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "max": int(settings.db_pool_size) + int(settings.db_max_overflow),
    }
