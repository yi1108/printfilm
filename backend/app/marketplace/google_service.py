"""One Google token, one immutable owner, one committed wallet credit."""
import hashlib
import uuid
from datetime import timedelta, datetime, timezone
from sqlalchemy import select
from app.models import User, Order
from app.services.billing import wallet
from app.services.model_settings import _encrypt_secret
from .google_models import GoogleAccount, GoogleIntent, GooglePurchase, GoogleWork, GoogleVoid
from .google_config import fail, read, credentials
from . import google_client
from .service import now


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def lock_user(db, user_id, *, allow_closed=False):
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update(key_share=True)
        .execution_options(populate_existing=True))
    if not user or (user.closed_at is not None and not allow_closed):
        fail("GOOGLE_ACCOUNT_UNAVAILABLE", "账户不可用。", "Account unavailable.", 403)
    return user


async def account(db, user_id, package):
    await lock_user(db, user_id)
    row = await db.scalar(select(GoogleAccount).where(GoogleAccount.user_id == user_id, GoogleAccount.package_name == package))
    if not row:
        # Persist random identifiers: secret rotation cannot orphan old purchases.
        row = GoogleAccount(user_id=user_id, package_name=package, account_id=uuid.uuid4().hex + uuid.uuid4().hex)
        db.add(row)
        await db.flush()
    return row.account_id


def available(config, secret):
    if not config.get("purchasing_enabled") or not wallet.enabled():
        return False
    try:
        credentials(secret)
        return True
    except Exception:
        return False


def product(config, product_id):
    return next((p for p in config["products"] if p["product_id"] == product_id), None)


async def create_intent(db, user_id, body):
    settings, config = await read(db)
    if not settings or not available(config, settings.credentials):
        fail("GOOGLE_PURCHASING_DISABLED", "Google 新购暂不可用。", "Google purchasing is unavailable.", 503)
    p = product(config, body.product_id)
    if body.package_name != config["package_name"] or not p or not p["enabled"] or p["sku_id"] != body.sku_id:
        fail("GOOGLE_PRODUCT_UNAVAILABLE", "Google 商品或包名不匹配。", "Google product or package mismatch.")
    identity = await account(db, user_id, body.package_name)
    request_hash = digest(f"{body.package_name}:{body.sku_id}:{body.product_id}")
    intent = await db.scalar(select(GoogleIntent).where(GoogleIntent.user_id == user_id,
        GoogleIntent.idempotency_key == body.idempotency_key))
    if intent:
        if intent.request_hash != request_hash:
            fail("GOOGLE_IDEMPOTENCY_CONFLICT", "该操作编号已用于其他商品。", "Idempotency key was used with another product.")
        if aware(intent.expires_at) <= now() and not intent.fulfilled_token:
            fail("GOOGLE_INTENT_EXPIRED", "购买意向已过期，请重新创建。", "Purchase intent expired.")
    else:
        if not p.get("credit_fen"):
            fail("GOOGLE_PRODUCT_UNAVAILABLE", "请先在后台保存商品映射。", "Save product mappings in admin first.", 503)
        order = Order(user_id=user_id, out_trade_no="GP-I-" + uuid.uuid4().hex,
            sku_id=p["sku_id"], amount_fen=p["reference_amount_fen"], credit_fen=p["credit_fen"],
            pay_type="google_play", payment_environment=wallet.configured_environment(), status="pending")
        db.add(order)
        await db.flush()
        intent = GoogleIntent(user_id=user_id, package_name=body.package_name, sku_id=p["sku_id"], product_id=p["product_id"],
            account_id=identity, profile_id=uuid.uuid4().hex + uuid.uuid4().hex, intent_key=uuid.uuid4().hex,
            idempotency_key=body.idempotency_key, request_hash=request_hash, snapshot=dict(p), order_id=order.id,
            expires_at=now() + timedelta(minutes=30))
        db.add(intent)
        await db.flush()
    return dict(package_name=intent.package_name, intent_id=intent.intent_key, sku_id=intent.sku_id,
        product_id=intent.product_id, credit_fen=intent.snapshot["credit_fen"], obfuscated_account_id=intent.account_id,
        obfuscated_profile_id=intent.profile_id, expires_at=aware(intent.expires_at))


def state(proof):
    value = proof.get("purchaseState")
    if type(value) is not int or value not in (0, 1, 2):
        fail("GOOGLE_PROOF_INVALID", "Google 购买状态无法确认。", "Invalid Google purchase state.", 502)
    if proof.get("quantity", 1) != 1 or type(proof.get("quantity", 1)) is not int:
        fail("GOOGLE_QUANTITY_UNSUPPORTED", "仅支持单数量购买。", "Only quantity one is supported.")
    return value


async def apply_proof(db, package, product_id, token, proof, config, user_id=None, hints=None):
    """Google network query has finished; only DB work from this point."""
    status = state(proof)
    token_hash = digest(token)
    profile, identity = proof.get("obfuscatedExternalProfileId"), proof.get("obfuscatedExternalAccountId")
    intent = await db.scalar(select(GoogleIntent).where(GoogleIntent.profile_id == profile)) if profile else None
    if not intent or not identity or intent.account_id != identity:
        fail("GOOGLE_ACCOUNT_MISMATCH", "无法核实购买的原账号与意向。", "Purchase account and intent could not be verified.")
    if (intent.package_name != package or intent.product_id != product_id
            or (user_id is not None and user_id != intent.user_id)):
        fail("GOOGLE_ACCOUNT_MISMATCH", "请登录购买时的原账号。", "Sign in to the original purchasing account.")
    if hints:
        for key, value in (("intent_id", intent.intent_key), ("obfuscated_account_id", identity), ("obfuscated_profile_id", profile)):
            if hints.get(key) is not None and hints[key] != value:
                fail("GOOGLE_ACCOUNT_MISMATCH", "客户端购买绑定与 Google 凭证不一致。", "Purchase binding does not match Google records.")
    purchase_type = proof.get("purchaseType")
    if purchase_type is not None and (type(purchase_type) is not int or purchase_type not in (0, 1, 2)):
        fail("GOOGLE_PROOF_INVALID", "Google 购买类型无法确认。", "Invalid Google purchase type.", 502)
    test = purchase_type == 0
    env = wallet.configured_environment() if status == 2 and "purchaseType" not in proof else "Sandbox" if test else "Production"
    # License payments can only fund a test deployment, never production users.
    if env != wallet.configured_environment() or (env == "Sandbox" and intent.user_id not in config.get("test_user_ids", [])):
        fail("GOOGLE_TEST_PURCHASE_ISOLATED", "测试付款只允许获准账号在 Sandbox 测试部署使用，不计入正式余额。",
             "License test purchases require an approved account on a Sandbox wallet deployment.", 403)
    # Account closure cannot discard a valid paid transaction or prevent refunds.
    await lock_user(db, intent.user_id, allow_closed=True)
    intent = await db.scalar(select(GoogleIntent).where(GoogleIntent.id == intent.id).execution_options(populate_existing=True))
    if intent.fulfilled_token and intent.fulfilled_token != token_hash:
        fail("GOOGLE_INTENT_CONFLICT", "该购买意向已绑定另一笔交易，请联系客服。", "This intent is bound to another purchase.")
    txn = await db.scalar(select(GooglePurchase).where(GooglePurchase.package_name == package,
        GooglePurchase.token_hash == token_hash).with_for_update().execution_options(populate_existing=True))
    if txn and (txn.user_id != intent.user_id or txn.intent_id != intent.id or txn.product_id != product_id):
        fail("GOOGLE_ACCOUNT_MISMATCH", "交易已绑定原账号。", "Purchase is bound to its original account.")
    order = await db.get(Order, intent.order_id)
    if not order or order.user_id != intent.user_id or order.pay_type != "google_play":
        fail("GOOGLE_ORDER_CONFLICT", "原充值订单不一致。", "Original recharge order mismatch.")
    if order.payment_environment != env:
        fail("GOOGLE_ORDER_CONFLICT", "交易环境与原订单不一致。", "Purchase environment differs from the original order.")
    # Current time expiry must not erase a real payment or approved pending order.
    if status == 0:
        try:
            purchased = datetime.fromtimestamp(int(proof["purchaseTimeMillis"]) / 1000, timezone.utc)
            if purchased < aware(intent.created_at) - timedelta(minutes=5) or purchased > now() + timedelta(minutes=5):
                raise ValueError()
        except (ValueError, KeyError, OverflowError, TypeError):
            fail("GOOGLE_PROOF_INVALID", "Google 付款时间与原意向不一致。", "Purchase time does not match the intent.")
        if not isinstance(proof.get("orderId"), str) or not 1 <= len(proof["orderId"]) <= 200:
            fail("GOOGLE_PROOF_INVALID", "Google 订单编号缺失。", "Google order identifier missing.", 502)
    if not txn:
        txn = GooglePurchase(package_name=package, token_hash=token_hash, token_secret=_encrypt_secret(token),
            user_id=intent.user_id, intent_id=intent.id, order_id=order.id, product_id=product_id,
            environment=env, credit_fen=intent.snapshot["credit_fen"], status="pending", consumed=False,
            last_verified_at=now())
        db.add(txn)
        await db.flush()
    prior = txn.status
    if proof.get("orderId"):
        if txn.google_order_id and txn.google_order_id != proof["orderId"]:
            fail("GOOGLE_ORDER_CONFLICT", "Google 订单凭证发生冲突。", "Google order proof conflict.")
        txn.google_order_id = proof["orderId"]
    tombstone = await db.scalar(select(GoogleVoid.id).where(GoogleVoid.package_name == package, GoogleVoid.token_hash == token_hash))
    intent.fulfilled_token = token_hash
    if status == 1 or tombstone or prior in ("refunded", "cancelled"):
        if prior == "credited":
            await refund(db, txn)
        else:
            txn.status = "refunded" if tombstone or prior == "refunded" else "cancelled"
            order.status = txn.status
    elif status == 0 and prior != "credited":
        lot = await wallet.credit(db, intent.user_id, txn.credit_fen, source_type="google_transaction",
            source_ref=f"{package}:{token_hash}", amount_fen=0, environment=env,
            note="Google Play 充值；原币实付与资金成本待核算")
        lot.settlement_status = "pending_fx"
        txn.was_credited = True
        txn.status = order.status = "credited"
        order.status, order.trade_no, order.paid_at = "paid", txn.google_order_id, purchased
        order.payment_environment = env
    if proof.get("consumptionState") == 1:
        txn.consumed = True
    txn.last_verified_at = now()
    await queue(db, package, product_id, token)
    await db.flush()
    response_status = "already_credited" if prior == "credited" and txn.status == "credited" else txn.status
    if status == 2 and txn.status not in ("refunded", "cancelled"):
        response_status = "pending"
    return response(txn, response_status)


def response(txn, status):
    granted = status in ("credited", "already_credited")
    return dict(package_name=txn.package_name, product_id=txn.product_id, purchase_token_sha256=txn.token_hash,
        order_id=txn.google_order_id, status=status, credited=granted, consume_purchase=granted,
        credit_fen=txn.credit_fen if granted else 0)


async def queue(db, package, product_id, token):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    await db.execute(insert(GoogleWork).values(package_name=package, product_id=product_id,
        token_hash=digest(token), token_secret=_encrypt_secret(token), next_attempt_at=now(), attempts=0,
        last_error="").on_conflict_do_nothing(index_elements=["package_name", "token_hash"]))


async def refund(db, txn):
    """Same debt/AI reserve/video entitlement reversal as other wallet channels."""
    if txn.status != "credited":
        return
    result = await wallet.revoke_source(db, txn.user_id, "google_transaction",
        f"{txn.package_name}:{txn.token_hash}", environment=txn.environment)
    from .app_models import CoinUnlock
    from .coin_refunds import _reverse_unlock
    ids = sorted({int(item["business_ref"]) for item in result["affected_business_refs"]
                  if item["business_type"] == "video_unlock"})
    if ids:
        from .models import RevenueLedger
        from .coin_service import lock_creator
        owner_ids = (await db.scalars(select(RevenueLedger.owner_id).join(CoinUnlock,
            CoinUnlock.order_id == RevenueLedger.order_id).where(CoinUnlock.id.in_(ids)).distinct())).all()
        for owner_id in sorted(owner_ids):
            await lock_creator(db, owner_id, txn.environment)
    for ident in ids:
        unlock = await db.get(CoinUnlock, ident)
        if unlock and unlock.user_id == txn.user_id and unlock.environment == txn.environment:
            await _reverse_unlock(db, unlock, txn, channel="Google Play", transaction_id=txn.google_order_id or txn.token_hash)
    await wallet.sweep_debts(db, txn.user_id, environment=txn.environment)
    txn.status = "refunded"
    order = await db.get(Order, txn.order_id)
    if order:
        order.status = "refunded"


async def verify(db, user_id, body):
    settings, config = await read(db)
    secret = settings.credentials if settings else ""
    if body.package_name != config["package_name"]:
        fail("GOOGLE_PACKAGE_MISMATCH", "包名不匹配。", "Package name mismatch.")
    await db.rollback()  # no DB transaction is held across Google network calls
    proof = await google_client.query(secret, body.package_name, body.product_id, body.purchase_token)
    # Settings changes during the query must not alter ownership or frozen credit.
    result = await apply_proof(db, body.package_name, body.product_id, body.purchase_token, proof, config,
        user_id=user_id, hints=body.model_dump())
    await db.commit()  # consume permission is never returned before this succeeds
    return result
