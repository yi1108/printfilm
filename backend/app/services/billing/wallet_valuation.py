"""Historical payment valuation shared by fulfilment, migration and review."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def order_cash(order):
    """Use the historical payment snapshot; unknown FX is not certified zero cash."""
    currency = (getattr(order, "payment_currency", None) or "cny").lower()
    if currency == "cny":
        minor = getattr(order, "payment_amount_minor", None)
        amount = int(order.amount_fen if minor is None else minor)
        if amount < 0:
            raise RuntimeError("充值实付金额不能为负数")
        return amount
    minor, rate = getattr(order, "payment_amount_minor", None), getattr(order, "payment_exchange_rate", None)
    if minor is None or rate is None:
        return None
    try:
        rate = Decimal(str(rate))
        if not rate.is_finite() or rate <= 0 or int(minor) < 0:
            raise ValueError()
        return int((Decimal(minor) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RuntimeError("充值实付汇率快照无效，必须人工核对") from exc

