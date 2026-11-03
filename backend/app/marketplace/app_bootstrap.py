"""App 路由与财务运行时集成，展示开关不控制已付款履约。"""
import logging
import time

from fastapi import Depends, FastAPI, Request

from .app_schema import acquire_schema_lock, apply_schema, check_schema, legacy_marketplace_tables, register_models
from .coin_service import app_fail

logger = logging.getLogger(__name__)
_schema_checked_at = 0.0
_schema_ready = False


async def verify_schema() -> list[str]:
    """只读检查 App 内容、播放、互动及财务结构。"""
    global _schema_checked_at, _schema_ready
    from app.database import engine
    async with engine.connect() as connection:
        missing = await connection.run_sync(check_schema)
    _schema_checked_at, _schema_ready = time.monotonic(), not missing
    return missing


async def ensure_schema() -> list[str]:
    """在 API 启动阶段幂等建立 App 结构并核验结果。

    The transaction lock covers both the legacy marketplace tables required by
    App foreign keys and all App content/social/financial tables.  Only
    additive, checkfirst/IF NOT EXISTS operations are performed; no historical
    rows, balances, orders, or columns are deleted or rewritten.
    """
    from app.database import engine
    from .models import MarketBase

    logger.info("Ensuring marketplace App schema (content, playback, social and finance)")
    async with engine.begin() as connection:
        await connection.run_sync(acquire_schema_lock)
        # App tables reference the original marketplace tables.  Creating the
        # missing legacy tables here makes first boot deterministic; the normal
        # marketplace switch remains responsible for starting its worker.
        await connection.run_sync(
            lambda sync_connection: MarketBase.metadata.create_all(
                sync_connection, tables=legacy_marketplace_tables()
            )
        )
        await connection.run_sync(apply_schema)
        missing = await connection.run_sync(check_schema)

    global _schema_checked_at, _schema_ready
    _schema_checked_at, _schema_ready = time.monotonic(), not missing
    if missing:
        logger.error("Marketplace App schema is incomplete after startup migration: %s", ", ".join(missing))
    else:
        logger.info("Marketplace App schema is ready")
    return missing


async def schema_ready() -> bool:
    """接口与媒体循环共用只读检查缓存，未迁移时不查询或创建 App 业务表。"""
    if not _schema_ready and time.monotonic() - _schema_checked_at >= 5:
        await verify_schema()
    return _schema_ready


async def require_schema(request: Request) -> None:
    """未迁移时给出503而非缺表500；能力发现始终可用。"""
    if request.url.path == "/api/marketplace/app/v1/capabilities":
        return
    if not await schema_ready():
        app_fail("MARKETPLACE_APP_SCHEMA_REQUIRED", "App服务结构尚未准备，请先完成数字资产市场App增量迁移并重启服务。", 503)


def install(app: FastAPI) -> None:
    """独立挂载App及运营路由，不继承市场展示开关依赖。"""
    from . import app_admin, app_content, app_playback, apple_api, coin_api, app_social
    from .app_logging import install_access_filter
    from .locale import locale_header
    from .locale_middleware import install_locale
    install_locale(app)
    register_models()
    install_access_filter()
    for router in (app_content.router, app_playback.router, coin_api.router, apple_api.router, app_social.router):
        app.include_router(router, prefix="/api/marketplace/app/v1", dependencies=[Depends(require_schema), Depends(locale_header)], tags=["App视频与观影币"])
    app.include_router(app_admin.router, prefix="/api/admin/marketplace/app", dependencies=[Depends(require_schema)], tags=["App运营与财务"])
    app.include_router(apple_api.notifications_router, dependencies=[Depends(require_schema)], tags=["Apple服务器通知"])
    app.include_router(apple_api.billing_router, dependencies=[Depends(require_schema)], tags=["统一钱包Apple支付"])


async def start_app_services() -> None:
    """自动完成幂等增量迁移，再启动已配置的 Apple 通知和补偿运行时。"""
    from .app_settings import get_app_settings, is_app_enabled
    from .apple_client import apple_configured
    from .apple_runtime import start_apple_runtime
    config = get_app_settings()
    if is_app_enabled() or config.apple_iap_enabled or apple_configured():
        missing = await ensure_schema()
        if missing:
            raise RuntimeError("App数据库结构自动迁移后仍不完整：" + ", ".join(missing))
    await start_apple_runtime()


async def stop_app_services() -> None:
    """关闭通知处理后释放播放Redis连接，数据库持久状态不丢失。"""
    from .apple_runtime import stop_apple_runtime
    from .app_playback import session_store
    await stop_apple_runtime()
    if session_store.cache_info().currsize:
        await session_store().aclose()
        session_store.cache_clear()
