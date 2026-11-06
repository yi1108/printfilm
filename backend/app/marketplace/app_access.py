"""App 统一内容和环境权益检查，供内容、播放与观影币解锁共用。"""
from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select

from . import storage
from .config import is_marketplace_enabled
from .models import Asset, ContentOrder, Entitlement, Publication, Rights, Series, SeriesEpisode, Work
from .service import rights_valid


def error(code: str, message: str, status: int = 400):
    """App 错误保留稳定编码和中文说明。"""
    raise HTTPException(status, {"code": code, "message": message})


def app_open() -> bool:
    """入口关闭只影响新发现和新消费，不用于吞掉已付款交易。"""
    from .app_settings import is_app_enabled
    return bool(is_marketplace_enabled() and is_app_enabled())


def require_app_open():
    """未开放时不向 App 暴露市场草稿。"""
    if not app_open():
        error("MARKETPLACE_APP_UNAVAILABLE", "App 视频服务尚未开放", 404)


def require_social_open():
    from .app_settings import get_app_settings
    if not app_open() or not get_app_settings().social_enabled:
        error("MARKETPLACE_SOCIAL_UNAVAILABLE", "互动服务尚未开放", 404)


def environment() -> str:
    """支付环境只由服务器配置决定，不读取客户端字段。"""
    from .app_settings import get_app_settings
    value = get_app_settings().apple_environment
    return value.value if hasattr(value, "value") else str(value)


def entitlement_filters(user_id: int):
    """币权益只认当前环境；旧易支付及无订单历史权益保留。"""
    from .app_models import CoinGrant
    coin = select(CoinGrant.publication_id).where(CoinGrant.user_id == user_id,
        CoinGrant.environment == environment(), CoinGrant.active.is_(True))
    legacy = select(Entitlement.publication_id).outerjoin(ContentOrder, ContentOrder.id == Entitlement.order_id).where(
        Entitlement.user_id == user_id, Entitlement.active.is_(True),
        or_(ContentOrder.pay_type.in_(("alipay", "wxpay")), and_(Entitlement.order_id.is_(None),
            ~exists().where(CoinGrant.user_id == user_id, CoinGrant.publication_id == Entitlement.publication_id))))
    return or_(Publication.id.in_(coin), Publication.id.in_(legacy))


async def has_entitlement(db, user_id: int, publication_id: int) -> bool:
    """客户端声明、Sandbox 币授权均不能代替当前环境真实权益。"""
    from .coin_service import has_access
    return await has_access(db, user_id, publication_id, environment())


def author_filter(model, user_id: int | None):
    """屏蔽作者只影响发现，不影响已购记录和已购播放。"""
    from .app_models import AuthorBlock
    return ~exists().where(AuthorBlock.user_id == user_id, AuthorBlock.author_id == model.owner_id) if user_id else True


def work_query(user_id=None):
    """免费和平台投放与 Web 共用审核、短试看、版权和实时限制条件。"""
    from .service import public_work_filters
    return select(Work).join(Asset, Work.asset_id == Asset.id).join(Rights, Rights.asset_id == Asset.id).where(
        *public_work_filters(), Work.sale_type.in_(("free", "platform_unlock")),
        Asset.owner_id == Work.owner_id, Rights.owner_id == Work.owner_id, author_filter(Work, user_id))


def series_query(user_id=None):
    """系列整体审核，不能绕过任意一集的封禁或失效版权材料。"""
    from .series import public_series_filters
    return select(Series).where(*public_series_filters(), Series.sale_type.in_(("free", "platform_unlock")),
                                author_filter(Series, user_id))


async def current_content(db, kind: str, content_id: int, user_id=None):
    """公开详情、试看和新解锁从同一当前版本入口解析。"""
    if kind == "work":
        item = await db.scalar(work_query(user_id).where(Work.id == content_id))
        parent = item
        free = bool(item and item.sale_type == "free")
    elif kind == "series_episode":
        item = await db.get(SeriesEpisode, content_id)
        parent = await db.scalar(series_query(user_id).where(Series.id == item.series_id)) if item else None
        from .previews import episode_is_free
        free = bool(item and parent and episode_is_free(parent, item))
    else:
        item = parent = None
        free = False
    if not item or not parent:
        error("MARKETPLACE_CONTENT_UNAVAILABLE", "内容不存在或暂不可访问", 404)
    asset = await db.get(Asset, item.asset_id)
    publication = await db.scalar(select(Publication).where(Publication.content_type == kind,
        Publication.content_id == item.id, Publication.version == item.version,
        Publication.asset_id == item.asset_id, Publication.audit_status == "approved"))
    return item, parent, asset, publication, free


async def purchased_content(db, publication: Publication, user_id: int):
    """旧购买版本不要求作者当前上架，但持续执行该资产的权属和封禁限制。"""
    from .commerce import _publication_restriction
    if not await has_entitlement(db, user_id, publication.id):
        error("MARKETPLACE_ENTITLEMENT_REQUIRED", "请先解锁该发布版本", 403)
    restriction = await _publication_restriction(db, publication)
    rights = await db.scalar(select(Rights).where(Rights.asset_id == publication.asset_id))
    if restriction or not rights_valid(rights, full=True) or publication.audit_status != "approved":
        error("MARKETPLACE_CONTENT_RESTRICTED", restriction or "该发布版本的版权材料已受限制", 403)
    asset = await db.get(Asset, publication.asset_id)
    if not asset or asset.status != "ready" or asset.owner_id != publication.owner_id:
        error("MARKETPLACE_EPISODE_NOT_READY", "该发布版本的视频尚未就绪", 409)
    return asset
