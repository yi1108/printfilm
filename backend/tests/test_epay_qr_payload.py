"""Unit tests for epay QR payload selection (no live gateway)."""
from __future__ import annotations

from app.services.epay import _is_epay_cashier_url, _is_image_url


def test_epay_cashier_url_detected() -> None:
    base = "https://pay.gitcc.com"
    assert _is_epay_cashier_url("https://pay.gitcc.com/pay/submit/123/", base)
    assert _is_epay_cashier_url("https://pay.gitcc.com/pay/wxpay/abc/", base)
    assert not _is_epay_cashier_url("weixin://wxpay/bizpayurl?pr=xx", base)
    assert not _is_epay_cashier_url("https://qr.alipay.com/xxx", base)


def test_image_url_helper() -> None:
    assert _is_image_url("https://cdn.example.com/q.png")
    assert _is_image_url("https://cdn.example.com/q.jpg?x=1")
    assert not _is_image_url("https://pay.gitcc.com/pay/submit/1/")
    assert not _is_image_url("weixin://wxpay/bizpayurl?pr=xx")
