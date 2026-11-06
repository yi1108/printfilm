"""唯一的原项目接入点：能力发现、路由挂载和独立表初始化。"""
from fastapi import Depends, FastAPI

from .config import is_marketplace_enabled


def install(app: FastAPI) -> None:
    """始终挂上路由。关闭时业务接口返回未启用，能力接口仍可给菜单判断。"""
    from .locale_middleware import install_locale
    from .locale import locale_header
    install_locale(app)
    @app.get(
        "/api/marketplace/capabilities", tags=["下游能力"], response_model=dict,
        summary='获取数字资产市场能力状态',
        description='无需登录，始终可读取。报告市场是否启用以及存储、支付是否具备配置；这些标记仅反映配置存在，不代表外部服务连通性或真实交易已验证。',
        response_description='市场开关 enabled、存储配置 storage_configured 与支付配置 payments。',
    )
    async def capabilities():
        """仅报告配置状态，不将配置完整误报为 OSS 联调通过。"""
        from .storage import configured
        enabled = is_marketplace_enabled()
        from app.config import get_settings
        settings = get_settings()
        return {"enabled": enabled, "storage_configured": enabled and configured(), "sharing_enabled": enabled and settings.marketplace_app_enabled and settings.marketplace_sharing_enabled, "payments": enabled and bool(settings.epay_pid and settings.epay_key and settings.epay_api_url)}

    from . import admin, api, authorization, media, uploads, workspace, series, commerce, handoff, drama_publish
    from .dependencies import enabled

    for router in (api.router, uploads.router, workspace.router, media.router, authorization.router, series.router, commerce.router, handoff.router, drama_publish.router):
        app.include_router(router, prefix="/api/marketplace", dependencies=[Depends(enabled), Depends(locale_header)], tags=["下游作品与招募"])
    app.include_router(admin.router, prefix="/api/admin/marketplace", dependencies=[Depends(enabled)], tags=["下游运营"])
    from .app_bootstrap import install as install_app
    install_app(app)


async def apply_marketplace_switch() -> None:
    """打开时创建市场表并启动 Worker；关闭时只停 Worker，不删表和文件。"""
    from .runtime import start_marketplace_runtime, stop_marketplace_runtime
    if not is_marketplace_enabled():
        await stop_marketplace_runtime()
        return
    from app.database import engine
    from .models import MarketBase
    from .app_schema import legacy_marketplace_tables, acquire_schema_lock, apply_schema
    from .locale_schema import ensure_locale_columns
    async with engine.begin() as conn:
        await conn.run_sync(acquire_schema_lock)
        await conn.run_sync(lambda connection: MarketBase.metadata.create_all(connection, tables=legacy_marketplace_tables()))
        # 旧库没有双语列时，保存市场开关会在读取作品前补列，避免 category_code 不存在。
        await conn.run_sync(ensure_locale_columns)
        await conn.run_sync(apply_schema)
    from app.database import AsyncSessionLocal
    from .previews import reconcile_preview_policy
    async with AsyncSessionLocal() as db:
        await reconcile_preview_policy(db)
        await db.commit()
    await start_marketplace_runtime()
