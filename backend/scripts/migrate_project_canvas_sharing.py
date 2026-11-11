"""Add only project membership/invitation tables; never modify existing teams or wallets.

Run from backend: .venv/Scripts/python.exe scripts/migrate_project_canvas_sharing.py
Use --check to verify the tables without writes.
"""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect
from app.database import engine
import app.models_teams  # noqa: F401
from app.printfilm_studio.sharing import CanvasMember, CanvasInvitation


async def main():
    try:
        async with engine.begin() as conn:
            for model in (CanvasMember, CanvasInvitation):
                if '--check' in sys.argv:
                    present = await conn.run_sync(lambda sync, table=model.__tablename__: inspect(sync).has_table(table))
                    if not present:
                        raise SystemExit(f'Missing table: {model.__tablename__}')
                else:
                    await conn.run_sync(lambda sync, table=model.__table__: table.create(sync, checkfirst=True))
        print('Project sharing schema ready')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
