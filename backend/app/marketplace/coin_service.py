"""App 兼容层：充值和解锁共用平台余额，事务由调用方提交。"""
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models import User
from app.services.billing import wallet
from .app_models import AppleProduct, AppleTransaction, AppleTransactionRevision, CoinGrant, CoinUnlock, CreatorAccount
from .models import ContentOrder, Entitlement, Publication, RevenueLedger
from .service import now

ENVIRONMENTS = ("Production", "Sandbox")
PRICE_DIFFERENCE_ANOMALY = "苹果实际付款与商品参考价格不一致，请核对财务报告。"


def app_fail(code: str, message: str, status: int = 400):
    """稳定错误编码和中文原因，不向客户端返回底层异常。"""
    raise HTTPException(status, {"code": code, "message": message})


def check_environment(environment: str) -> None:
    """运营可以读取历史环境，资金操作另由统一钱包核对部署环境。"""
    if environment not in ENVIRONMENTS:
        app_fail("MARKETPLACE_IAP_ENVIRONMENT_INVALID", "交易环境不正确。")


async def funds_call(operation):
    """独立挂载 App 路由时也将资金错误转换为稳定 HTTP 响应。"""
    try:
        return await operation
    except wallet.WalletError as exc:
        app_fail(exc.code, exc.message, exc.status)


async def lock_wallet(db, user_id: int, environment: str) -> User:
    """兼容原调用名称，唯一账户锁和余额来自 users，不创建旧币钱包。"""
    check_environment(environment)
    return await funds_call(wallet.lock_account(db, user_id, environment))


async def lock_creator(db, owner_id: int, environment: str) -> CreatorAccount:
    """打款与退款冲正共用创作者结算锁，不并入消费余额。"""
    await db.execute(insert(CreatorAccount).values(owner_id=owner_id, environment=environment, debt_fen=0)
        .on_conflict_do_nothing(index_elements=["owner_id", "environment"]))
    return (await db.execute(select(CreatorAccount).where(CreatorAccount.owner_id == owner_id,
        CreatorAccount.environment == environment).with_for_update())).scalar_one()


async def apply_apple_transaction(db, txn: dict) -> AppleTransaction:
    """已验签的每笔真实付款，对应一笔共同充值订单和一个资金来源。"""
    from .apple_recharge import product_snapshot, recharge_order_for_transaction, expected_prices
    environment, transaction_id = txn["environment"], str(txn["transaction_id"])
    await lock_wallet(db, txn["user_id"], environment)
    existing = await db.scalar(select(AppleTransaction).where(AppleTransaction.environment == environment,
        AppleTransaction.transaction_id == transaction_id)
        .with_for_update().execution_options(populate_existing=True))
    if existing:
        if (existing.user_id != txn["user_id"] or existing.product_id != txn["product_id"]
                or existing.app_account_token != txn["app_account_token"]):
            app_fail("MARKETPLACE_IAP_ACCOUNT_MISMATCH", "该交易不属于当前账号。", 403)
        if txn.get("status") == "refunded" and existing.status != "refunded":
            await refund_apple_transaction(db, environment, transaction_id)
        return existing
    product = await db.scalar(select(AppleProduct).where(AppleProduct.product_id == txn["product_id"]))
    if not product:
        app_fail("MARKETPLACE_IAP_PRODUCT_UNKNOWN", "充值商品尚未登记，请联系客服核对，交易不会被标记到账。", 409)
    product_snapshot(product)
    from .apple_fx import value_transaction
    txn = await value_transaction(db, txn)
    amount = txn["amount_fen"]
    if (txn.get("currency") not in ("CNY", "USD") or type(amount) is not int or amount < 0
            or txn.get("status", "paid") not in ("paid", "refunded")):
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "交易金额、币种或状态不正确。")
    refunded = txn.get("status") == "refunded"
    order = await recharge_order_for_transaction(db, txn, product)
    item = AppleTransaction(environment=environment, transaction_id=transaction_id, recharge_order_id=order.id,
        original_transaction_id=str(txn.get("original_transaction_id", transaction_id)),
        user_id=txn["user_id"], product_id=product.product_id, coins=order.credit_fen, amount_fen=amount,
        currency=txn["currency"], payment_amount_minor=txn["payment_amount_minor"],
        apple_price_milliunits=txn.get("apple_price_milliunits", txn["payment_amount_minor"] * 10),
        storefront=txn.get("storefront"), fx_snapshot=txn["fx_snapshot"], valuation_status=txn["valuation_status"],
        app_account_token=txn["app_account_token"], status="refunded" if refunded else "paid",
        revision=0, signed_at=txn["signed_at"], revoked_at=txn.get("revoked_at"), raw_payload=txn.get("raw_payload", {}),
        anomaly=PRICE_DIFFERENCE_ANOMALY if txn["payment_amount_minor"] != expected_prices(product).get(txn["currency"]) else "")
    db.add(item)
    await db.flush()
    db.add(AppleTransactionRevision(transaction_id=item.id, revision=0, status=item.status,
        delta_gross_fen=0 if refunded else amount))
    source_ref = f"{environment}:{transaction_id}"
    lot = await funds_call(wallet.credit(db, item.user_id, item.coins, source_type="apple_transaction",
        source_ref=source_ref, amount_fen=amount, environment=environment, note=f"Apple充值 {order.out_trade_no}"))
    lot.settlement_status = "pending_fx" if item.valuation_status == "pending" else "pending"
    if refunded:
        # 首次得知即已退款，同事务登记再失效，外部永远看不到可消费到账。
        await funds_call(wallet.revoke_source(db, item.user_id, "apple_transaction", source_ref, environment=environment))
        await funds_call(wallet.sweep_debts(db, item.user_id, environment=environment))
    await db.flush()
    return item


async def has_access(db, user_id: int, publication_id: int, environment: str) -> bool:
    """各渠道共用永久权益，历史币授予仍按环境读取。"""
    grant = await db.scalar(select(CoinGrant.id).where(CoinGrant.user_id == user_id,
        CoinGrant.publication_id == publication_id, CoinGrant.environment == environment, CoinGrant.active.is_(True)))
    if grant:
        return True
    entitlement = await db.scalar(select(Entitlement).where(Entitlement.user_id == user_id,
        Entitlement.publication_id == publication_id, Entitlement.active.is_(True))
        .execution_options(populate_existing=True))
    if not entitlement:
        return False
    if entitlement.order_id:
        order = await db.get(ContentOrder, entitlement.order_id)
        return bool(order and order.pay_type in ("alipay", "wxpay"))
    return not bool(await db.scalar(select(CoinGrant.id).where(CoinGrant.user_id == user_id,
        CoinGrant.publication_id == publication_id).limit(1)))


def unlock_data(item: CoinUnlock) -> dict:
    """coins 是扣款额度，amount_fen 是真实实付分摊，二者不可混淆。"""
    return {"id": item.id, "order_id": item.order_id, "publication_id": item.publication_id,
        "environment": item.environment, "coins": item.coins, "amount_fen": item.amount_fen,
        "status": item.status, "created_at": item.created_at}


async def unlock_publication(db, user_id: int, environment: str, publication_id: int,
                             expected_coins: int, idempotency_key: str) -> dict:
    """同事务完成统一余额扣款、来源分摊、永久权益和收入。"""
    from .commerce import _current_sale
    account = await lock_wallet(db, user_id, environment)
    prior = await db.scalar(select(CoinUnlock).where(CoinUnlock.user_id == user_id,
        CoinUnlock.environment == environment, CoinUnlock.idempotency_key == idempotency_key))
    if prior:
        if prior.publication_id != publication_id or prior.coins != expected_coins:
            app_fail("MARKETPLACE_IDEMPOTENCY_CONFLICT", "本次操作编号已用于其他内容，请刷新后重试。", 409)
        return {**unlock_data(prior), "entitled": await has_access(db, user_id, publication_id, environment), "duplicate": True}
    if await has_access(db, user_id, publication_id, environment):
        return {"publication_id": publication_id, "entitled": True, "duplicate": True, "charged_coins": 0}
    publication = await db.scalar(select(Publication).where(Publication.id == publication_id)
        .with_for_update().execution_options(populate_existing=True))
    if not publication or not await _current_sale(db, publication):
        app_fail("MARKETPLACE_CONTENT_CHANGED", "该版本已更新、下架或暂不可购买，请刷新后确认。", 409)
    if publication.owner_id == user_id:
        app_fail("MARKETPLACE_SELF_PURCHASE", "不能购买自己的作品。", 409)
    if publication.unlock_price_fen != expected_coins or expected_coins <= 0:
        app_fail("MARKETPLACE_CONTENT_CHANGED", "解锁价格已变化，请刷新后重新确认。", 409)
    state = await funds_call(wallet.snapshot(db, user_id, environment))
    if state["debt_fen"]:
        app_fail("WALLET_DEBT_OUTSTANDING", "账户存在欠费，请先充值补齐。", 409)
    if state["spendable_fen"] < expected_coins:
        app_fail("MARKETPLACE_COIN_BALANCE_INSUFFICIENT", "平台余额不足，或额度已被AI任务预留，请先充值。", 409)
    order = ContentOrder(out_trade_no=f"BAL-{uuid.uuid4().hex}", user_id=user_id,
        publication_id=publication_id, episode_id=publication.content_id if publication.content_type == "series_episode" else None,
        amount_fen=0, pay_type="platform_balance", status="paid", paid_at=now(),
        idempotency_key=f"balance:{environment}:{user_id}:{uuid.uuid4().hex}")
    db.add(order)
    await db.flush()
    item = CoinUnlock(user_id=user_id, environment=environment, order_id=order.id,
        publication_id=publication_id, coins=expected_coins, amount_fen=0, status="paid", idempotency_key=idempotency_key)
    db.add(item)
    await db.flush()
    allocations = await funds_call(wallet.consume(db, user_id, expected_coins,
        business_type="video_unlock", business_ref=str(item.id), environment=environment))
    gross = sum(row.amount_fen for row in allocations)
    item.amount_fen = order.amount_fen = gross
    db.add(CoinGrant(user_id=user_id, environment=environment, publication_id=publication_id,
        order_id=order.id, unlock_id=item.id, active=True))
    if environment == "Production":
        await db.execute(insert(Entitlement).values(user_id=user_id, publication_id=publication_id,
            episode_id=order.episode_id, order_id=order.id, active=True).on_conflict_do_update(
            index_elements=["user_id", "publication_id"], set_={"active": True, "order_id": order.id}))
    share = int(publication.share_bps)
    platform = gross * share // 10000
    db.add(RevenueLedger(order_id=order.id, publication_id=publication_id, owner_id=publication.owner_id,
        gross_fen=gross, platform_fen=platform, creator_fen=gross-platform, share_bps=share))
    await db.flush()
    return {**unlock_data(item), "entitled": True, "charged_coins": expected_coins,
        "balance_coins": account.balance_fen, "balance_fen": account.balance_fen}


async def refund_apple_transaction(db, environment: str, transaction_id: str, reversed: bool = False):
    """保留渠道适配层稳定入口，复杂退款独立分层。"""
    from .coin_refunds import refund_apple_transaction as refund
    return await refund(db, environment, transaction_id, reversed=reversed)
