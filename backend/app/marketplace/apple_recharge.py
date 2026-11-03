"""Apple 作为统一充值订单的支付渠道，不建立第二份消费余额。"""
from datetime import timedelta
import hashlib
import uuid

from sqlalchemy import select

from app.models import Order
from app.services.billing import wallet
from .apple_models import ApplePurchaseIntent
from .app_models import AppleProduct
from .coin_service import app_fail, check_environment
from .service import now


def product_snapshot(product: AppleProduct) -> dict:
    """商品绑定的是已冻结的共同套餐；旧未绑定商品必须人工核对。"""
    snapshot = product.sku_snapshot or {}
    if (not product.sku_id or snapshot.get("id") != product.sku_id
            or type(snapshot.get("credit_fen")) is not int
            or snapshot["credit_fen"] != product.coins
            or type(snapshot.get("amount_fen")) is not int
            or snapshot["amount_fen"] <= 0):
        app_fail("MARKETPLACE_IAP_PRODUCT_BINDING_REQUIRED", "苹果商品尚未绑定共同充值套餐，请联系管理员核对。", 503)
    return snapshot


async def find_product_for_sku(db, sku_id: str) -> AppleProduct:
    """同一套餐有多个在售映射时拒绝猜选，要求后台停用旧档位。"""
    products = list((await db.execute(select(AppleProduct).where(
        AppleProduct.sku_id == sku_id, AppleProduct.enabled.is_(True)))).scalars())
    if len(products) != 1:
        app_fail("MARKETPLACE_IAP_PRODUCT_UNAVAILABLE", "该套餐的苹果商品暂不可购买，请联系管理员。", 503)
    product_snapshot(products[0])
    return products[0]


async def list_recharge_products(db) -> list[dict]:
    """共同套餐列表展示冻结额度，苹果实际售价仍由 StoreKit 提供。"""
    rows = list((await db.execute(select(AppleProduct).where(
        AppleProduct.enabled.is_(True)).order_by(AppleProduct.coins, AppleProduct.id))).scalars())
    result = []
    seen = set()
    for product in rows:
        snapshot = product_snapshot(product)
        if product.sku_id in seen:
            app_fail("MARKETPLACE_IAP_PRODUCT_CONFLICT", "同一套餐存在多个启用商品，请联系管理员核对。", 503)
        seen.add(product.sku_id)
        result.append({**snapshot, "product_id": product.product_id,
                       "coins": product.coins, "reference_price_fen": product.price_fen})
    return result


async def create_recharge_intent(db, user_id: int, environment: str, product_id: str, key: str) -> dict:
    """先锁同一用户，幂等创建充值订单和 StoreKit 意向，不代表已付款。"""
    from .apple_service import account_token
    check_environment(environment)
    await wallet.lock_account(db, user_id, environment)
    product = await db.scalar(select(AppleProduct).where(
        AppleProduct.product_id == product_id, AppleProduct.enabled.is_(True)))
    if not product:
        app_fail("MARKETPLACE_IAP_PRODUCT_UNAVAILABLE", "该充值商品暂不可购买。", 409)
    snapshot = product_snapshot(product)
    request_hash = hashlib.sha256(product_id.encode()).hexdigest()
    intent = await db.scalar(select(ApplePurchaseIntent).where(
        ApplePurchaseIntent.user_id == user_id, ApplePurchaseIntent.environment == environment,
        ApplePurchaseIntent.idempotency_key == key).with_for_update())
    if intent and intent.request_hash != request_hash:
        app_fail("MARKETPLACE_IDEMPOTENCY_CONFLICT", "本次操作编号已用于其他充值商品。", 409)
    if not intent:
        order = Order(out_trade_no=f"IAP-I-{uuid.uuid4().hex}", user_id=user_id,
                      sku_id=product.sku_id, amount_fen=product.price_fen,
                      credit_fen=snapshot["credit_fen"], pay_type="apple_iap", status="pending")
        db.add(order)
        await db.flush()
        intent = ApplePurchaseIntent(user_id=user_id, environment=environment, product_id=product_id,
            recharge_order_id=order.id, idempotency_key=key, request_hash=request_hash,
            expires_at=now() + timedelta(minutes=30))
        db.add(intent)
        await db.flush()
    order = await db.get(Order, intent.recharge_order_id) if intent.recharge_order_id else None
    if not order:
        app_fail("MARKETPLACE_IAP_RECHARGE_ORDER_REQUIRED", "该历史充值意向尚未完成订单核对，请重新创建充值意向。", 409)
    token = await account_token(db, user_id)
    return {"intent_id": intent.id, "order_id": order.id, "out_trade_no": order.out_trade_no,
            "sku_id": order.sku_id, "product_id": product.product_id,
            "credit_fen": order.credit_fen, "coins": order.credit_fen,
            "price_fen": order.amount_fen, "amount_fen": order.amount_fen,
            "currency": "CNY", "app_account_token": token.token,
            "environment": environment, "expires_at": intent.expires_at}


async def recharge_order_for_transaction(db, txn: dict, product: AppleProduct) -> Order:
    """通知先到仍履约；同一意向出现多笔真实付款，每笔必须独立建单。"""
    snapshot = product_snapshot(product)
    query = select(ApplePurchaseIntent).where(
        ApplePurchaseIntent.user_id == txn["user_id"], ApplePurchaseIntent.environment == txn["environment"],
        ApplePurchaseIntent.product_id == product.product_id,
        ApplePurchaseIntent.fulfilled_transaction_id.is_(None),
        ApplePurchaseIntent.recharge_order_id.is_not(None))
    if txn.get("intent_id"):
        query = query.where(ApplePurchaseIntent.id == txn["intent_id"])
    intent = await db.scalar(query.order_by(ApplePurchaseIntent.id).limit(1).with_for_update())
    order = await db.get(Order, intent.recharge_order_id) if intent else None
    if order and (order.user_id != txn["user_id"] or order.pay_type != "apple_iap"
                  or order.sku_id != product.sku_id or order.credit_fen != product.coins
                  or order.status == "paid"):
        order = None
    if not order:
        identifier = hashlib.sha256(f'{txn["environment"]}:{txn["transaction_id"]}'.encode()).hexdigest()[:48]
        order = Order(out_trade_no=f"IAP-T-{identifier}", user_id=txn["user_id"], sku_id=product.sku_id,
                      amount_fen=txn["amount_fen"], credit_fen=snapshot["credit_fen"],
                      pay_type="apple_iap", status="pending")
        db.add(order)
        await db.flush()
    if intent and not intent.fulfilled_transaction_id:
        intent.fulfilled_transaction_id = str(txn["transaction_id"])
    order.amount_fen = txn["amount_fen"]
    order.trade_no = str(txn["transaction_id"])
    order.status = "refunded" if txn.get("status") == "refunded" else "paid"
    order.paid_at = now()
    await db.flush()
    return order
