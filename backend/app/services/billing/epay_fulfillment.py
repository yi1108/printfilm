"""Signed Epay evidence is the only path to recharge fulfilment."""
import hmac
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from app.config import get_settings
from app.models import Order, User
from app.marketplace.android_epay_models import AndroidEpayCheckout, EpayReceipt
from app.services import epay
from app.services.model_settings import _decrypt_secret
from .order_origin import ANDROID, payment_client
from .android_epay import namespace

log = logging.getLogger(__name__)

def reject(status=400):
    return PlainTextResponse("fail", status_code=status)

async def fulfill(db, params):
    number = str(params.get("out_trade_no") or "")
    if not number or len(number) > 64:
        return reject()
    # No row lock until the gateway signature is valid.
    checkout = await db.scalar(select(AndroidEpayCheckout).join(Order, Order.id == AndroidEpayCheckout.order_id)
        .where(Order.out_trade_no == number))
    cfg = get_settings()
    key = _decrypt_secret(checkout.signing_secret) if checkout else cfg.epay_key
    if not key or key.startswith("enc:"):
        return reject(503)
    signature = str(params.get("sign") or "").lower()
    if not signature or not hmac.compare_digest(signature, epay._sign_pairs(params, key)):
        log.warning("Epay notification signature rejected")
        return reject()
    expected_pid = checkout.merchant_pid if checkout else str(cfg.epay_pid)
    # Legacy Web notifications missing pid/type remain compatible. Android requires full evidence.
    if (("pid" in params or checkout) and str(params.get("pid") or "") != expected_pid):
        return reject()
    status = str(params.get("trade_status") or params.get("status") or "").upper()
    if status not in ("TRADE_SUCCESS", "SUCCESS", "1"):
        return PlainTextResponse("success")
    order = await db.scalar(select(Order).where(Order.out_trade_no == number).with_for_update()
        .execution_options(populate_existing=True))
    if not order:
        return reject(404)
    if order.pay_type not in ("alipay", "wxpay") or order.payment_environment not in (None, "Production"):
        return reject()
    if (("type" in params or checkout) and str(params.get("type") or "") != order.pay_type):
        return reject()
    if payment_client(order) == ANDROID:
        if not checkout:
            return reject(409)
        if not cfg.unified_wallet_enabled or cfg.wallet_environment != "Production":
            return reject(503)
    trade = str(params.get("trade_no") or params.get("transaction_id") or "")
    if (checkout and not trade) or len(trade) > 128 or any(c.isspace() for c in trade):
        return reject()
    text_amount = str(params.get("money") or "")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", text_amount):
        return reject()
    amount = Decimal(text_amount) * 100
    if amount <= 0 or amount != int(order.amount_fen):
        return reject()
    if order.trade_no and trade and order.trade_no != trade:
        return reject(409)
    if order.status not in ("pending", "closed", "paid"):
        return reject(409)
    if trade:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        dialect = db.bind.dialect.name
        insert = sqlite_insert if dialect == "sqlite" else pg_insert
        merchant = checkout.merchant_namespace if checkout else namespace(cfg.epay_api_url, cfg.epay_pid)
        await db.execute(insert(EpayReceipt).values(merchant_namespace=merchant, merchant_pid=expected_pid,
            trade_no=trade, order_id=order.id, payment_client=payment_client(order), pay_type=order.pay_type,
            amount_fen=int(amount)).on_conflict_do_nothing())
        receipt = await db.scalar(select(EpayReceipt).where(EpayReceipt.order_id == order.id))
        if not receipt or receipt.trade_no != trade or receipt.merchant_namespace != merchant:
            await db.rollback()
            return reject(409)
    if order.status != "paid":
        user = await db.get(User, order.user_id)
        if not user:
            return reject(404)
        from app.services.billing import credit_topup
        order.status, order.trade_no, order.paid_at = "paid", trade or None, datetime.now(timezone.utc)
        order.payment_currency, order.payment_amount_minor = "cny", int(amount)
        order.payment_exchange_rate = "1"
        await credit_topup(db, user, int(order.credit_fen), ref_type="order", ref_id=order.out_trade_no,
            note=f"epay:{order.pay_type} source:{payment_client(order)}" + (f" legacy_team:{order.team_id}" if order.team_id else ""))
    if checkout:
        checkout.state, checkout.completed_at = "paid", datetime.now(timezone.utc)
    await db.commit()
    log.info("Epay payment confirmed order=%s source=%s", number, payment_client(order))
    return PlainTextResponse("success")
