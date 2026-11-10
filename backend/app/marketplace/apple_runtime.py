"""Apple 通知可靠处理与历史补偿，随API运行，不受市场展示开关控制。"""
import asyncio
from datetime import timedelta
import logging
import time
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal
from . import apple_client
from .apple_models import AppleNotification, AppleNotificationCursor
from .apple_service import (apply_verified_transaction, consumption_request_snapshot,
                            persist_notification, send_consumption_snapshot)
from .app_settings import get_app_settings
from .service import now

logger = logging.getLogger(__name__)
_task: asyncio.Task | None = None
_state = {"heartbeat_at": None, "last_error": "", "last_compensated_at": None}
FINANCIAL_EVENTS = {"ONE_TIME_CHARGE", "REFUND", "REFUND_REVERSED", "REVOKE"}


def apple_runtime_state() -> dict:
    """运行状态不暴露账号令牌、JWS或支付密钥。"""
    return {"configured": apple_client.apple_configured(), "running": bool(_task and not _task.done()), **_state}


async def _claim_notification():
    """数据库租约阻止多API进程重复处理，超时工作允许重启恢复。"""
    async with AsyncSessionLocal() as db:
        instant = now()
        query = select(AppleNotification).where(
            AppleNotification.environment == get_app_settings().apple_environment,
            or_(and_(AppleNotification.status.in_(("pending", "failed")), AppleNotification.attempts < 20,
                     or_(AppleNotification.next_attempt_at.is_(None), AppleNotification.next_attempt_at <= instant)),
                and_(AppleNotification.status == "running", AppleNotification.lease_until <= instant)),
        ).order_by(AppleNotification.id).with_for_update(skip_locked=True).limit(1)
        item = (await db.execute(query)).scalar_one_or_none()
        if not item:
            return None
        token = uuid.uuid4().hex
        item.status, item.lease_token = "running", token
        item.attempts += 1
        item.lease_until = instant + timedelta(seconds=180)
        result = {"id": item.id, "token": token, "type": item.notification_type,
                  "transaction_id": item.transaction_id, "payload": item.payload}
        await db.commit()
        return result


def _safe_error(exc: Exception) -> str:
    """错误仅保留中文业务原因，SDK或网络异常不进入运营日志。"""
    if isinstance(exc, HTTPException):
        detail = exc.detail
        message = detail.get("message") if isinstance(detail, dict) else detail
        if isinstance(message, str) and any("\u3400" <= char <= "\u9fff" for char in message):
            return message[:500]
    return "苹果交易处理暂时失败，将自动重试；请检查服务及配置。"


async def process_notification_once() -> bool:
    """查询当前权威状态后，在同事务中履约并完成收件箱记录。"""
    work = await _claim_notification()
    if not work:
        return False
    try:
        # Apple调用在持有金融行锁前完成，历史通知不会按到达顺序复活退款。
        transaction = await apple_client.query_transaction(work["transaction_id"]) if work["type"] in FINANCIAL_EVENTS else None
        note = ""
        if work["type"] == "CONSUMPTION_REQUEST":
            original = (work["payload"] or {}).get("transaction")
            if not original:
                raise ValueError("消费信息请求缺少交易")
            async with AsyncSessionLocal() as read_db:
                snapshot = await consumption_request_snapshot(read_db, original)
            # 快照读事务已经关闭；网络调用不持有通知或金融行锁。
            note = await send_consumption_snapshot(snapshot)
        async with AsyncSessionLocal() as db:
            item = (await db.execute(select(AppleNotification).where(AppleNotification.id == work["id"],
                AppleNotification.lease_token == work["token"], AppleNotification.status == "running").with_for_update())).scalar_one_or_none()
            if not item:
                return True
            if transaction is not None:
                if transaction["transaction_id"] != item.transaction_id or transaction["environment"] != item.environment:
                    raise ValueError("苹果查询结果与通知不一致")
                await apply_verified_transaction(db, transaction, event_type=item.notification_type)
            # TEST/REFUND_DECLINED和未知非财务事件不产生余额变化，保留审计记录。
            item.status = "done" if item.notification_type in FINANCIAL_EVENTS | {"TEST", "CONSUMPTION_REQUEST", "REFUND_DECLINED"} else "ignored"
            item.error, item.processed_at = note, now()
            item.lease_token = item.lease_until = item.next_attempt_at = None
            await db.commit()
            _state["last_error"] = ""
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        message = _safe_error(exc)
        async with AsyncSessionLocal() as db:
            item = (await db.execute(select(AppleNotification).where(AppleNotification.id == work["id"],
                AppleNotification.lease_token == work["token"]).with_for_update())).scalar_one_or_none()
            if item:
                item.status, item.error = "failed", message
                item.next_attempt_at = now() + timedelta(seconds=min(3600, 5 * 2 ** min(item.attempts, 10)))
                item.lease_token = item.lease_until = None
                await db.commit()
        _state["last_error"] = message
        logger.warning("Apple通知处理失败 id=%s type=%s", work["id"], type(exc).__name__)
    return True


async def reconcile_history_once() -> bool:
    """每次补偿一页，持久化时间窗口和分页令牌，支持长时间停机后恢复。"""
    environment = get_app_settings().apple_environment
    async with AsyncSessionLocal() as db:
        instant = now()
        await db.execute(insert(AppleNotificationCursor).values(environment=environment, last_end_at=instant - timedelta(days=1), error="")
                         .on_conflict_do_nothing(index_elements=["environment"]))
        cursor = (await db.execute(select(AppleNotificationCursor).where(
            AppleNotificationCursor.environment == environment,
            or_(AppleNotificationCursor.lease_until.is_(None), AppleNotificationCursor.lease_until <= instant)
        ).with_for_update(skip_locked=True))).scalar_one_or_none()
        if not cursor:
            return False
        if cursor.last_end_at < instant - timedelta(days=179):
            cursor.error = "通知补偿间隔超过Apple可查询期限，需人工核对财务及交易记录。"
            await db.commit()
            _state["last_error"] = cursor.error
            return False
        if not cursor.window_start:
            cursor.window_start = cursor.last_end_at - timedelta(minutes=10)
            cursor.window_end = min(instant, cursor.last_end_at + timedelta(days=1))
        token = uuid.uuid4().hex
        cursor.lease_token, cursor.lease_until = token, instant + timedelta(seconds=180)
        snapshot = {"id": cursor.id, "start": cursor.window_start, "end": cursor.window_end,
                    "page": cursor.pagination_token, "token": token}
        await db.commit()
    try:
        response = await apple_client.notification_history(snapshot["start"], snapshot["end"], snapshot["page"])
        for record in response.notificationHistory or []:
            payload = await apple_client.verify_notification(record.signedPayload)
            async with AsyncSessionLocal() as db:
                await persist_notification(db, payload)
                # 一页可能含多个需在线验签的通知，每条入库后续租，避免长页反复失去游标。
                retained = await db.execute(update(AppleNotificationCursor).where(
                    AppleNotificationCursor.id == snapshot["id"], AppleNotificationCursor.lease_token == token,
                    AppleNotificationCursor.lease_until > now()
                ).values(lease_until=now() + timedelta(seconds=180)).returning(AppleNotificationCursor.id))
                still_owned = retained.scalar_one_or_none() is not None
                await db.commit()
            if not still_owned:
                return False
        async with AsyncSessionLocal() as db:
            cursor = (await db.execute(select(AppleNotificationCursor).where(
                AppleNotificationCursor.id == snapshot["id"], AppleNotificationCursor.lease_token == token
            ).with_for_update())).scalar_one_or_none()
            if cursor:
                if response.hasMore:
                    if not response.paginationToken or response.paginationToken == snapshot["page"]:
                        raise ValueError("苹果通知分页游标无效")
                    cursor.pagination_token = response.paginationToken
                else:
                    cursor.last_end_at = snapshot["end"]
                    cursor.window_start = cursor.window_end = cursor.pagination_token = None
                cursor.error = ""
                cursor.lease_token = cursor.lease_until = None
                await db.commit()
        _state["last_compensated_at"] = now().isoformat()
        return bool(response.hasMore or snapshot["end"] < now() - timedelta(minutes=1))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        message = _safe_error(exc)
        async with AsyncSessionLocal() as db:
            cursor = (await db.execute(select(AppleNotificationCursor).where(
                AppleNotificationCursor.id == snapshot["id"], AppleNotificationCursor.lease_token == token
            ).with_for_update())).scalar_one_or_none()
            if cursor:
                cursor.error = message
                cursor.lease_token = cursor.lease_until = None
                await db.commit()
        _state["last_error"] = message
        logger.warning("Apple通知补偿失败 type=%s", type(exc).__name__)
        return False


async def _loop():
    """一次事件失败不会终止服务；数据库租约保护重启与重复运行。"""
    next_reconcile = 0.0
    while True:
        _state["heartbeat_at"] = now().isoformat()
        try:
            if not apple_client.apple_configured():
                await asyncio.sleep(get_app_settings().apple_notification_poll_seconds)
                continue
            worked = await process_notification_once()
            if time.monotonic() >= next_reconcile:
                more = await reconcile_history_once()
                next_reconcile = time.monotonic() + (0 if more else get_app_settings().apple_reconciliation_seconds)
            if not worked:
                await asyncio.sleep(get_app_settings().apple_notification_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _state["last_error"] = _safe_error(exc)
            logger.warning("Apple运行时暂时异常 type=%s", type(exc).__name__)
            await asyncio.sleep(get_app_settings().apple_notification_poll_seconds)


async def start_apple_runtime() -> None:
    """只有真实Apple配置齐备时启用，不读取市场新购/展示开关。"""
    global _task
    if apple_client.apple_configured() and (_task is None or _task.done()):
        _task = asyncio.create_task(_loop(), name="marketplace-apple-notifications")


async def stop_apple_runtime() -> None:
    """关闭API时取消循环，处理中事务自动回滚，租约到期后恢复。"""
    global _task
    task, _task = _task, None
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
