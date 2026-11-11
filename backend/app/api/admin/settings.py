"""管理员模型路由、运行配置及媒体价格管理接口。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_admin
from app.models import User
from app.schemas_routing import AdminRoutingSettingsOut, AdminRoutingSettingsPatch, AdminRoutingSettingsSaveOut
from app.schemas_settings import (
    AdminModelSettingsImportEnvOut,
    AdminModelSettingsOut,
    AdminModelSettingsPatch,
    AdminModelSettingsSaveOut,
)
from app.services.model_settings import (
    get_admin_model_settings,
    get_admin_routing_settings,
    import_admin_model_settings_from_env,
    patch_admin_model_settings,
    patch_admin_routing_settings,
)
from app.services.upstream_model_catalog import list_upstream_models

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/settings/apple/status", summary="检查 Apple 支付配置（不发起支付）")
async def apple_settings_status(_admin: User = Depends(get_current_admin)):
    from app.config import get_settings
    from app.marketplace.app_settings import get_app_settings
    from app.marketplace.apple_configuration import configuration_status
    from app.marketplace.apple_runtime import apple_runtime_state
    from app.services.billing.wallet import enabled
    from app.services.billing.wallet_base import environment as wallet_environment
    base = get_settings().public_base_url.rstrip("/")
    return {**configuration_status(get_app_settings()),
            "notification_url": f"{base}/api/billing/apple/notifications",
            "notification_https": base.startswith("https://"),
            "unified_wallet_enabled": enabled(),
            "sandbox_enabled": get_settings().apple_sandbox_enabled,
            "sandbox_user_count": len({v for v in get_settings().apple_sandbox_user_ids.split(",") if v}),
            "wallet_environment": wallet_environment(),
            "wallet_environment_matches": wallet_environment() == get_app_settings().apple_environment,
            "runtime_running": apple_runtime_state()["running"]}


class MediaPricePublishBody(BaseModel):
    """发布并启用新的媒体价格版本。"""

    prices: dict[str, dict[str, str]] = Field(
        description="媒体价格表，第一层为规范模型 ID，第二层为模型支持的分辨率，值为人民币单价字符串；图片按张、视频按秒计价。单价须大于 0、不超过 10000 元，最多四位小数。"
    )
    expected_version: int | None = Field(
        default=None,
        ge=1,
        description="客户端读取到的当前价格版本，用于防止覆盖并发修改；首次发布时省略或传 null，已有版本时须传入匹配的版本号。",
    )


class MediaPriceActivationBody(BaseModel):
    """在指定价格版本未变化的前提下启用或停用媒体价格表。"""

    enabled: bool = Field(description="是否启用当前媒体价格表。")
    expected_version: int = Field(ge=1, description="客户端读取到的当前价格版本；与服务端不一致时返回 409。")


@router.patch(
    "/settings/billing/media-prices/activation",
    summary="启用或停用媒体价格表",
    description="仅管理员可操作。切换当前媒体价格版本的启用状态；必须提交匹配的 expected_version，版本已变化或尚未发布时返回 409。",
    response_description="返回媒体价格表更新后的 enabled 状态。",
)
async def activate_media_prices(body: MediaPriceActivationBody, _admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    from app.services.media_models.prices import set_pricing_enabled
    await set_pricing_enabled(db, enabled=body.enabled, expected_version=body.expected_version)
    await db.commit()
    return {"enabled": body.enabled}


@router.get(
    "/settings/billing/media-prices",
    summary="获取媒体价格表与模型计价规则",
    description="仅管理员可访问。返回当前价格版本 active_version、启用状态 enabled、价格表 prices 和模型规则 strategies。尚未发布时 active_version 为 null、enabled 为 false，并返回可编辑的初始草稿；读取草稿不会自动发布。",
    response_description="当前媒体价格配置及各模型支持的分辨率、比例、参考素材限制和计费单位。",
)
async def get_media_prices(_admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    from app.services.media_models import strategies
    from app.services.media_models.prices import active_book, initial_draft
    book = await active_book(db, include_disabled=True)
    return {"active_version": book["version"] if book else None,
            "enabled": book["enabled"] if book else False,
            "prices": book["prices"] if book else initial_draft(),
            "strategies": [{"id": strategy.model_id, **strategy.describe()} for strategy in strategies()]}


@router.post(
    "/settings/billing/media-prices",
    summary="发布媒体价格新版本",
    description="仅管理员可操作。校验价格表后创建新版本并立即启用。expected_version 必须匹配当前版本，首次发布时为 null；并发修改导致版本不匹配时返回 409。",
    response_description="发布成功后的版本号 version 与规范化价格表 prices。",
)
async def publish_media_prices(body: MediaPricePublishBody, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    from app.services.media_models.prices import publish_book
    result = await publish_book(db, prices=body.prices, expected_version=body.expected_version, user_id=admin.id)
    await db.commit()
    return result


class AdminUpstreamModelsRequest(BaseModel):
    """按渠道凭证拉取上游 /models 目录。"""

    channel_id: str | None = Field(default=None, max_length=64, description="已保存的渠道 ID；找到渠道时，用其配置补充未提供的地址、密钥和协议。")
    protocol: str = Field(default="auto", max_length=32, description="上游协议，默认 auto；为 auto 时优先沿用渠道协议。旧 ark、volc_tts 协议会转为 TokenFree 模型目录。")
    base_url: str = Field(default="", max_length=512, description="上游 API 基础地址；为空时优先使用指定渠道地址，仍为空则使用 TokenFree 默认地址。")
    api_key: str | None = Field(default=None, max_length=512, description="仅本次查询使用的 API 密钥，不会保存；省略、null 或空白时优先沿用已保存的渠道密钥。")
    capability: str = Field(default="all", max_length=32, description="按生成能力筛选模型：all 为全部，text 为文本，image 为图像，video 为视频，audio 为语音。")


@router.get(
    "/settings/routing",
    response_model=AdminRoutingSettingsOut,
    summary="获取模型路由配置",
    description="仅管理员可访问。返回渠道、逻辑模型、四类默认模型、参考素材数量限制及路由校验信息；渠道密钥不会以明文返回。",
    response_description="当前模型路由配置及校验结果。",
)
async def admin_get_routing_settings(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminRoutingSettingsOut:
    # 读取渠道 + 逻辑模型 + 默认模型完整路由配置
    return await get_admin_routing_settings(db)


@router.patch(
    "/settings/routing",
    response_model=AdminRoutingSettingsSaveOut,
    summary="更新模型路由配置",
    description="仅管理员可操作。更新提交的渠道、逻辑模型、默认模型或参考素材限制，保存时自动同步模型绑定并刷新运行缓存。当前渠道统一为 TokenFree，渠道模型目录采用站点预设；默认模型按有效路由归一化。路由或参考素材配置校验失败时返回 400。",
    response_description="保存后的路由配置与实际应用的配置分组。",
)
async def admin_patch_routing_settings(
    body: AdminRoutingSettingsPatch,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminRoutingSettingsSaveOut:
    # 保存渠道与逻辑路由；保存时自动 sync 逻辑模型绑定
    try:
        settings, applied = await patch_admin_routing_settings(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminRoutingSettingsSaveOut(settings=settings, applied=applied)


@router.get(
    "/settings/models",
    response_model=AdminModelSettingsOut,
    summary="获取模型与运行配置",
    description="仅管理员可访问。读取当前生效的模型、并发、存储、计费和站点配置；数据库配置优先，未设置项沿用环境变量或默认值，模型相关值会结合当前路由解析。所有密钥字段返回空串，使用 has_* 判断是否已配置；readiness 反映路由配置是否就绪，不执行上游连通性测试。",
    response_description="当前生效的脱敏配置、配置来源、更新时间和生成能力就绪状态。",
)
async def admin_get_model_settings(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminModelSettingsOut:
    # 读取当前生效的模型配置（DB 优先，env 兜底）
    return await get_admin_model_settings(db)


@router.patch(
    "/settings/models",
    response_model=AdminModelSettingsSaveOut,
    summary="部分更新模型与运行配置",
    description="仅管理员可操作。仅应用显式提交且非 null 的配置项，普通字符串可用空串覆盖。密钥省略、null 或空白字符串均保留原值；使用对应 clear_* 标记显式清空，同一请求同时提供非空新密钥时以新值为准。敏感字段加密保存，成功后刷新运行缓存；模型相关值还会按路由配置统一处理。",
    response_description="刷新后的脱敏配置与本次实际应用的字段名列表。",
)
async def admin_patch_model_settings(
    body: AdminModelSettingsPatch,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminModelSettingsSaveOut:
    # 部分更新模型配置；密钥留空表示不修改
    try:
        settings, applied = await patch_admin_model_settings(db, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AdminModelSettingsSaveOut(settings=settings, applied_fields=applied)


@router.post(
    "/settings/models/import-env",
    response_model=AdminModelSettingsImportEnvOut,
    summary="从环境配置导入运行设置",
    description="仅管理员可操作。读取进程环境变量、.env 及 Settings 默认值中的全部可管理配置并写入数据库；普通字段会覆盖当前值，空白密钥会跳过以保留已有值，非空密钥加密保存。导入后刷新运行缓存。",
    response_description="导入后的脱敏配置、已导入字段与跳过的空密钥字段列表。",
)
async def admin_import_model_settings_from_env(
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminModelSettingsImportEnvOut:
    # 一键将 .env / 环境变量中的可管理项导入 DB（空密钥跳过，避免覆盖已有密文）
    settings, imported, skipped = await import_admin_model_settings_from_env(db)
    return AdminModelSettingsImportEnvOut(
        settings=settings,
        imported_fields=imported,
        skipped_secret_fields=skipped,
    )


@router.post(
    "/settings/upstream/models",
    summary="查询上游可用模型目录",
    description="仅管理员可访问。使用本次提供的地址和密钥，或指定已保存的渠道，查询 OpenAI 兼容 /models 目录；旧方舟或语音协议地址会转为 TokenFree。结果按能力筛选、去重并按模型 ID 排序，不保存请求凭证；缺少凭证或上游目录查询失败时返回 400。",
    response_description="models 列表，每项包含模型 ID、展示名称 label 和生成能力 capability。",
)
async def admin_list_upstream_models(
    body: AdminUpstreamModelsRequest,
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按渠道协议拉取上游可用模型（TokenFree / OpenAI 兼容）。"""
    try:
        models = await list_upstream_models(
            db,
            channel_id=body.channel_id,
            protocol=body.protocol,
            base_url=body.base_url,
            api_key_override=body.api_key,
            capability=body.capability,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"models": models}
