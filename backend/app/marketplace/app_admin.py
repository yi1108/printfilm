"""App 与苹果内购运营，不随公开市场开关停用财务查询。"""
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, update
from app.models import User
from app.services.billing.pricing import sku_by_id

from app.models_wallet import WalletEvent, WalletFundingLot
from .app_models import AppleProduct, AppleSettlement, AppleTransaction, AppPayout, CoinUnlock, CreatorAccount, RevenueAdjustment
from .app_social_models import AppComment, AppCommentAction, AppCommentReport, AppContentStats
from .coin_service import app_fail, check_environment
from .dependencies import Admin, DB
from .models import RevenueLedger
from .service import event

router = APIRouter()
Environment = Literal["Production", "Sandbox"]


def _sku_snapshot(sku_id: str) -> dict:
    """冻结当前Web套餐的到账额度与实付金额，历史Apple交易不能随价格修改。"""
    sku = sku_by_id(sku_id)
    if not sku:
        app_fail("MARKETPLACE_IAP_PRODUCT_BINDING_REQUIRED", "Web充值套餐不存在，不能绑定苹果商品。", 409)
    return {"id": sku["id"], "name": sku["name"], "amount_fen": int(sku["amount_fen"]), "credit_fen": int(sku["credit_fen"])}


class ProductInput(BaseModel):
    """苹果商品绑定现有Web套餐，赠送额度也必须原样冻结；已使用映射不可改。"""
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._-]+$")
    sku_id: str = Field(min_length=1, max_length=64)
    coins: int = Field(gt=0, le=100_000_000, strict=True)
    price_fen: int = Field(gt=0, le=100_000_000, strict=True)
    enabled: bool = False

class SettlementInput(BaseModel):
    """管理员逐批确认苹果财务报告，不提供无凭据的调账入口。"""
    model_config = ConfigDict(extra="forbid")
    environment: Environment
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    transaction_ids: list[int] = Field(min_length=1, max_length=500)
    channel_fee_fen: int = Field(ge=0, strict=True)
    tax_fen: int = Field(ge=0, strict=True)
    received_fen: int = Field(strict=True)
    note: str = Field(min_length=1, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.transaction_ids)) != len(self.transaction_ids) or any(i <= 0 for i in self.transaction_ids):
            raise ValueError("交易编号须为不重复的正整数。")
        return self


class PayoutInput(BaseModel):
    """人工打款金额须与所选账目及抵扣完全一致。"""
    model_config = ConfigDict(extra="forbid")
    environment: Environment
    owner_id: int = Field(gt=0)
    ledger_ids: list[int] = Field(min_length=1, max_length=500)
    amount_fen: int = Field(ge=0, strict=True)
    note: str = Field(min_length=1, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.ledger_ids)) != len(self.ledger_ids) or any(i <= 0 for i in self.ledger_ids):
            raise ValueError("收益编号须为不重复的正整数。")
        return self


class FundingReviewInput(BaseModel):
    """Web充值来源须以真实收款报告核对，不增减用户余额。"""
    model_config = ConfigDict(extra="forbid")
    lot_id: int = Field(gt=0)
    channel_fee_fen: int = Field(ge=0, strict=True)
    tax_fen: int = Field(ge=0, strict=True)
    received_fen: int = Field(strict=True)
    note: str = Field(min_length=1, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class CommentModerationInput(BaseModel):
    action: Literal["hide", "restore", "delete"]
    reason: str = Field(min_length=1, max_length=300)


def view(row, fields):
    """仅序列化明确白名单，永不向后台回显密钥或签名交易正文。"""
    return {name: getattr(row, name) for name in fields.split()}


async def listing(db, model, fields, environment, page, page_size, status="", user_id=None):
    """后台列表均服务端筛选分页。"""
    conditions = []
    if hasattr(model, "environment"):
        conditions.append(model.environment == environment)
    if status and hasattr(model, "status"):
        conditions.append(model.status == status)
    if user_id and hasattr(model, "user_id"):
        conditions.append(model.user_id == user_id)
    query = select(model).where(*conditions)
    rows = list((await db.execute(query.order_by(model.id.desc()).offset((page-1)*page_size).limit(page_size))).scalars())
    total = (await db.execute(select(func.count()).select_from(model).where(*conditions))).scalar_one()
    return {"items": [view(row, fields) for row in rows], "meta": {"page": page, "page_size": page_size, "total": total}}


@router.get("/summary", response_model=dict)
async def summary(db: DB, user: Admin, environment: Environment = "Production"):
    """配置可用不等于真实联调成功；只报告非敏感状态。"""
    from .app_settings import get_app_settings, is_app_enabled
    from .apple_models import AppleNotification
    from .apple_client import apple_configured
    from .app_finance import eligible_condition
    from app.services.billing import wallet
    config = get_app_settings()
    app_enabled = is_app_enabled()
    visible_balance = (await db.execute(select(func.coalesce(func.sum(User.balance_fen), 0)))).scalar_one() if environment == config.apple_environment else None
    if not wallet.enabled():
        return {"environment": environment, "app_enabled": app_enabled, "iap_enabled": False,
                "unified_wallet_enabled": False, "wallet_balance_fen": visible_balance,
                "wallet_balance_coins": visible_balance, "topup_count": 0,
                "pending_notifications": 0, "payout_due_fen": None, "creator_debt_fen": 0,
                "production_ready": False}
    owner_due = select(RevenueLedger.owner_id.label("owner_id"), func.sum(RevenueLedger.creator_fen).label("amount")).join(
        CoinUnlock, CoinUnlock.order_id == RevenueLedger.order_id).where(
        CoinUnlock.environment == environment, *eligible_condition()).group_by(RevenueLedger.owner_id).subquery()
    due = (await db.execute(select(func.coalesce(func.sum(func.greatest(0,
        owner_due.c.amount - func.coalesce(CreatorAccount.debt_fen, 0))), 0)).select_from(owner_due).outerjoin(
        CreatorAccount, (CreatorAccount.owner_id == owner_due.c.owner_id) & (CreatorAccount.environment == environment)))).scalar_one()
    debt = (await db.execute(select(func.coalesce(func.sum(CreatorAccount.debt_fen), 0)).where(CreatorAccount.environment == environment))).scalar_one()
    return {"environment": environment, "app_enabled": app_enabled, "iap_enabled": config.apple_iap_enabled,
            "unified_wallet_enabled": True, "wallet_balance_fen": visible_balance, "wallet_balance_coins": visible_balance,
            "topup_count": (await db.execute(select(func.count()).select_from(AppleTransaction).where(AppleTransaction.environment == environment))).scalar_one(),
            "pending_notifications": (await db.execute(select(func.count()).select_from(AppleNotification).where(AppleNotification.environment == environment, AppleNotification.status.in_(("pending", "running", "failed"))))).scalar_one(),
            "payout_due_fen": due, "creator_debt_fen": debt,
            "production_ready": config.apple_environment == "Production" and apple_configured()}


@router.get("/products", response_model=dict)
async def products(db: DB, user: Admin, environment: Environment = "Production", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    return await listing(db, AppleProduct, "id product_id sku_id sku_snapshot coins price_fen enabled created_at", environment, page, page_size)


@router.put("/products", response_model=dict)
async def save_product(body: ProductInput, db: DB, user: Admin):
    """只维护本地商品映射，不冒充已在苹果创建或审核商品。"""
    from .coin_service import lock_creator
    await lock_creator(db, 0, "Production")
    if body.enabled and await db.scalar(select(AppleProduct.id).where(
            AppleProduct.sku_id == body.sku_id, AppleProduct.enabled.is_(True),
            AppleProduct.product_id != body.product_id).limit(1)):
        app_fail("MARKETPLACE_IAP_PRODUCT_CONFLICT", "该套餐已有启用的苹果商品，请先停用旧商品后再启用新商品。", 409)
    item = (await db.execute(select(AppleProduct).where(AppleProduct.product_id == body.product_id).with_for_update())).scalar_one_or_none()
    if item:
        if item.coins != body.coins or item.price_fen != body.price_fen:
            app_fail("MARKETPLACE_IAP_PRODUCT_IMMUTABLE", "已创建的商品币数和价格映射不可改写，请创建新的苹果商品。", 409)
        if item.sku_id and item.sku_id != body.sku_id:
            app_fail("MARKETPLACE_IAP_PRODUCT_IMMUTABLE", "已创建商品绑定的Web套餐不可改写，请创建新的苹果商品。", 409)
        if not item.sku_snapshot:
            snapshot = _sku_snapshot(body.sku_id)
            if snapshot["credit_fen"] != body.coins:
                app_fail("MARKETPLACE_IAP_PRODUCT_BINDING_REQUIRED", "商品额度与Web套餐不一致，请创建新的苹果商品。", 409)
            item.sku_id, item.sku_snapshot = body.sku_id, snapshot
        item.enabled = body.enabled
    else:
        snapshot = _sku_snapshot(body.sku_id)
        if snapshot["credit_fen"] != body.coins:
            app_fail("MARKETPLACE_IAP_PRODUCT_BINDING_REQUIRED", "商品额度与Web套餐不一致，赠额须与共同套餐相同。", 409)
        item = AppleProduct(**body.model_dump(), sku_snapshot=snapshot)
        db.add(item)
    await db.flush()
    event(db, user.id, "apple_product", item.id, "configured", "更新商品映射；苹果可售状态须独立验证")
    await db.commit()
    return view(item, "id product_id sku_id sku_snapshot coins price_fen enabled created_at")


@router.post("/settlements", response_model=dict)
async def create_settlement(body: SettlementInput, db: DB, user: Admin):
    """按真实财务报告对账，重复提交不重复确认交易。"""
    from .app_finance import reconcile
    item = await reconcile(db, body, user.id)
    event(db, user.id, "apple_settlement", item.id, "reconciled", body.note)
    await db.commit()
    return view(item, "id environment month gross_fen channel_fee_fen tax_fen received_fen note created_at")


@router.post("/funding-reviews", response_model=dict)
async def review_funding(body: FundingReviewInput, db: DB, user: Admin):
    """登记Web资金来源实收核对，不复用Apple通知修改付款结果。"""
    from .unified_admin import review_web_funding
    item = await review_web_funding(db, body, user.id)
    event(db, user.id, "wallet_funding_review", item.id, "reconciled", body.note)
    await db.commit()
    return view(item, "id source_type source_ref gross_fen channel_fee_fen tax_fen received_fen note reviewed_at")


@router.post("/payouts", response_model=dict)
async def record_payout(body: PayoutInput, db: DB, user: Admin):
    """此接口不转账，管理员须核对已完成的线下打款。"""
    from .app_finance import create_payout
    item = await create_payout(db, body, user.id)
    event(db, user.id, "app_payout", item.id, "recorded", body.note)
    await db.commit()
    return view(item, "id owner_id environment amount_fen debt_offset_fen status note created_at")


@router.get("/revenue", response_model=dict)
async def revenue(db: DB, user: Admin, environment: Environment = "Production", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), owner_id: int | None = Query(None, gt=0), user_id: int | None = Query(None, gt=0)):
    """查询统一余额解锁收入，来源可能为Web、Apple或赠额，按来源实收对账。"""
    from .app_finance import eligible_condition
    conditions = [CoinUnlock.environment == environment]
    if owner_id or user_id:
        conditions.append(RevenueLedger.owner_id == (owner_id or user_id))
    query = select(RevenueLedger, CoinUnlock).join(CoinUnlock, CoinUnlock.order_id == RevenueLedger.order_id).where(*conditions)
    rows = (await db.execute(query.order_by(RevenueLedger.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    eligible = set((await db.execute(select(RevenueLedger.id).join(CoinUnlock, CoinUnlock.order_id == RevenueLedger.order_id).where(
        *conditions, RevenueLedger.id.in_([row.id for row, _ in rows]), *eligible_condition()))).scalars())
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    return {"items": [{**view(row, "id owner_id publication_id gross_fen creator_fen platform_fen settlement_status created_at"), "environment": item.environment, "eligible": row.id in eligible} for row, item in rows], "meta": {"page": page, "page_size": page_size, "total": total}}


@router.get("/{kind}", response_model=dict)
async def records(kind: str, db: DB, user: Admin, environment: Environment = "Production", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), status: str = "", user_id: int | None = Query(None, gt=0)):
    """金融和媒体记录白名单；未知 kind 不能反射访问任意表。"""
    from .apple_models import AppleNotification
    from .app_media_models import AppMedia
    if kind in ("wallets", "wallet-entries", "funding-sources", "debts", "repayments", "recharge-orders", "funding-reviews"):
        from .unified_admin import records as unified_records
        return await unified_records(db, kind, environment, page, page_size, status, user_id)
    choices = {
        "transactions": (AppleTransaction, "id user_id environment transaction_id product_id coins amount_fen status settlement_status anomaly created_at"),
        "notifications": (AppleNotification, "id environment notification_uuid notification_type transaction_id status attempts error created_at"),
        "wallets": (WalletFundingLot, "id user_id source_type source_ref total_units total_amount_fen active settlement_status created_at"),
        "wallet-entries": (WalletEvent, "id user_id kind delta_fen frozen_delta_fen balance_after frozen_after reference created_at"),
        "unlock-orders": (CoinUnlock, "id user_id environment order_id publication_id coins amount_fen status created_at"),
        "adjustments": (RevenueAdjustment, "id owner_id environment unlock_id gross_fen platform_fen creator_fen reason created_at"),
        "settlements": (AppleSettlement, "id environment month gross_fen channel_fee_fen tax_fen received_fen note created_at"),
        "payouts": (AppPayout, "id owner_id environment amount_fen debt_offset_fen status note created_at"),
        "media": (AppMedia, "id content_type content_id version variant status attempts error created_at"),
    }
    if kind not in choices:
        app_fail("MARKETPLACE_RECORD_NOT_FOUND", "业务记录不存在。", 404)
    model, fields = choices[kind]
    return await listing(db, model, fields, environment, page, page_size, status, user_id)


@router.post("/notifications/{notification_id}/retry", response_model=dict)
async def retry_notification(notification_id: int, db: DB, user: Admin):
    """只重试已验证入库的通知，不允许手工伪造退款。"""
    from .apple_models import AppleNotification
    item = (await db.execute(select(AppleNotification).where(AppleNotification.id == notification_id).with_for_update())).scalar_one_or_none()
    if not item:
        app_fail("MARKETPLACE_RECORD_NOT_FOUND", "通知不存在。", 404)
    if item.status not in ("failed", "pending"):
        app_fail("MARKETPLACE_NOTIFICATION_NOT_RETRYABLE", "通知已完成或正在处理，请勿重复重试。", 409)
    item.status, item.attempts, item.error = "pending", 0, ""
    item.lease_token = item.lease_until = item.next_attempt_at = None
    event(db, user.id, "apple_notification", item.id, "retry")
    await db.commit()
    return {"ok": True}


@router.post("/media/{media_id}/retry", response_model=dict)
async def retry_media(media_id: int, db: DB, user: Admin):
    """失败任务重新排队；成功对象、内容版本和源文件均不被改写。"""
    from .app_media_models import AppMedia
    item = (await db.execute(select(AppMedia).where(AppMedia.id == media_id).with_for_update())).scalar_one_or_none()
    if not item or item.status != "failed":
        app_fail("MARKETPLACE_MEDIA_NOT_RETRYABLE", "只有失败的播放准备任务可以重试。", 409)
    item.status, item.attempts, item.error = "pending", 0, ""
    item.lease_token = item.lease_until = None
    event(db, user.id, "app_media", item.id, "retry")
    await db.commit()
    return {"ok": True}


@router.get("/social/stats", response_model=dict)
async def social_stats(db: DB, user: Admin, target_type: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    query = select(AppContentStats)
    if target_type:
        query = query.where(AppContentStats.target_type == target_type)
    rows = list((await db.scalars(query.order_by(AppContentStats.updated_at.desc()).offset((page - 1) * page_size).limit(page_size))).all())
    return {"items": [{"id": r.id, "target_type": r.target_type, "target_id": r.target_id, "like_count": r.like_count, "comment_count": r.comment_count, "favorite_count": r.favorite_count} for r in rows]}


@router.get("/social/comments", response_model=dict)
async def social_comments(db: DB, user: Admin, status: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    query = select(AppComment)
    if status:
        query = query.where(AppComment.status == status)
    rows = list((await db.scalars(query.order_by(AppComment.id.desc()).offset((page - 1) * page_size).limit(page_size))).all())
    return {"items": [{"id": r.id, "user_id": r.user_id, "target_type": r.target_type, "target_id": r.target_id, "text": r.text, "status": r.status, "created_at": r.created_at} for r in rows]}


@router.post("/social/comments/{comment_id}/moderate", response_model=dict)
async def moderate_comment(comment_id: int, body: CommentModerationInput, db: DB, user: Admin):
    row = await db.get(AppComment, comment_id)
    if not row:
        app_fail("MARKETPLACE_COMMENT_NOT_FOUND", "评论不存在。", 404)
    old_status = row.status
    row.status = {"hide": "hidden", "restore": "visible", "delete": "deleted"}[body.action]
    row.deleted_by = user.id if body.action != "restore" else None
    row.deleted_reason = body.reason
    db.add(AppCommentAction(comment_id=row.id, operator_id=user.id, action=body.action, reason=body.reason))
    if old_status == "visible" and row.status != "visible":
        await db.execute(update(AppContentStats).where(AppContentStats.target_type == row.target_type, AppContentStats.target_id == row.target_id).values(comment_count=func.greatest(AppContentStats.comment_count - 1, 0)))
    elif old_status != "visible" and row.status == "visible":
        await db.execute(update(AppContentStats).where(AppContentStats.target_type == row.target_type, AppContentStats.target_id == row.target_id).values(comment_count=AppContentStats.comment_count + 1))
    await db.commit()
    return {"ok": True, "id": row.id, "status": row.status}
