"""只使用 Apple 官方服务器库验签和查询，不接受客户端声称的付款结果。"""
import asyncio
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any
import uuid

from fastapi import HTTPException

from .app_settings import get_app_settings
from .coin_service import app_fail


def _scalar(value):
    """将官方模型的枚举转成稳定的 JSON 值。"""
    return value.value if isinstance(value, Enum) else value


def _field(value, name: str, default=None):
    """同时支持官方 attrs 模型和测试中经过验证的字典。"""
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _json_value(value: Any):
    """保留已验证交易的审计字段，不记录签名私钥。"""
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    import attrs
    if attrs.has(type(value)):
        return _json_value(attrs.asdict(value))
    raise TypeError("不支持的 Apple 数据结构")


def apple_configured() -> bool:
    """配置完整仅代表可以验签，不等同于真实支付已联调。"""
    from .apple_configuration import configuration_status
    return configuration_status(get_app_settings())["configured"]


def require_apple_configured() -> None:
    """缺少真实配置时阻断验单，不构造假交易。"""
    if not apple_configured():
        app_fail("MARKETPLACE_PAYMENT_UNAVAILABLE", "苹果内购暂未配置，请稍后重试。", 503)


@lru_cache(maxsize=4)
def _official_objects(environment: str, bundle_id: str, app_id: int | None,
                      issuer_id: str, key_id: str, private_key: str,
                      roots: tuple[bytes, ...], online: bool):
    """服务器从可信证书建立验证器；SDK 请求自带30秒超时。"""
    from appstoreserverlibrary.api_client import AppStoreServerAPIClient
    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
    env = Environment(environment)
    verifier = SignedDataVerifier(list(roots), online, env, bundle_id, app_id)
    client = AppStoreServerAPIClient(private_key, key_id, issuer_id, bundle_id, env)
    return verifier, client


def _objects():
    """运行时只接受当前服务器环境，客户端不能指定 Sandbox 绕过付款。"""
    require_apple_configured()
    cfg = get_app_settings()
    try:
        from .apple_configuration import material
        private_key, roots = material(cfg)
        return _official_objects(cfg.apple_environment, cfg.apple_bundle_id, cfg.apple_app_id,
                                 cfg.apple_issuer_id, cfg.apple_key_id, private_key,
                                 roots, cfg.apple_online_checks)
    except Exception as exc:
        app_fail("MARKETPLACE_PAYMENT_UNAVAILABLE", "苹果内购服务器配置不可用，请联系管理员。", 503)


def _millisecond_date(value, *, required=False):
    """Apple 时间均为毫秒；拒绝非法时间而不是用服务器时间伪造。"""
    if value is None and not required:
        return None
    if type(value) is not int or value <= 0:
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "苹果交易时间不正确。")
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "苹果交易时间不正确。")


def normalize_transaction(decoded) -> dict:
    """已验签消耗型交易严格转换为人民币分；币数仍由不可变商品配置决定。"""
    cfg = get_app_settings()
    payload = _json_value(decoded)
    price, quantity = _field(decoded, "price"), _field(decoded, "quantity")
    env = _scalar(_field(decoded, "environment"))
    if (_field(decoded, "bundleId") != cfg.apple_bundle_id or env != cfg.apple_environment
            or _scalar(_field(decoded, "type")) != "Consumable" or type(quantity) is not int or quantity != 1
            or _field(decoded, "currency") not in ("CNY", "USD")
            or not _field(decoded, "storefront")
            or (_field(decoded, "currency") == "CNY" and _field(decoded, "storefront") != "CHN")
            or type(price) is not int or price < 0 or price % 10):
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "苹果交易的应用、地区、币种、类型或金额不正确。")
    try:
        token = str(uuid.UUID(str(_field(decoded, "appAccountToken"))))
    except (ValueError, TypeError, AttributeError):
        app_fail("MARKETPLACE_IAP_ACCOUNT_MISMATCH", "苹果交易没有有效的账号绑定，请联系客服核对。", 403)
    transaction_id = str(_field(decoded, "transactionId") or "")
    product_id = _field(decoded, "productId")
    if not transaction_id or len(transaction_id) > 100 or not isinstance(product_id, str) or not 0 < len(product_id) <= 200:
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "苹果交易编号或商品编号不正确。")
    revoked = _millisecond_date(_field(decoded, "revocationDate"))
    return {"environment": env, "transaction_id": transaction_id,
            "original_transaction_id": str(_field(decoded, "originalTransactionId") or transaction_id),
            "product_id": product_id, "amount_fen": price // 10 if _field(decoded, "currency") == "CNY" else 0,
            "payment_amount_minor": price // 10, "apple_price_milliunits": price,
            "currency": _field(decoded, "currency"), "storefront": _field(decoded, "storefront"),
            "app_account_token": token, "status": "refunded" if revoked else "paid",
            "signed_at": _millisecond_date(_field(decoded, "signedDate"), required=True),
            "revoked_at": revoked, "raw_payload": payload}


async def verify_transaction(signed_transaction_info: str) -> dict:
    """先执行官方证书链与JWS验证，再读取业务字段。"""
    verifier, _ = _objects()
    try:
        decoded = await asyncio.to_thread(verifier.verify_and_decode_signed_transaction, signed_transaction_info)
    except Exception as exc:
        app_fail("MARKETPLACE_IAP_TRANSACTION_INVALID", "苹果交易签名验证失败，请稍后重试或联系客服。")
    return normalize_transaction(decoded)


async def query_transaction(transaction_id: str) -> dict:
    """查询 Apple 当前权威状态，用于退款乱序和断线补偿。"""
    _, client = _objects()
    started_at = datetime.now(timezone.utc)
    try:
        response = await asyncio.to_thread(client.get_transaction_info, transaction_id)
        signed = response.signedTransactionInfo
    except Exception as exc:
        app_fail("MARKETPLACE_PAYMENT_UNAVAILABLE", "暂时无法向苹果确认交易，请稍后重试。", 503)
    result = await verify_transaction(signed)
    result["raw_payload"]["_server_observed_at"] = started_at.isoformat()
    return result


async def verify_notification(signed_payload: str) -> dict:
    """验证外层通知和内层交易；只有完整通过才可进入可靠收件箱。"""
    verifier, _ = _objects()
    try:
        decoded = await asyncio.to_thread(verifier.verify_and_decode_notification, signed_payload)
    except Exception:
        app_fail("MARKETPLACE_IAP_NOTIFICATION_INVALID", "苹果通知签名验证失败。")
    payload = _json_value(decoded)
    data = _field(decoded, "data")
    env = _scalar(_field(data, "environment"))
    notification_type = _scalar(_field(decoded, "notificationType")) or _field(decoded, "rawNotificationType")
    try:
        notification_uuid = str(uuid.UUID(str(_field(decoded, "notificationUUID"))))
    except (ValueError, TypeError):
        app_fail("MARKETPLACE_IAP_NOTIFICATION_INVALID", "苹果通知编号不正确。")
    if env != get_app_settings().apple_environment or _field(decoded, "version") != "2.0":
        app_fail("MARKETPLACE_IAP_NOTIFICATION_INVALID", "苹果通知环境或版本不正确。")
    signed = _field(data, "signedTransactionInfo")
    transaction = await verify_transaction(signed) if signed else None
    return {"environment": env, "notification_uuid": notification_uuid,
            "notification_type": str(notification_type or "UNKNOWN"), "transaction": transaction,
            "observed_at": _millisecond_date(_field(decoded, "signedDate"), required=True),
            "raw_payload": payload}


async def notification_history(start: datetime, end: datetime, pagination_token: str | None):
    """查询包含已投递通知的历史，覆盖漏通知和进程停机。"""
    from appstoreserverlibrary.models.NotificationHistoryRequest import NotificationHistoryRequest
    _, client = _objects()
    request = NotificationHistoryRequest(startDate=int(start.timestamp() * 1000), endDate=int(end.timestamp() * 1000), onlyFailures=False)
    try:
        return await asyncio.to_thread(client.get_notification_history, pagination_token, request)
    except Exception:
        app_fail("MARKETPLACE_PAYMENT_UNAVAILABLE", "苹果通知历史查询暂时不可用。", 503)


async def send_consumption(transaction_id: str, *, delivered: bool, consumed_milli_percent: int) -> None:
    """仅在账号明确授权后发送真实的交付/消费数据；不上传无关个人信息。"""
    from appstoreserverlibrary.models.ConsumptionRequest import ConsumptionRequest
    from appstoreserverlibrary.models.DeliveryStatus import DeliveryStatus
    from appstoreserverlibrary.models.RefundPreference import RefundPreference
    _, client = _objects()
    request = ConsumptionRequest(customerConsented=True, sampleContentProvided=False,
                                 deliveryStatus=DeliveryStatus.DELIVERED if delivered else DeliveryStatus.UNDELIVERED_SERVER_OUTAGE,
                                 consumptionPercentage=max(0, min(100000, consumed_milli_percent)),
                                 refundPreference=RefundPreference.DECLINE if consumed_milli_percent > 0 else None)
    try:
        await asyncio.to_thread(client.send_consumption_information, transaction_id, request)
    except Exception:
        app_fail("MARKETPLACE_PAYMENT_UNAVAILABLE", "苹果消费信息回传暂时失败，将自动重试。", 503)
