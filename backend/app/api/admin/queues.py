# Admin task runtime monitoring API (legacy /queues path for dashboard compat)
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_admin
from app.models import User
from app.schemas import AdminQueuesOut
from app.services.tasks.runtime import runtime_summary
from app.services.tasks.service import get_task_stats_admin

router = APIRouter()


@router.get("/queues", response_model=AdminQueuesOut)
async def admin_queues(
    detail: bool = Query(default=False, description="保留参数，任务中心请用 /admin/tasks"),
    _admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminQueuesOut:
    # 兼容旧路径：返回 task_runs 聚合统计，不再暴露历史 worker 控制项
    _ = detail
    settings = get_settings()
    stats = await get_task_stats_admin(db)
    runtime = runtime_summary()
    running_jobs = int(runtime.get("scheduler_running_jobs") or 0)
    max_concurrency = int(settings.task_runtime_max_concurrency)
    pending = int(stats.get("pending_count") or 0)
    active = int(stats.get("active_count") or 0)
    return AdminQueuesOut.model_validate(
        {
            "ok": True,
            "redis_ok": False,
            "unacked": 0,
            "total_pending": pending,
            "active_count": active,
            "reserved_count": int(stats.get("leased_count") or 0),
            "queues": [
                {
                    "name": item["domain"],
                    "label": item["domain"],
                    "pending": item["pending"],
                    "sample": [],
                }
                for item in stats.get("domains") or []
            ],
            "pending_tasks": [],
            "active_tasks": [],
            "reserved_tasks": [],
            "runtime": {"mode": "task_runtime", "running_jobs": running_jobs, "max_concurrency": max_concurrency},
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    )
