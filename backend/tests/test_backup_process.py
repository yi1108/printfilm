import asyncio
import sys
from unittest.mock import AsyncMock
import pytest
from app.services.billing import backup_process, wallet_cutover

@pytest.mark.asyncio
async def test_unsupported_loop_uses_fallback(monkeypatch):
    monkeypatch.setattr(asyncio,"create_subprocess_exec",AsyncMock(side_effect=NotImplementedError))
    await wallet_cutover.command(sys.executable,"-c","raise SystemExit(0)")
    with pytest.raises(ValueError,match="备份或校验失败"):
        await wallet_cutover.command(sys.executable,"-c","raise SystemExit(2)")

@pytest.mark.asyncio
@pytest.mark.parametrize("cancel",[False,True])
async def test_child_is_stopped_on_timeout_or_cancel(monkeypatch,cancel):
    original=backup_process.subprocess.Popen
    children=[]
    def spawn(*a,**kw):
        child=original(*a,**kw);children.append(child);return child
    monkeypatch.setattr(backup_process.subprocess,"Popen",spawn)
    task=asyncio.create_task(backup_process.run_process(
        [sys.executable,"-c","import time; time.sleep(60)"],timeout=10 if cancel else 0.2))
    if cancel:
        await asyncio.sleep(0.15)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    assert len(children)==1 and children[0].poll() is not None
