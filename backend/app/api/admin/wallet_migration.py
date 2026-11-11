"""Admin-only cutover, report and authenticated database backup download."""
from fastapi import APIRouter, Depends, HTTPException, Query
import asyncio
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
import hashlib
from pydantic import BaseModel, Field, field_validator
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_admin
from app.models import User
from app.services.billing import wallet_cutover as cutover

router = APIRouter(prefix="/settings/wallet-migration")


class Action(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    job_id: str = Field(default="", max_length=32, pattern=r"^[a-f0-9]*$")

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("请填写至少 3 字的操作理由")
        return value.strip()


@router.get("", summary="只读核对统一钱包历史资金")
async def report(_admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    return await cutover.report(db)


class Approval(Action):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    environment: str = Field(pattern=r"^(Production|Sandbox)$")


@router.post("/approvals/{user_id}", summary="逐户确认缺失的历史期初余额")
async def approve(user_id: int, body: Approval, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    try:
        return await cutover.approve(db, user_id, body.fingerprint, body.environment, body.job_id, admin.id, body.reason)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc


@router.post("/{action}", summary="暂停资金写入、迁移或复核恢复")
async def act(action: str, body: Action, admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    if action not in ("pause", "apply", "resume"):
        raise HTTPException(404, "操作不存在")
    try:
        if action == "pause":
            return await cutover.pause(db, admin.id, body.reason)
        result = await getattr(cutover, action)(db, body.job_id, admin.id, body.reason)
        if action == "apply":
            try:
                cutover.backup_manifest(body.job_id, migration_status="completed")
            except (OSError, ValueError):
                logging.getLogger(__name__).warning("Wallet backup journal unavailable after committed migration")
        return result
    except Exception as exc:
        await db.rollback()
        safe = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "迁移未完成，请刷新报告；维护状态保留。请检查服务器日志、数据库锁和备份工具。"
        logging.getLogger(__name__).warning("Wallet cutover failed action=%s type=%s", action, type(exc).__name__)
        # Failure audit is separate from the rolled-back financial transaction.
        try:
            await cutover.exclusive(db)
            value = await cutover.state(db)
            if value.get("paused") and value.get("job_id") == body.job_id:
                if action == "apply" and value.get("phase") != "completed":
                    try:
                        cutover.backup_manifest(body.job_id, migration_status="failed",
                            migration_error="迁移未完成，请核对审计和服务器日志")
                    except (OSError, ValueError):
                        logging.getLogger(__name__).warning("Wallet backup journal unavailable on failure")
                cutover.audit(value, "failed:" + action, admin.id, body.reason + "；" + safe)
                await cutover.save_state(db, value)
                await db.commit()
        except Exception:
            await db.rollback()
        raise HTTPException(409, safe) from exc


@router.get("/backup", summary="下载当前迁移数据库备份（仅管理员）")
async def download(job_id: str | None = Query(default=None, pattern=r"^[a-f0-9]{32}$"),
                   _admin: User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    value = await cutover.state(db)
    job = job_id or value.get("job_id", "")
    if len(job) != 32 or any(c not in "0123456789abcdef" for c in job):
        raise HTTPException(404, "没有备份")
    path = cutover.BACKUPS / (job + ".dump")
    record = next((item for item in cutover.backup_records() if item["job_id"] == job), {})
    digest = record.get("sha256") or (value.get("backup_sha256") if job == value.get("job_id") else None)
    if not digest or not path.is_file():
        raise HTTPException(404, "备份未完成或当前容器未挂载备份目录")
    stream = None
    try:
        stream = path.open("rb")
        actual = await asyncio.to_thread(hashlib.file_digest, stream, "sha256")
        if actual.hexdigest() != digest:
            raise ValueError("checksum mismatch")
        stream.seek(0)
    except (OSError, ValueError) as exc:
        if stream:
            stream.close()
        raise HTTPException(409, "备份文件校验失败，禁止下载，请联系管理员核对") from exc

    async def chunks():
        # Verify and stream the same open file, even if a retry archives its path.
        try:
            while data := await asyncio.to_thread(stream.read, 1024 * 1024):
                yield data
        finally:
            stream.close()

    return StreamingResponse(chunks(), media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"', "X-Backup-SHA256": digest},
        background=BackgroundTask(stream.close))
