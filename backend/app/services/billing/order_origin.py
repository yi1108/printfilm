"""Client identity is immutable order metadata, not a payment method."""
ANDROID = "android_domestic"
CASH_SOURCE_TYPES = ("web_order", "android_epay_order")

def payment_client(order):
    value = getattr(order, "payment_client", None)
    if value:
        return value
    # Historical records stay unchanged; infer only from a proven channel.
    return {"apple_iap": "ios", "google_play": "android_international"}.get(getattr(order, "pay_type", ""), "web")

def funding_source(order):
    return "android_epay_order" if payment_client(order) == ANDROID else "web_order"
