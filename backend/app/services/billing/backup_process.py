"""Backup process fallback for Windows event loops without subprocess transports."""
import asyncio
import subprocess

async def run_process(args, env=None, timeout=300):
    # Popen only starts the child; polling below never blocks the event loop.
    # No shell and no credentials in argv. Output may contain secrets, so discard it.
    process = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    async def wait():
        while process.poll() is None:
            await asyncio.sleep(0.1)
        return process.returncode
    try:
        return await asyncio.wait_for(wait(), timeout)
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await asyncio.to_thread(process.wait)
