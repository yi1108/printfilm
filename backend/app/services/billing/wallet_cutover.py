"""Administrator wallet cutover. Financial replay remains in wallet_migration.

State is persisted separately from runtime settings so a settings save cannot erase
maintenance. Maintenance survives errors/restarts; only explicit resume clears it.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import uuid
from datetime import UTC, datetime
from contextlib import asynccontextmanager

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.config import get_settings, reload_settings
from app.models_settings import AppSettings
from .wallet_migration import assert_no_active_tasks, build_report, apply_plans

STATE_ID = "wallet_cutover"
LOCK = 73409112
BACKUPS = Path(__file__).resolve().parents[3] / "var" / "wallet-backups"
_revision = None


@asynccontextmanager
async def background_guard(factory):
    """Serialize full Apple network+fulfilment cycles against cutover."""
    async with factory() as db:
        await db.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": LOCK})
        value = await runtime_state(db)
        await sync_runtime(db, value)
        if value.get("paused"):
            await db.rollback()
        yield not value.get("paused", False)


async def state(db):
    row = await db.scalar(select(AppSettings).where(AppSettings.id == STATE_ID)
                          .execution_options(populate_existing=True))
    return dict(row.config_json or {}) if row else {}


async def runtime_state(db):
    """Hot paths read two JSON keys, never the financial report/audit payload."""
    row = (await db.execute(select(AppSettings.config_json["paused"], AppSettings.config_json["revision"])
                           .where(AppSettings.id == STATE_ID))).one_or_none()
    return {"paused": bool(row[0]), "revision": row[1]} if row else {}


async def save_state(db, value):
    row = await db.get(AppSettings, STATE_ID)
    if row is None:
        row = AppSettings(id=STATE_ID)
        db.add(row)
    row.config_json = value
    await db.flush()


async def sync_runtime(db, value):
    """Refresh each API/scheduler process after the committed cutover revision."""
    global _revision
    revision = value.get("revision")
    if revision and revision != _revision:
        from app.services.model_settings import _refresh_overlay, _decrypt_flat_config
        row = await db.scalar(select(AppSettings).where(AppSettings.id == "default")
                              .execution_options(populate_existing=True))
        if row:
            _refresh_overlay({"flat": _decrypt_flat_config(row.config_json or {})})
            reload_settings()
        _revision = revision


async def configured_flat(db):
    """Read the database configuration, not a potentially older worker cache."""
    from app.services.model_settings import _decrypt_flat_config, _effective_flat
    row = await db.scalar(select(AppSettings).where(AppSettings.id == "default")
                          .execution_options(populate_existing=True))
    return _effective_flat(_decrypt_flat_config(row.config_json or {}) if row else None)


async def report(db, environment=None):
    from .wallet_schema import check_schema
    missing = await (await db.connection()).run_sync(check_schema)
    value = await state(db)
    if missing:
        return {"state": value, "missing_schema": missing, "accounts": [], "ready": 0,
                "blocked": 0, "already_migrated": 0, "active_tasks": False}
    environment = environment or (await configured_flat(db))["wallet_environment"]
    rows, _ = await build_report(db, environment)
    active = False
    try:
        await assert_no_active_tasks(db)
    except RuntimeError:
        active = True
    return {"state": value, "missing_schema": [], "accounts": rows, "active_tasks": active,
            **{key: sum(r["status"] == key for r in rows)
               for key in ("ready", "blocked", "already_migrated")}}


async def validate_activation(db, environment):
    """A settings switch never substitutes for historical source reconciliation."""
    value = await report(db, environment)
    if value["missing_schema"] or value["ready"] or value["blocked"] or value["active_tasks"]:
        raise ValueError("统一钱包尚未完成核对：待迁移 %s 个，异常 %s 个，在途任务 %s。请先使用资金迁移入口。"
                         % (value["ready"], value["blocked"], "有" if value["active_tasks"] else "无"))


async def validate_settings_activation(db, environment):
    await validate_activation(db, environment)
    # A clean preview alone is not a write barrier: a legacy registration or
    # payment could have passed admission immediately before a settings save.
    # Enabling is therefore owned by the exclusive, atomic cutover transaction.
    raise ValueError("资金核对通过；请通过统一钱包迁移入口执行切换，不能在业务运行中直接开启。")


async def exclusive(db):
    await db.execute(text("SET LOCAL lock_timeout = '5s'"))
    # Queue the exclusive lock so a busy stream of new shared requests cannot
    # starve pause forever. lock_timeout bounds the operator's wait.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})


def audit(value, action, admin_id, reason, report_snapshot=None):
    value["history"] = [*value.get("history", []), {
        "action": action, "operator_id": admin_id, "reason": reason,
        "at": datetime.now(UTC).isoformat(), "job_id": value.get("job_id"),
        "backup_sha256": value.get("backup_sha256"),
        **({"report": report_snapshot} if report_snapshot is not None else {}),
    }]


async def pause(db, admin_id, reason):
    await exclusive(db)
    value = await state(db)
    if value.get("paused"):
        return value
    value.update(paused=True, job_id=uuid.uuid4().hex, phase="paused",
                 backup_sha256=None, migrated_count=None)
    audit(value, "pause", admin_id, reason)
    await save_state(db, value)
    await db.commit()
    return value


async def command(*args, env=None):
    try:
        process = await asyncio.create_subprocess_exec(*args, env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise ValueError("服务器未安装 PostgreSQL 备份工具，请发布包含 pg_dump/pg_restore 的 API 镜像。") from exc
    try:
        code = await asyncio.wait_for(process.wait(), 300)
    except (TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.wait()
        raise
    if code:
        raise ValueError("数据库备份或校验失败，未迁移。请检查备份工具版本、数据库权限和磁盘空间。")


async def backup(job_id):
    """Credentials only in child environment, never argv, response or logs."""
    url = make_url(get_settings().database_url).set(drivername="postgresql")
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = BACKUPS / (job_id + ".dump")
    temporary = BACKUPS / (job_id + ".partial")
    env = dict(os.environ, PGHOST=url.host or "localhost", PGPORT=str(url.port or 5432),
               PGUSER=url.username or "", PGPASSWORD=url.password or "", PGDATABASE=url.database or "")
    # Preserve SSL parameters without putting a password in the process arguments.
    for key in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
        if key in url.query:
            env["PG" + key.upper()] = str(url.query[key])
    await command("pg_dump", "--format=custom", "--file", str(temporary), env=env)
    await command("pg_restore", "--list", str(temporary), env=env)
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise ValueError("数据库备份为空，未迁移。")
    def digest():
        with temporary.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    result = await asyncio.to_thread(digest)
    temporary.replace(path)
    return result


async def apply(db, job_id, admin_id, reason):
    await exclusive(db)
    value = await state(db)
    if not value.get("paused") or value.get("job_id") != job_id:
        raise ValueError("暂停状态或迁移编号已变化，请刷新核对报告。")
    if value.get("phase") == "completed":
        return value
    check = await report(db)
    if check["missing_schema"] or check["blocked"] or check["active_tasks"]:
        raise ValueError("结构、历史来源或在途任务检查未通过；保持暂停，请查看核对报告。")
    # Background workers are not HTTP requests. Lock task/financial tables and
    # recheck AFTER acquiring them; no plan from the preview is ever executed.
    await db.execute(text("SET LOCAL statement_timeout = '120s'"))
    await db.execute(text("LOCK TABLE task_runs IN SHARE MODE"))
    from sqlalchemy import inspect
    from app.models_wallet import WalletBase
    tables = await (await db.connection()).run_sync(lambda c: set(inspect(c).get_table_names()))
    names = ["users", "wallet_ledger", "orders", *WalletBase.metadata.tables,
             "marketplace_coin_wallets", "marketplace_coin_lots", "marketplace_coin_allocations",
             "marketplace_coin_unlocks", "marketplace_apple_transactions", "app_settings"]
    for name in sorted(set(names) & tables):
        await db.execute(text(f'LOCK TABLE "{name}" IN SHARE ROW EXCLUSIVE MODE'))
    await assert_no_active_tasks(db)
    digest = await backup(job_id)
    environment = (await configured_flat(db))["wallet_environment"]
    rows, plans = await build_report(db, environment)
    if any(row["status"] == "blocked" for row in rows):
        raise ValueError("锁内重新核对发现账目变化，未迁移；请刷新报告。")
    reference = f"admin:{admin_id}:{job_id}:sha256:{digest}"
    await apply_plans(db, plans, environment, reference)
    await db.flush()
    await validate_activation(db, environment)
    # Settings and migrated balances commit together. Maintenance remains on.
    from app.services.model_settings import _get_or_create_app_row, _decrypt_flat_config, _encrypt_flat_config, _effective_flat
    row = await _get_or_create_app_row(db)
    config = dict(row.config_json or {})
    flat = _effective_flat(_decrypt_flat_config(config))
    flat["unified_wallet_enabled"] = True
    config["flat"] = _encrypt_flat_config(flat)
    row.config_json = config
    value.update(phase="completed", revision=job_id, backup_sha256=digest, migrated_count=len(plans))
    audit(value, "apply", admin_id, reason, {"environment": environment, "accounts": rows,
                                            "migrated_count": len(plans)})
    await save_state(db, value)
    await db.commit()
    await sync_runtime(db, value)
    return value


async def resume(db, job_id, admin_id, reason):
    await exclusive(db)
    value = await state(db)
    if not value.get("paused") or value.get("job_id") != job_id:
        raise ValueError("暂停状态或迁移编号已变化，请刷新。")
    if value.get("phase") == "completed":
        await sync_runtime(db, value)
        flat = await configured_flat(db)
        if not flat["unified_wallet_enabled"]:
            raise ValueError("迁移后统一钱包配置被修改，不能恢复；请核对系统配置。")
        await validate_activation(db, flat["wallet_environment"])
    # Before apply this only cancels maintenance, restoring the exact original
    # accounting mode; it never certifies or changes an account.
    value["paused"] = False
    audit(value, "resume", admin_id, reason)
    await save_state(db, value)
    await db.commit()
    return value
