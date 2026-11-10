"""Shared flags, recommendation ordering and signed feed cursors."""
import base64
from datetime import datetime
import hashlib
import hmac
import json

from sqlalchemy import and_, case, func, select

from app.config import get_settings
from .app_access import error
from .curation_models import ContentCuration, CurationRevision


def configuration(row, target_type: str, target_id: int) -> dict:
    return {"target_type": target_type, "target_id": target_id,
            "is_featured": bool(row and row.is_featured), "is_pinned": bool(row and row.is_pinned),
            "pin_priority": row.pin_priority if row else 100, "version": row.version if row else 0}


async def flags(db, target_type: str, target_id: int) -> dict:
    if target_type not in ("work", "series"):
        return {"is_featured": False, "is_pinned": False}
    row = await db.scalar(select(ContentCuration).where(ContentCuration.target_type == target_type, ContentCuration.target_id == target_id))
    return {"is_featured": bool(row and row.is_featured), "is_pinned": bool(row and row.is_pinned)}


async def admin_fields(db, target_type: str, target_id: int) -> dict:
    row = await db.scalar(select(ContentCuration).where(ContentCuration.target_type == target_type, ContentCuration.target_id == target_id))
    value = configuration(row, target_type, target_id)
    return {"is_featured": value["is_featured"], "is_pinned": value["is_pinned"],
            "pin_priority": value["pin_priority"], "curation_version": value["version"]}


def join_curation(query, model, kind: str):
    return query.outerjoin(ContentCuration, and_(ContentCuration.target_type == kind, ContentCuration.target_id == model.id))


def ordering_columns():
    pinned = case((ContentCuration.is_pinned.is_(True), 1), else_=0)
    priority = case((ContentCuration.is_pinned.is_(True), ContentCuration.pin_priority), else_=0)
    featured = case((ContentCuration.is_featured.is_(True), 1), else_=0)
    return pinned.label("pin"), priority.label("priority"), featured.label("feature")


def filter_curation(query, model, kind: str, selection: str):
    if not selection:
        return query
    if selection not in ("featured", "pinned", "normal"):
        error("MARKETPLACE_CURATION_FILTER_INVALID", "运营筛选条件无效", 422)
    query = join_curation(query, model, kind)
    if selection == "featured":
        return query.where(ContentCuration.is_featured.is_(True))
    if selection == "pinned":
        return query.where(ContentCuration.is_pinned.is_(True))
    return query.where(func.coalesce(ContentCuration.is_featured, False).is_(False),
                       func.coalesce(ContentCuration.is_pinned, False).is_(False))


async def revision(db) -> int:
    return int(await db.scalar(select(CurationRevision.revision).where(CurationRevision.id == 1)) or 0)


def feed_fingerprint(*, q, category, category_code, content_type, sort, user_id) -> str:
    # Locale affects labels, never membership or ordering.
    values = [q, "" if category_code else category, category_code, content_type, sort, user_id]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:24]


def encode_feed_cursor(row, *, sort: str, fingerprint: str, revision: int) -> str:
    values = [row.timestamp.isoformat(), row.kind, row.record_id]
    if sort == "recommended":
        values = [row.pin, row.priority, row.feature, *values]
    body = json.dumps({"v": 2, "sort": sort, "filter": fingerprint, "revision": revision, "key": values}, separators=(",", ":")).encode()
    signature = hmac.new(get_settings().secret_key.encode(), body, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(signature + body).decode().rstrip("=")


def decode_feed_cursor(value: str, *, sort: str, fingerprint: str, revision: int):
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        signature, body = decoded[:16], decoded[16:]
        if not hmac.compare_digest(signature, hmac.new(get_settings().secret_key.encode(), body, hashlib.sha256).digest()[:16]):
            raise ValueError()
        payload = json.loads(body)
        if isinstance(payload, list):
            # Pre-upgrade time cursors are meaningful only in chronological mode.
            if sort != "latest":
                error("MARKETPLACE_FEED_UPDATED", "列表已更新，请刷新", 409)
            values = payload
        else:
            if not isinstance(payload, dict) or payload.get("v") != 2 or payload.get("sort") != sort or payload.get("filter") != fingerprint:
                raise ValueError()
            if sort == "recommended" and payload.get("revision") != revision:
                error("MARKETPLACE_FEED_UPDATED", "列表已更新，请刷新", 409)
            values = payload["key"]
        expected = 6 if sort == "recommended" else 3
        if not isinstance(values, list) or len(values) != expected:
            raise ValueError()
        timestamp, kind, record_id = values[-3:]
        parsed = datetime.fromisoformat(timestamp)
        if not parsed.tzinfo or kind not in ("work", "series") or type(record_id) is not int or record_id < 1:
            raise ValueError()
        if sort == "recommended":
            pin, priority, feature = values[:3]
            if type(pin) is not int or pin not in (0, 1) or type(feature) is not int or feature not in (0, 1) or type(priority) is not int or not 0 <= priority <= 9999:
                raise ValueError()
            return pin, priority, feature, parsed, kind, record_id
        return parsed, kind, record_id
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, OverflowError):
        error("MARKETPLACE_CURSOR_INVALID", "分页位置无效，请刷新列表", 422)
