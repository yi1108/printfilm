"""Small supervised maintenance loop, independent of OSS and media conversion."""
import asyncio
import logging

logger = logging.getLogger(__name__)
_task: asyncio.Task | None = None


async def _loop():
    while True:
        try:
            from .app_bootstrap import schema_ready
            if await schema_ready():
                from .app_engagement import run_engagement_maintenance_once
                await run_engagement_maintenance_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("互动运营维护失败，下轮自动重试")
        await asyncio.sleep(10)


async def start_engagement_runtime():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="marketplace-engagement-maintenance")


async def stop_engagement_runtime():
    global _task
    if _task is not None:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
