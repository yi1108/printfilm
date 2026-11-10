"""市场平台投放订单、永久权益和收益账本。"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.models import User
from app.services import epay
from . import storage
from .dependencies import Actor, DB, Visitor, storage_ready
from .models import Asset, ContentOrder, Entitlement, Publication, RevenueConfig, RevenueLedger, Rights, Series, SeriesEpisode, Work
from .schemas import ContentOrderInput
from .service import data, event, fail, now, rights_valid

router = APIRouter()


def _client_ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or (request.client.host if request.client else "127.0.0.1")).split(",")[0].strip()


def _payment_ready() -> bool:
    settings = get_settings()
    return bool(settings.epay_pid and settings.epay_key and settings.epay_api_url)


def _publication_public(item: Publication) -> bool:
    return bool(item.audit_status == "approved" and item.listed and item.sale_type == "platform_unlock" and item.unlock_price_fen > 0 and item.playback_status == "done" and item.playback_manifest_key)


async def _publication_restriction(db: DB, publication: Publication) -> str:
    """购买后的播放保留旧快照，但实时执行封禁与该版本资产的权属限制。"""
    owner = await db.get(User, publication.owner_id)
    if not owner:
        return "作者账号不可用"
    # 账号模型当前没有封禁字段；不引入或修改原用户表。
    if publication.content_type == "work":
        item = await db.get(Work, publication.content_id, populate_existing=True)
        if not item or item.owner_id != publication.owner_id:
            return "作品不可用"
        if item.blocked:
            return "作品已被限制播放"
    elif publication.content_type == "series_episode":
        item = await db.get(SeriesEpisode, publication.content_id, populate_existing=True)
        series = await db.get(Series, item.series_id, populate_existing=True) if item else None
        if not item or not series or item.owner_id != publication.owner_id or series.owner_id != publication.owner_id:
            return "分集不可用"
        if item.blocked or series.blocked:
            return "系列或分集已被限制播放"
    else:
        return "不支持的发布内容"
    rights = (await db.execute(select(Rights).where(Rights.asset_id == publication.asset_id).execution_options(populate_existing=True))).scalar_one_or_none()
    if not rights or rights.owner_id != publication.owner_id or rights.blocked or (rights.valid_until and rights.valid_until <= now()):
        return "该发布版本的权属已受限制"
    return ""


async def _current_sale(db: DB, publication: Publication) -> bool:
    """Publication.listed 只是快照标记，不能代替父内容当前可售状态。"""
    if not _publication_public(publication) or await _publication_restriction(db, publication):
        return False
    if publication.share_bps is None or not 0 <= publication.share_bps <= 10000:
        return False
    if publication.content_type == "work":
        item = await db.get(Work, publication.content_id, populate_existing=True)
        parent = item
    else:
        item = await db.get(SeriesEpisode, publication.content_id, populate_existing=True)
        parent = await db.get(Series, item.series_id, populate_existing=True)
        from .previews import episode_is_free
        if episode_is_free(parent, item):
            return False
    if (item.version != publication.version or item.asset_id != publication.asset_id
            or item.audit_status != "approved" or not item.listed
            or parent.audit_status != "approved" or not parent.listed
            or parent.deleted_at or parent.sale_type != "platform_unlock"):
        return False
    asset = await db.get(Asset, publication.asset_id, populate_existing=True)
    rights = (await db.execute(select(Rights).where(Rights.asset_id == publication.asset_id).execution_options(populate_existing=True))).scalar_one_or_none()
    return bool(asset and asset.owner_id == publication.owner_id and asset.status == "ready" and rights_valid(rights, full=True))


async def _publication_playback(db: DB, user: User, publication: Publication) -> dict:
    entitlement = (await db.execute(select(Entitlement).where(
        Entitlement.user_id == user.id, Entitlement.publication_id == publication.id,
        Entitlement.active.is_(True)))).scalar_one_or_none()
    if not entitlement:
        fail("MARKETPLACE_ENTITLEMENT_REQUIRED", 403)
    restriction = await _publication_restriction(db, publication)
    if restriction:
        fail(restriction, 403)
    if publication.sale_type != "platform_unlock" or publication.audit_status != "approved":
        fail("该发布版本不可播放", 403)
    asset = await db.get(Asset, publication.asset_id)
    if not asset or asset.owner_id != publication.owner_id or asset.status != "ready" or publication.playback_status != "done" or not publication.playback_manifest_key:
        fail("MARKETPLACE_EPISODE_NOT_READY", 409)
    await storage_ready()
    manifest = await _signed_hls_manifest(publication)
    from .config import get_marketplace_settings
    return {"publication_id": publication.id, "manifest": manifest, "kind": "hls", "expires_in": get_marketplace_settings().signed_url_seconds}


async def _signed_hls_manifest(publication: Publication) -> str:
    """重写私有 HLS 分片为短时签名 URL，避免仅签 manifest 后分片 403。"""
    if not publication.playback_manifest_key:
        fail("MARKETPLACE_EPISODE_NOT_READY", 409)
    raw = await __import__("asyncio").to_thread(storage.read, publication.playback_manifest_key)
    text = raw.decode("utf-8")
    prefix = publication.playback_manifest_key.rsplit("/", 1)[0] + "/"
    rewritten: list[str] = []
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#") or value.startswith(("http://", "https://")):
            rewritten.append(line)
            continue
        # 只允许 Worker 生成目录中的相对分片，拒绝路径穿越或外部 URI。
        if value.startswith("/") or ".." in value.split("/"):
            fail("播放清单无效", 502)
        key = prefix + value
        signed = await __import__("asyncio").to_thread(storage.signed, key, "video/mp2t")
        rewritten.append(signed)
    return "\n".join(rewritten) + "\n"


@router.get(
    "/platform/feed", response_model=dict,
    summary='分页获取平台解锁内容列表',
    description='允许访客访问。按发布版本 ID 倒序分页，列出已审核通过、已上架且播放文件已打包的平台解锁发布记录。',
    response_description='发布版本 items 与分页信息 meta，价格金额单位为人民币分。',
)
async def platform_feed(db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    filters = (
        Publication.audit_status == "approved",
        Publication.listed.is_(True),
        Publication.sale_type == "platform_unlock",
        Publication.playback_status == "done",
        Publication.playback_manifest_key.is_not(None),
    )
    query = select(Publication).where(*filters).order_by(Publication.id.desc())
    rows = list((await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all())
    total = (await db.execute(select(func.count()).select_from(Publication).where(*filters))).scalar_one()
    return {"items": [data(row, "id", "content_type", "content_id", "version", "sale_type", "copyright_price_fen", "unlock_price_fen", "share_bps", "created_at") for row in rows], "meta": {"page": page, "page_size": page_size, "total": total}}


@router.get(
    "/platform/episodes/{episode_id}", response_model=dict,
    summary='获取平台收费分集购买详情',
    description='允许访客访问。读取分集当前可售发布版本；登录时同时判断当前用户是否已拥有该版本权益。未公开或不满足可售条件时返回 404。',
    response_description='发布版本详情、entitled 购买权益状态及 playback_ready 播放就绪状态。',
)
async def platform_episode(episode_id: int, db: DB, user: Visitor):
    episode = await db.get(SeriesEpisode, episode_id)
    if not episode:
        fail("分集不存在", 404)
    publication = (await db.execute(select(Publication).where(
        Publication.content_type == "series_episode", Publication.content_id == episode.id,
        Publication.version == episode.version, Publication.audit_status == "approved",
        Publication.listed.is_(True), Publication.sale_type == "platform_unlock",
    ))).scalar_one_or_none()
    if not publication or not await _current_sale(db, publication):
        fail("分集尚未公开", 404)
    entitled = bool(user and (await db.execute(select(Entitlement.id).where(Entitlement.user_id == user.id, Entitlement.publication_id == publication.id, Entitlement.active.is_(True)))).scalar_one_or_none())
    return {**data(publication, "id", "content_type", "content_id", "version", "sale_type", "copyright_price_fen", "unlock_price_fen", "created_at"), "entitled": entitled, "playback_ready": bool(publication.playback_manifest_key)}


@router.get(
    "/platform/works/{work_id}", response_model=dict,
    summary='获取平台收费单视频购买详情',
    description='允许访客访问。读取单视频当前可售发布版本；登录时同时判断当前用户是否已拥有该版本权益。未公开或不满足可售条件时返回 404。',
    response_description='发布版本详情、entitled 购买权益状态及 playback_ready 播放就绪状态。',
)
async def platform_work(work_id: int, db: DB, user: Visitor):
    """单视频平台投放详情；与剧集分集使用相同的发布版本和永久权益模型。"""
    work = await db.get(Work, work_id)
    if not work:
        fail("作品不存在", 404)
    publication = (await db.execute(select(Publication).where(
        Publication.content_type == "work", Publication.content_id == work.id,
        Publication.version == work.version, Publication.audit_status == "approved",
        Publication.listed.is_(True), Publication.sale_type == "platform_unlock"))).scalar_one_or_none()
    if not publication or not await _current_sale(db, publication):
        fail("作品尚未公开", 404)
    entitled = bool(user and (await db.execute(select(Entitlement.id).where(
        Entitlement.user_id == user.id, Entitlement.publication_id == publication.id,
        Entitlement.active.is_(True)))).scalar_one_or_none())
    return {**data(publication, "id", "content_type", "content_id", "version", "sale_type", "copyright_price_fen", "unlock_price_fen", "created_at"), "entitled": entitled, "playback_ready": bool(publication.playback_manifest_key)}


@router.post(
    "/content-orders", response_model=dict,
    summary='创建平台内容解锁订单',
    description='登录后按 publication_id 购买当前可售内容，金额冻结为该发布版本的解锁价格。idempotency_key 重复使用须与原用户、版本和支付方式一致，否则返回 409；已拥有权益时直接返回已购状态。支付不可用时返回 503。',
    response_description='新订单的支付信息，或重复请求的已有订单摘要；金额 amount_fen 单位为人民币分。',
)
async def create_content_order(body: ContentOrderInput, request: Request, db: DB, user: Actor):
    if not _payment_ready():
        fail("MARKETPLACE_PAYMENT_UNAVAILABLE", 503)
    prior = (await db.execute(select(ContentOrder).where(ContentOrder.idempotency_key == body.idempotency_key).with_for_update())).scalar_one_or_none()
    if prior:
        if prior.user_id != user.id or prior.publication_id != body.publication_id or prior.pay_type != body.pay_type:
            fail("幂等键与原请求不一致", 409)
        return {"out_trade_no": prior.out_trade_no, "status": prior.status, "amount_fen": prior.amount_fen}
    publication = (await db.execute(select(Publication).where(Publication.id == body.publication_id).with_for_update())).scalar_one_or_none()
    if not publication:
        fail("内容尚未开放购买", 409)
    existing = (await db.execute(select(Entitlement).where(Entitlement.user_id == user.id, Entitlement.publication_id == publication.id, Entitlement.active.is_(True)))).scalar_one_or_none()
    if existing:
        return {"entitled": True, "publication_id": publication.id, "status": "paid"}
    if not await _current_sale(db, publication):
        fail("内容尚未开放购买", 409)
    out_trade_no = f"MKT{int(time.time())}{user.id:04d}{uuid.uuid4().hex[:10]}"
    inserted = await db.execute(insert(ContentOrder).values(
        out_trade_no=out_trade_no, user_id=user.id, publication_id=publication.id,
        episode_id=publication.content_id if publication.content_type == "series_episode" else None,
        amount_fen=int(publication.unlock_price_fen), pay_type=body.pay_type,
        idempotency_key=body.idempotency_key,
    ).on_conflict_do_nothing(index_elements=[ContentOrder.idempotency_key]).returning(ContentOrder.id))
    order_id = inserted.scalar_one_or_none()
    if order_id is None:
        prior = (await db.execute(select(ContentOrder).where(ContentOrder.idempotency_key == body.idempotency_key))).scalar_one()
        if prior.user_id != user.id or prior.publication_id != publication.id or prior.pay_type != body.pay_type:
            fail("幂等键与原请求不一致", 409)
        return {"out_trade_no": prior.out_trade_no, "status": prior.status, "amount_fen": prior.amount_fen}
    order = await db.get(ContentOrder, order_id)
    await db.commit()
    try:
        notify_url = f"{get_settings().public_base_url.rstrip('/')}/api/marketplace/payments/epay/notify"
        mapi = await epay.create_mapi_payment(out_trade_no=out_trade_no, name=f"数字资产-{publication.content_id}", money_yuan=epay.money_yuan_from_fen(order.amount_fen), pay_type=body.pay_type, clientip=_client_ip(request), notify_url=notify_url)
        fields = epay.build_submit_fields(out_trade_no=out_trade_no, name=f"数字资产-{publication.content_id}", money_yuan=epay.money_yuan_from_fen(order.amount_fen), pay_type=body.pay_type, clientip=_client_ip(request), notify_url=notify_url)
    except ValueError as exc:
        await db.execute(select(ContentOrder).where(ContentOrder.id == order.id).with_for_update())
        order.status = "failed"
        await db.commit()
        fail(str(exc), 503)
    return {"out_trade_no": order.out_trade_no, "status": order.status, "amount_fen": order.amount_fen, "pay_type": order.pay_type, "trade_no": mapi.get("trade_no") or "", "qrcode": mapi.get("qrcode") or "", "payurl": mapi.get("payurl") or "", "qr_payload": mapi.get("qr_payload") or "", "pay_mode": mapi.get("pay_mode") or "redirect", "submit_url": epay.submit_url(fields)}


@router.get(
    "/content-orders/{out_trade_no}", response_model=dict,
    summary='查询我的内容解锁订单',
    description='仅订单所属用户可按 out_trade_no 查询；不存在或属于他人的订单返回 404。',
    response_description='订单金额、发布版本、支付方式、状态、交易号与支付时间。',
)
async def get_content_order(out_trade_no: str, db: DB, user: Actor):
    order = (await db.execute(select(ContentOrder).where(ContentOrder.out_trade_no == out_trade_no, ContentOrder.user_id == user.id))).scalar_one_or_none()
    if not order:
        fail("订单不存在", 404)
    return data(order, "out_trade_no", "publication_id", "episode_id", "amount_fen", "pay_type", "status", "trade_no", "paid_at", "created_at")


@router.get(
    "/entitlements", response_model=dict,
    summary='获取我的有效内容购买权益',
    description='登录后列出本人 active=true 的购买权益及对应发布版本，按权益 ID 倒序返回。权益绑定购买时的发布版本。',
    response_description='有效权益 items，包含内容类型、内容 ID 与发布版本号。',
)
async def list_entitlements(db: DB, user: Actor):
    rows = list((await db.execute(select(Entitlement, Publication).join(Publication, Publication.id == Entitlement.publication_id).where(Entitlement.user_id == user.id, Entitlement.active.is_(True)).order_by(Entitlement.id.desc()))).all())
    return {"items": [{**data(entitlement, "id", "publication_id", "episode_id", "created_at"), **data(publication, "content_type", "content_id", "version", "unlock_price_fen")} for entitlement, publication in rows]}


@router.get(
    "/platform/episodes/{episode_id}/playback", response_model=dict, dependencies=[],
    summary='获取已购分集当前版本播放清单',
    description='仅已登录且拥有该分集当前公开发布版本有效权益的用户可访问。校验实时封禁、权属与播放就绪状态后，生成含短期签名分片链接的 HLS 清单。',
    response_description='publication_id、HLS 文本 manifest、kind=hls 与有效秒数 expires_in。',
)
async def episode_playback(episode_id: int, db: DB, user: Actor):
    episode = await db.get(SeriesEpisode, episode_id)
    if not episode:
        fail("分集不存在", 404)
    publication = (await db.execute(select(Publication).where(
        Publication.content_type == "series_episode", Publication.content_id == episode.id,
        Publication.version == episode.version, Publication.audit_status == "approved",
        Publication.listed.is_(True), Publication.sale_type == "platform_unlock",
    ))).scalar_one_or_none()
    if not publication or publication.sale_type != "platform_unlock":
        fail("分集尚未公开", 404)
    return await _publication_playback(db, user, publication)


@router.get(
    "/platform/works/{work_id}/playback", response_model=dict, dependencies=[],
    summary='获取已购单视频当前版本播放清单',
    description='仅已登录且拥有该作品当前公开发布版本有效权益的用户可访问。校验实时封禁、权属与播放就绪状态后，生成含短期签名分片链接的 HLS 清单。',
    response_description='publication_id、HLS 文本 manifest、kind=hls 与有效秒数 expires_in。',
)
async def work_playback(work_id: int, db: DB, user: Actor):
    work = await db.get(Work, work_id)
    if not work:
        fail("作品不存在", 404)
    publication = (await db.execute(select(Publication).where(
        Publication.content_type == "work", Publication.content_id == work.id,
        Publication.version == work.version, Publication.audit_status == "approved",
        Publication.listed.is_(True), Publication.sale_type == "platform_unlock"))).scalar_one_or_none()
    if not publication or publication.sale_type != "platform_unlock":
        fail("作品尚未公开", 404)
    return await _publication_playback(db, user, publication)


@router.get(
    "/platform/publications/{publication_id}/playback", response_model=dict,
    summary='按已购发布版本获取播放清单',
    description='登录后从购买权益打开对应发布版本。作者后续编辑或主动下架不撤销已购版本播放；仍实时检查有效权益、内容封禁、该版本权属与媒体就绪状态。无权益或受限制返回 403，文件未就绪返回 409。',
    response_description='publication_id、HLS 文本 manifest、kind=hls 与有效秒数 expires_in。',
)
async def publication_playback(publication_id: int, db: DB, user: Actor):
    """从永久权益打开购买时版本；作者编辑、主动下架不撤销已购在线播放。"""
    publication = await db.get(Publication, publication_id)
    if not publication:
        fail("发布版本不存在", 404)
    return await _publication_playback(db, user, publication)


def _notify_success(params: dict[str, str]) -> bool:
    return str(params.get("trade_status") or params.get("status") or "").upper() in {"TRADE_SUCCESS", "SUCCESS", "1"}


async def ensure_paid_order_revenue(db, order, publication):
    if await db.scalar(select(RevenueLedger.id).where(RevenueLedger.order_id == order.id)):
        return False
    share = publication.share_bps
    if share is None or not 0 <= share <= 10000:
        return False
    platform = order.amount_fen * share // 10000
    db.add(RevenueLedger(order_id=order.id, publication_id=publication.id, owner_id=publication.owner_id,
        gross_fen=order.amount_fen, platform_fen=platform, creator_fen=order.amount_fen-platform, share_bps=share))
    await db.flush()
    return True


@router.get(
    "/payments/epay/notify",
    response_class=PlainTextResponse,
    summary='接收易支付内容订单异步通知',
    description='供支付服务回调，支持 GET 查询参数与 POST 表单。校验签名、支付结果、订单和人民币金额后确认付款，幂等建立对应发布版本权益并记录分成；同一版本重复购买不重复创建权益或收益记录。',
    response_description='纯文本 success 或 fail；签名、金额、订单或支付配置异常时使用相应错误状态码。',
)
@router.post(
    "/payments/epay/notify",
    response_class=PlainTextResponse,
    summary='接收易支付内容订单异步通知',
    description='供支付服务回调，支持 GET 查询参数与 POST 表单。校验签名、支付结果、订单和人民币金额后确认付款，幂等建立对应发布版本权益并记录分成；同一版本重复购买不重复创建权益或收益记录。',
    response_description='纯文本 success 或 fail；签名、金额、订单或支付配置异常时使用相应错误状态码。',
)
async def epay_notify(request: Request, db: DB) -> PlainTextResponse:
    if not _payment_ready():
        return PlainTextResponse("fail", status_code=503)
    if request.method == "POST":
        form = await request.form()
        params = {key: str(value) for key, value in form.items()}
    else:
        params = {key: str(value) for key, value in request.query_params.items()}
    if not epay.verify(params):
        return PlainTextResponse("fail", status_code=400)
    if not _notify_success(params):
        return PlainTextResponse("success")
    trade_no = str(params.get("out_trade_no") or "")
    owner_id = await db.scalar(select(ContentOrder.user_id).where(ContentOrder.out_trade_no == trade_no))
    if owner_id is not None:
        await db.execute(select(User).where(User.id == owner_id).with_for_update())
    order = (await db.execute(select(ContentOrder).where(ContentOrder.out_trade_no == trade_no).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if not order:
        return PlainTextResponse("fail", status_code=404)
    if order.pay_type not in ("alipay", "wxpay"):
        return PlainTextResponse("fail", status_code=400)
    try:
        amount = Decimal(str(params.get("money") or "")) * 100
        if not amount.is_finite() or amount != amount.to_integral_value():
            raise ValueError("invalid amount")
        paid_fen = int(amount)
    except (ValueError, InvalidOperation):
        return PlainTextResponse("fail", status_code=400)
    if paid_fen != order.amount_fen:
        return PlainTextResponse("fail", status_code=400)
    if order.status == "paid":
        return PlainTextResponse("success")
    # Serialize callbacks for the same publication as well as the order. Two
    # different checkout attempts must not race the unique permanent entitlement.
    publication = (await db.execute(select(Publication).where(
        Publication.id == order.publication_id).with_for_update())).scalar_one_or_none()
    if not publication:
        return PlainTextResponse("fail", status_code=404)
    # A verified payment belongs to its frozen order, even if the author has
    # since edited/unlisted the content or an operator has blocked playback.
    order.status, order.trade_no, order.paid_at = "paid", str(params.get("trade_no") or params.get("transaction_id") or "") or None, datetime.now(timezone.utc)
    restriction = await _publication_restriction(db, publication)
    if restriction or publication.audit_status != "approved":
        event(db, order.user_id, "content_order", order.id, "paid_restricted_review",
              restriction or "付款时发布版本已受审核限制", publication.version)
    # Two checkout attempts can race before the first callback creates the
    # entitlement.  The unique entitlement is the idempotency boundary for a
    # user's permanent access; acknowledge the later payment without creating
    # a second entitlement or revenue ledger row.
    existing_entitlement = (await db.execute(select(Entitlement).where(
        Entitlement.user_id == order.user_id,
        Entitlement.publication_id == publication.id,
    ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if existing_entitlement:
        prior_order = await db.get(ContentOrder, existing_entitlement.order_id) if existing_entitlement.order_id else None
        if not existing_entitlement.active:
            existing_entitlement.active, existing_entitlement.order_id = True, order.id
            await ensure_paid_order_revenue(db, order, publication)
        elif prior_order and prior_order.pay_type == "platform_balance":
            # Preserve this independent paid grant if the Apple-funded grant is revoked later.
            existing_entitlement.order_id = order.id
        event(db, order.user_id, "content_order", order.id, "duplicate_purchase_paid",
              "同一发布版本已有权益，本次付款已确认，需人工核对重复收款；不重复计创作者收益", publication.version)
        await db.commit()
        return PlainTextResponse("success")
    entitlement = Entitlement(user_id=order.user_id, publication_id=publication.id, episode_id=order.episode_id, order_id=order.id)
    db.add(entitlement)
    share = publication.share_bps
    if share is None:
        # Legacy checkout records may predate frozen revenue shares. Confirm
        # the cash receipt without inventing an allocation if no config exists.
        config = await db.get(RevenueConfig, 1)
        share = config.platform_share_bps if config else None
        event(db, order.user_id, "content_order", order.id, "paid_legacy_share_review",
              "历史发布版本没有冻结分成；已确认付款及权益，需要人工核对分成", publication.version)
    if share is None or not 0 <= int(share) <= 10000:
        await db.commit()
        return PlainTextResponse("success")
    platform_fen = order.amount_fen * int(share) // 10000
    ledger = RevenueLedger(order_id=order.id, publication_id=publication.id, owner_id=publication.owner_id, gross_fen=order.amount_fen, platform_fen=platform_fen, creator_fen=order.amount_fen - platform_fen, share_bps=int(share))
    db.add(ledger)
    await db.commit()
    return PlainTextResponse("success")

