"""Apple 已验签交易和通知的共享履约逻辑。"""
from datetime import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from . import apple_client
from .apple_models import AppleAccountToken, AppleNotification, ApplePurchaseIntent
from .app_models import AppleTransaction
from .coin_service import app_fail, apply_apple_transaction, lock_wallet
from .coin_refunds import refund_apple_transaction
from .service import now


async def account_token(db, user_id: int) -> AppleAccountToken:
    """并发首次购买仍得到同一账号 UUID。"""
    await db.execute(insert(AppleAccountToken).values(user_id=user_id, token=str(uuid.uuid4()), consumption_data_consent=False)
                     .on_conflict_do_nothing(index_elements=["user_id"]))
    return (await db.execute(select(AppleAccountToken).where(AppleAccountToken.user_id == user_id))).scalar_one()


async def purchase_intent(db, user_id: int, environment: str, product_id: str, key: str) -> dict:
    """兼容 App 路径，共同订单服务负责幂等和套餐快照。"""
    from .apple_recharge import create_recharge_intent
    from .coin_service import funds_call
    return await funds_call(create_recharge_intent(db, user_id, environment, product_id, key))


async def apply_verified_transaction(db, txn: dict, *, expected_user_id: int | None = None,
                                     intent_id: int | None = None, event_type: str = "") -> AppleTransaction:
    """归属由预先分配的账号 UUID 决定；钱包锁内比较权威查询顺序再履约。"""
    from app.services.billing import wallet
    # 校验必须早于账号归属查询与任何订单、余额及退款写入。
    from .app_funds import isolated
    try:
        if not isolated(txn["environment"]):
            wallet.configured_environment(txn["environment"])
    except wallet.WalletError as exc:
        app_fail(exc.code, exc.message, exc.status)
    owner = (await db.execute(select(AppleAccountToken).where(AppleAccountToken.token == txn["app_account_token"]))).scalar_one_or_none()
    if not owner or (expected_user_id is not None and owner.user_id != expected_user_id):
        app_fail("MARKETPLACE_IAP_ACCOUNT_MISMATCH", "该苹果交易不属于当前 PrintFilm 账号，请使用购买时的账号登录。", 403)
    if isolated(txn["environment"]):
        from .sandbox_wallet import authorize_transaction
        await authorize_transaction(db, owner.user_id, txn)
    if intent_id is not None:
        intent = await db.get(ApplePurchaseIntent, intent_id)
        if not intent or intent.user_id != owner.user_id or intent.environment != txn["environment"] or intent.product_id != txn["product_id"]:
            app_fail("MARKETPLACE_IAP_ACCOUNT_MISMATCH", "充值意向与苹果交易不匹配，请联系客服核对。", 403)
    txn = {**txn, "user_id": owner.user_id, "intent_id": intent_id}
    await lock_wallet(db, owner.user_id, txn["environment"])
    previous = (await db.execute(select(AppleTransaction).where(AppleTransaction.environment == txn["environment"],
                              AppleTransaction.transaction_id == txn["transaction_id"])
                              .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if previous:
        if previous.user_id != owner.user_id or previous.product_id != txn["product_id"] or previous.app_account_token != txn["app_account_token"]:
            app_fail("MARKETPLACE_IAP_ACCOUNT_MISMATCH", "苹果交易归属发生冲突，请联系客服。", 403)
        if isolated(txn["environment"]):
            from .sandbox_models import SandboxLot
            if not await db.scalar(select(SandboxLot.id).where(SandboxLot.transaction_id == previous.id)):
                app_fail("SANDBOX_LEGACY_REVIEW_REQUIRED", "历史沙箱资金不在隔离账本中，请人工核对，不自动搬入正式余额。", 409)
        # 所有财务入口均先做 Apple 当前状态查询；旧查询返回较晚也不能复活新退款。
        incoming_at = txn.get("raw_payload", {}).get("_server_observed_at", "")
        previous_at = (previous.raw_payload or {}).get("_server_observed_at", "")
        if previous_at and (not incoming_at or incoming_at < previous_at):
            return previous
        if txn["signed_at"] < previous.signed_at and txn["status"] != previous.status:
            return previous
    if not previous and event_type == "REFUND_REVERSED" and txn["status"] == "paid":
        item = await apply_apple_transaction(db, {**txn, "status": "refunded"})
        await refund_apple_transaction(db, txn["environment"], txn["transaction_id"], reversed=True)
    else:
        item = await apply_apple_transaction(db, txn)
        if previous and previous.status == "refunded" and txn["status"] == "paid":
            await refund_apple_transaction(db, txn["environment"], txn["transaction_id"], reversed=True)
    item.signed_at = max(item.signed_at, txn["signed_at"])
    item.revoked_at = txn.get("revoked_at") if item.status == "refunded" else None
    item.raw_payload = txn.get("raw_payload", {})
    await db.flush()
    return item


def transaction_response(item: AppleTransaction) -> dict:
    """回传已持久化履约状态；finish可用于退款终态，但不伪称已到账。"""
    from .locale import localized
    return {"transaction_id": item.transaction_id, "environment": item.environment,
            "order_id": item.recharge_order_id,
            "status": item.status, "coins": item.coins, "amount_fen": item.amount_fen,
            "currency": item.currency, "credited": item.status == "paid", "finish_transaction": True,
            "payment_amount_minor": item.payment_amount_minor, "credit_currency": "CNY",
            "valuation_status": item.valuation_status, "test_only": item.settlement_status == "test_only",
            "message": localized("平台余额充值已确认。", "Platform credit confirmed.") if item.status == "paid" else localized("该笔充值已退款，未发放可用平台余额。", "This purchase was refunded; no available platform credit was granted.")}


async def persist_notification(db, payload: dict) -> bool:
    """验证结果持久化后再应答；UUID幂等与环境共同约束。"""
    transaction = payload.get("transaction") or {}
    stored = {"transaction": transaction.copy(), "raw_payload": payload.get("raw_payload", {})}
    for key in ("signed_at", "revoked_at"):
        if isinstance(stored["transaction"].get(key), datetime):
            stored["transaction"][key] = stored["transaction"][key].isoformat()
    inserted = await db.execute(insert(AppleNotification).values(
        environment=payload["environment"], notification_uuid=payload["notification_uuid"],
        notification_type=payload["notification_type"], transaction_id=transaction.get("transaction_id", ""),
        payload=stored, status="pending", attempts=0, observed_at=payload["observed_at"], error="")
        .on_conflict_do_nothing(index_elements=["environment", "notification_uuid"]).returning(AppleNotification.id))
    return inserted.scalar_one_or_none() is not None


async def consumption_request_snapshot(db, transaction: dict) -> dict:
    """仅查询授权及实际消费快照；调用方关闭读事务后才可访问Apple。"""
    owner = (await db.execute(select(AppleAccountToken).where(AppleAccountToken.token == transaction["app_account_token"]))).scalar_one_or_none()
    if not owner or not owner.consumption_data_consent:
        return {"note": "用户未授权向苹果提供消费数据，未披露；不影响苹果退款结果处理。"}
    item = (await db.execute(select(AppleTransaction).where(AppleTransaction.environment == transaction["environment"],
                            AppleTransaction.transaction_id == transaction["transaction_id"]))).scalar_one_or_none()
    if item and (item.user_id != owner.user_id or item.app_account_token != transaction["app_account_token"]):
        return {"note": "交易账号绑定存在冲突，未披露消费数据，请人工核对。"}
    from .app_funds import isolated
    if isolated(transaction["environment"]):
        from .sandbox_models import SandboxLot
        lot = await db.scalar(select(SandboxLot).where(SandboxLot.transaction_id == item.id)) if item else None
        return {"transaction_id": transaction["transaction_id"], "environment": "Sandbox",
                "delivered": bool(lot), "consumed_milli_percent":
                (lot.total_units - lot.available_units) * 100000 // lot.total_units if lot else 0}
    from app.services.billing import wallet
    from app.models_wallet import WalletAllocation
    from sqlalchemy import func
    try:
        lot = await wallet.get_source(db, owner.user_id, "apple_transaction",
            f'{transaction["environment"]}:{transaction["transaction_id"]}', environment=transaction["environment"]) if item else None
    except wallet.WalletError:
        return {"note": "统一余额尚未完成迁移，暂不向苹果提供消费数据；退款结果仍会正常处理。"}
    delivered = bool(item and lot)
    spent = await db.scalar(select(func.coalesce(func.sum(WalletAllocation.units), 0)).where(
        WalletAllocation.lot_id == lot.id, WalletAllocation.state == "consumed")) if lot else 0
    consumed = min(100000, int(spent or 0) * 100000 // lot.total_units) if lot else 0
    return {"transaction_id": transaction["transaction_id"], "delivered": delivered, "consumed_milli_percent": consumed}


async def send_consumption_snapshot(snapshot: dict) -> str:
    """无数据库事务地回传已授权的最小数据，失败由通知租约队列重试。"""
    if snapshot.get("note"):
        return snapshot["note"]
    await apple_client.in_environment(snapshot.get("environment", apple_client.get_app_settings().apple_environment),
        apple_client.send_consumption, snapshot["transaction_id"], delivered=snapshot["delivered"],
        consumed_milli_percent=snapshot["consumed_milli_percent"])
    return ""
