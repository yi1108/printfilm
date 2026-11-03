"""App 路由与财务运行时集成，展示开关不控制已付款履约。"""
import logging
import time

from fastapi import Depends, FastAPI, Request

from .app_schema import check_schema, register_models
from .coin_service import app_fail

logger = logging.getLogger(__name__)
_schema_checked_at = 0.0
_schema_ready = False


async def verify_schema() -> list[str]:
    """只读检查独立增量结构；启动时不静默创建财务表。"""
    global _schema_checked_at, _schema_ready
    from app.database import engine
    async with engine.connect() as connection:
        missing = await connection.run_sync(check_schema)
    _schema_checked_at, _schema_ready = time.monotonic(), not missing
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
    """功能开放前要求显式迁移；停新购仍启动已配置的通知和补偿。"""
    from .app_settings import get_app_settings
    from .apple_client import apple_configured
    from .apple_runtime import start_apple_runtime
    config = get_app_settings()
    if config.enabled or config.apple_iap_enabled or apple_configured():
        missing = await verify_schema()
        if missing:
            raise RuntimeError("App数据库结构未准备，请先运行 scripts.prepare_marketplace_app_schema 并使用 --check 验证：" + ", ".join(missing))
    await start_apple_runtime()


async def stop_app_services() -> None:
    """关闭通知处理后释放播放Redis连接，数据库持久状态不丢失。"""
    from .apple_runtime import stop_apple_runtime
    from .app_playback import session_store
    await stop_apple_runtime()
    if session_store.cache_info().currsize:
        await session_store().aclose()
        session_store.cache_clear()
