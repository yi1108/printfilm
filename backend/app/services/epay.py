# -*- coding: utf-8 -*-
"""Epay (易支付) client for pay.gitcc.com — alipay / wxpay."""
from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _sign_pairs(params: dict[str, Any], key: str) -> str:
    items = []
    for k in sorted(params.keys()):
        if k in {"sign", "sign_type"}:
            continue
        v = params[k]
        if v is None or v == "":
            continue
        items.append(f"{k}={v}")
    raw = "&".join(items) + str(key)
    return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()


def sign(params: dict[str, Any]) -> str:
    s = get_settings()
    return _sign_pairs(params, s.epay_key)


def verify(params: dict[str, Any]) -> bool:
    got = str(params.get("sign") or "").lower()
    if not got:
        return False
    expect = sign({k: v for k, v in params.items() if k != "sign"})
    return got == expect


def build_submit_fields(
    *,
    out_trade_no: str,
    name: str,
    money_yuan: str,
    pay_type: str,
    notify_url: str | None = None,
    return_url: str | None = None,
    clientip: str | None = None,
    device: str | None = None,
) -> dict[str, str]:
    s = get_settings()
    if pay_type not in {"alipay", "wxpay"}:
        raise ValueError("pay_type must be alipay or wxpay")
    if not s.epay_pid or not s.epay_key:
        raise ValueError("易支付未配置 EPAY_PID / EPAY_KEY")
    notify = (notify_url or s.epay_notify_url or "").strip()
    ret = (return_url or s.epay_return_url or "").strip()
    # Avoid "/api/" in notify_url — pay.gitcc.com WAF blocks those payloads.
    if not notify:
        notify = f"{s.public_base_url.rstrip('/')}/epay/notify"
    if not ret:
        ret = f"{s.public_base_url.rstrip('/')}/pricing?paid=1"
    fields: dict[str, str] = {
        "pid": str(s.epay_pid),
        "type": pay_type,
        "out_trade_no": out_trade_no,
        "notify_url": notify,
        "return_url": ret,
        "name": name[:100],
        "money": money_yuan,
    }
    if clientip:
        fields["clientip"] = clientip
    # device=jump 只会返回收银台跳转 URL；扫码场景必须用 pc（勿传 jump）
    if device:
        fields["device"] = device
    fields["sign"] = sign(fields)
    fields["sign_type"] = "MD5"
    return fields


def _is_image_url(value: str) -> bool:
    return bool(value) and value.lower().startswith(("http://", "https://")) and any(
        ext in value.lower().split("?", 1)[0] for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")
    )


def _is_epay_cashier_url(value: str, api_base: str) -> bool:
    """易支付收银台 /submit 页，扫码会打开站点而非原生支付码。"""
    v = (value or "").strip().lower()
    if not v.startswith(("http://", "https://")):
        return False
    base = (api_base or "").rstrip("/").lower()
    host = base.replace("https://", "").replace("http://", "").split("/", 1)[0]
    if host and host in v:
        return True
    return "pay.gitcc.com" in v or "/pay/submit/" in v


def submit_url(fields: dict[str, str]) -> str:
    s = get_settings()
    base = s.epay_api_url.rstrip("/") + "/submit.php"
    return f"{base}?{urlencode(fields)}"


def money_yuan_from_fen(fen: int) -> str:
    return f"{fen / 100:.2f}"


async def create_mapi_payment(
    *,
    out_trade_no: str,
    name: str,
    money_yuan: str,
    pay_type: str,
    clientip: str,
    notify_url: str | None = None,
    return_url: str | None = None,
) -> dict[str, Any]:
    """
    Call epay /mapi.php for QR / native pay payload.
    Returns pay_mode=qr（原生扫码）或 redirect（仅收银台 payurl，前端新开易支付站点）。
    """
    fields = build_submit_fields(
        out_trade_no=out_trade_no,
        name=name,
        money_yuan=money_yuan,
        pay_type=pay_type,
        notify_url=notify_url,
        return_url=return_url,
        clientip=clientip or "127.0.0.1",
        device="pc",
    )
    s = get_settings()
    url = s.epay_api_url.rstrip("/") + "/mapi.php"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, data=fields)
    try:
        data = resp.json()
    except Exception as exc:
        snippet = (resp.text or "").replace("\n", " ")[:200]
        logger.error("epay mapi non-json status=%s body=%s", resp.status_code, snippet)
        if resp.status_code == 403 or "防火墙" in (resp.text or ""):
            raise ValueError(
                "易支付防火墙拦截（请确认 notify_url 不含 /api/ 路径）"
            ) from exc
        raise ValueError(f"易支付返回异常(HTTP {resp.status_code})") from exc
    if int(data.get("code") or 0) != 1:
        msg = str(data.get("msg") or data.get("message") or "下单失败")
        raise ValueError(msg)
    qrcode = str(data.get("qrcode") or "").strip()
    payurl = str(data.get("payurl") or "").strip()
    urlscheme = str(data.get("urlscheme") or "").strip()
    img = str(data.get("img") or data.get("code_url") or "").strip()

    qr_payload = ""
    if qrcode and not _is_epay_cashier_url(qrcode, s.epay_api_url):
        qr_payload = qrcode
    elif urlscheme:
        qr_payload = urlscheme
    elif _is_image_url(img):
        qr_payload = img

    # 有原生扫码内容 → 弹窗二维码；否则若有收银台 payurl → 前端新开易支付站点
    if qr_payload:
        pay_mode = "qr"
    elif payurl:
        pay_mode = "redirect"
        logger.info(
            "epay mapi redirect mode pay_type=%s trade_no=%s payurl=%s",
            pay_type,
            data.get("trade_no"),
            payurl[:120],
        )
    else:
        logger.warning(
            "epay mapi empty pay_type=%s trade_no=%s raw_keys=%s",
            pay_type,
            data.get("trade_no"),
            sorted(data.keys()) if isinstance(data, dict) else [],
        )
        raise ValueError(f"易支付未返回可用支付链接（{pay_type}）")

    return {
        "trade_no": str(data.get("trade_no") or ""),
        "qrcode": qrcode,
        "payurl": payurl,
        "img": img,
        "urlscheme": urlscheme,
        "qr_payload": qr_payload,
        "pay_mode": pay_mode,
        "raw": data,
    }
