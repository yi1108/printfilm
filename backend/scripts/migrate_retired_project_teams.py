"""Run with --apply on the intended local DB. Default is a read-only count."""
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from app.database import AsyncSessionLocal, engine
# Register legacy foreign keys without creating or deleting any tables.
from app import models, models_agent, models_creation, models_drama, models_settings, models_tasks, models_teams, models_team_billing, models_team_locks
from app.printfilm_studio.project_team_migration import migrate_project_teams
async def main():
    try:
        async with AsyncSessionLocal() as db:
            if '--apply' in sys.argv:
                print(await migrate_project_teams(db))
                await db.commit()
            else:
                print({'legacy_projects': await db.scalar(text('select count(*) from drama_projects where team_id is not null'))})
    finally:
        await engine.dispose()
if __name__ == '__main__':
    asyncio.run(main())
