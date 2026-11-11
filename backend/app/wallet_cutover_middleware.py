"""Cross-process migration barrier, including GET payment callbacks.

HTTP write requests hold a shared advisory lock until their handler returns.
Migration actions use the exclusive version. Reads remain available. DB failure
is never treated as permission to pass a write through the barrier.
"""
from fastapi.responses import JSONResponse
import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.billing import wallet_cutover as cutover

# Barrier connections must not exhaust the pool needed by handlers they protect.
# This separate, bounded pool admits writes while preserving the business pool.
_engine = create_async_engine(get_settings().database_url, pool_size=2, max_overflow=2,
                              pool_pre_ping=True, pool_timeout=30)
BarrierSession = async_sessionmaker(_engine, expire_on_commit=False)


def guarded(method, path):
    if not path.startswith("/api/") or path.startswith("/api/admin/settings/wallet-migration"):
        return False
    if path in ("/api/auth/login", "/api/auth/logout"):
        return False
    return (method not in ("GET", "HEAD", "OPTIONS") or "notify" in path or "webhook" in path
            or path == "/api/admin/settings/models")


async def middleware(request, call_next):
    if not request.url.path.startswith("/api/") or request.url.path == "/api/health":
        return await call_next(request)
    write = guarded(request.method, request.url.path)
    async with (BarrierSession() if write else AsyncSessionLocal()) as db:
        if write:
            await db.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": cutover.LOCK})
        value = await cutover.runtime_state(db)
        await cutover.sync_runtime(db, value)
        # Cancellation can drain existing tasks; it cannot create new spending.
        cancelling = request.method == "POST" and re.fullmatch(r"/api/(?:admin/)?tasks/\d+/cancel", request.url.path) is not None
        if write and value.get("paused") and not cancelling:
            return JSONResponse(status_code=503, headers={"Retry-After": "30"}, content={
                "detail": ("Financial reconciliation maintenance is in progress. Please try again later."
                           if request.headers.get("Accept-Language", "").lower().startswith("en")
                           else "资金核对维护中，暂不接受写入，请稍后重试。"),
                "code": "WALLET_MIGRATION_MAINTENANCE"})
        if not write:
            await db.rollback()
        return await call_next(request)
