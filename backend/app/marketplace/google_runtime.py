"""Durable delivery, post-commit consumption, and paged voided-purchase recovery."""
import asyncio
import logging
from app.services.billing.diagnostics import failure_fields
import time
import uuid
import re
from datetime import timedelta
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from app.database import AsyncSessionLocal
from app.services.model_settings import _decrypt_secret
from .google_models import GoogleWork, GooglePurchase, GoogleCursor, GoogleVoid, GoogleNotification
from .google_config import read
from .google_service import apply_proof, lock_user, refund, digest
from . import google_client
from .service import now

logger = logging.getLogger(__name__)
_task = None


async def work_once():
    async with AsyncSessionLocal() as db:
        settings, config = await read(db)
        if not settings or not settings.credentials:
            return False
        secret = settings.credentials
        work = await db.scalar(select(GoogleWork).where(GoogleWork.next_attempt_at <= now(),
            or_(GoogleWork.lease_until.is_(None), GoogleWork.lease_until < now()))
            .order_by(GoogleWork.next_attempt_at, GoogleWork.id).with_for_update(skip_locked=True).limit(1))
        if not work:
            return False
        lease = uuid.uuid4().hex
        work.lease_key, work.lease_until = lease, now() + timedelta(minutes=5)
        data = dict(id=work.id, package=work.package_name, product=work.product_id,
            token=_decrypt_secret(work.token_secret), hash=work.token_hash)
        voided = await db.scalar(select(GoogleVoid.id).where(GoogleVoid.package_name == work.package_name,
            GoogleVoid.token_hash == work.token_hash))
        await db.commit()
    try:
        proof = None if voided else await google_client.query(secret, data["package"], data["product"], data["token"])
        async with AsyncSessionLocal() as db:
            # A stale claim cannot perform financial work; extend/validate before it.
            work = await db.scalar(select(GoogleWork.id).where(GoogleWork.id == data["id"],
                GoogleWork.lease_key == lease, GoogleWork.lease_until > now()))
            if not work:
                return True
            if voided:
                txn = await db.scalar(select(GooglePurchase).where(GooglePurchase.package_name == data["package"],
                    GooglePurchase.token_hash == data["hash"]))
                if txn:
                    await lock_user(db, txn.user_id, allow_closed=True)
                    txn = await db.scalar(select(GooglePurchase).where(GooglePurchase.id == txn.id)
                        .with_for_update().execution_options(populate_existing=True))
                    await refund(db, txn)
                    if txn.status == "pending":
                        txn.status = "refunded"
                        from app.models import Order
                        order = await db.get(Order, txn.order_id)
                        if order:
                            order.status = "refunded"
                result = {"consume_purchase": False, "status": "refunded"}
            else:
                result = await apply_proof(db, data["package"], data["product"], data["token"], proof, config)
            await db.commit()
        # Only committed credit may be consumed; never consume a pending purchase.
        if result["consume_purchase"] and proof.get("consumptionState") != 1:
            await google_client.consume(secret, data["package"], data["product"], data["token"])
        async with AsyncSessionLocal() as db:
            work = await db.scalar(select(GoogleWork).where(GoogleWork.id == data["id"], GoogleWork.lease_key == lease).with_for_update())
            if work:
                work.attempts, work.last_error = 0, ""
                work.lease_key = work.lease_until = None
                work.next_attempt_at = now() + timedelta(seconds=30 if result["status"] == "pending" else 21600)
                if result["consume_purchase"]:
                    txn = await db.scalar(select(GooglePurchase).where(GooglePurchase.package_name == data["package"],
                        GooglePurchase.token_hash == data["hash"]))
                    if txn:
                        txn.consumed = True
                await db.execute(update(GoogleNotification).where(GoogleNotification.token_hash == data["hash"])
                    .values(status="pending" if result["status"] == "pending" else "processed"))
                await db.commit()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # No raw exception: HTTP URLs can contain purchase tokens and credentials.
        logger.warning("Google purchase retry failed type=%s status=%s code=%s", *failure_fields(exc))
        detail = getattr(exc, "detail", None)
        code = detail.get("code", "") if isinstance(detail, dict) else ""
        safe_error = code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,99}", code) else type(exc).__name__
        async with AsyncSessionLocal() as db:
            work = await db.scalar(select(GoogleWork).where(GoogleWork.id == data["id"], GoogleWork.lease_key == lease).with_for_update())
            if work:
                work.attempts += 1
                work.last_error = safe_error
                work.next_attempt_at = now() + timedelta(seconds=min(3600, 15 * 2 ** min(work.attempts, 8)))
                work.lease_key = work.lease_until = None
                await db.commit()
    return True


async def voided_once():
    """Page every window before advancing. Re-scan overlap to catch late voids."""
    async with AsyncSessionLocal() as db:
        settings, config = await read(db)
        if not settings or not settings.credentials:
            return
        secret, package = settings.credentials, config["package_name"]
        instant = now()
        end_ms = int(instant.timestamp() * 1000)
        start_ms = end_ms - 29 * 86400000
        await db.execute(insert(GoogleCursor).values(key=package, start_ms=str(start_ms),
            end_ms=str(min(end_ms, start_ms + 86400000)), page_token="").on_conflict_do_nothing(index_elements=["key"]))
        cursor = await db.scalar(select(GoogleCursor).where(GoogleCursor.key == package).with_for_update())
        if cursor.lease_until and cursor.lease_until > instant:
            return
        lease = uuid.uuid4().hex
        cursor.lease_key, cursor.lease_until = lease, instant + timedelta(minutes=5)
        params = {"startTime": cursor.start_ms, "endTime": cursor.end_ms, "type": 0, "maxResults": 1000}
        if cursor.page_token:
            params["token"] = cursor.page_token
        await db.commit()
    result = await google_client.request(secret, package, "purchases/voidedpurchases", params=params)
    async with AsyncSessionLocal() as db:
        cursor = await db.scalar(select(GoogleCursor).where(GoogleCursor.key == package,
            GoogleCursor.lease_key == lease, GoogleCursor.lease_until > now()).with_for_update())
        if not cursor:
            return
        for item in result.get("voidedPurchases", []):
            raw = item.get("purchaseToken")
            if not raw:
                continue
            hashed = digest(raw)
            await db.execute(insert(GoogleVoid).values(package_name=package, token_hash=hashed)
                .on_conflict_do_nothing(index_elements=["package_name", "token_hash"]))
            txn = await db.scalar(select(GooglePurchase).where(GooglePurchase.package_name == package, GooglePurchase.token_hash == hashed))
            if txn:
                # Hold exactly one user per transaction: don't batch user/creator locks.
                # Persist tombstone and let its durable token worker do the reversal.
                work = await db.scalar(select(GoogleWork).where(GoogleWork.package_name == package, GoogleWork.token_hash == hashed))
                if work:
                    work.next_attempt_at = now()
        cursor.page_token = result.get("tokenPagination", {}).get("nextPageToken", "")
        if not cursor.page_token:
            limit = int(now().timestamp() * 1000)
            start = int(cursor.end_ms)
            if start >= limit - 60000:
                start = max(limit - 2 * 86400000, limit - 29 * 86400000)
            cursor.start_ms, cursor.end_ms = str(start), str(min(limit, start + 86400000))
        cursor.lease_key = cursor.lease_until = None
        await db.commit()


async def loop():
    last_voided = 0
    while True:
        worked = False
        try:
            from .app_bootstrap import schema_ready
            if await schema_ready():
                from app.services.billing.wallet_cutover import background_guard
                from app.wallet_cutover_middleware import BarrierSession
                async with background_guard(BarrierSession) as allowed:
                    if allowed:
                        worked = await work_once()
                        if time.monotonic() - last_voided > 60:
                            await voided_once()
                            last_voided = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Google payment worker failed type=%s status=%s code=%s", *failure_fields(exc))
        await asyncio.sleep(0 if worked else 3)


async def start():
    global _task
    if not _task or _task.done():
        _task = asyncio.create_task(loop(), name="google-play-delivery")


async def stop():
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
