import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models_teams  # noqa: F401
from app.models import User
from app.models_drama import DramaAsset, DramaEpisode, DramaProject, DramaScript
from app.models_tasks import TaskRun
from app.printfilm_studio.agent.queries import load_project_view
from app.printfilm_studio.canvas.service import get_project


@pytest.mark.asyncio
@pytest.mark.parametrize('source, expected', [
    ('自由画布创作项目', 'canvas'),
    ('普通剧本', 'script'),
    (None, 'script'),
])
async def test_legacy_project_view_loads_script_in_async_session(tmp_path, source, expected):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'view.db').as_posix()}")
    try:
        async with engine.begin() as conn:
            for model in (User, DramaProject, DramaScript, DramaEpisode, DramaAsset, TaskRun):
                await conn.run_sync(model.__table__.create)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            db.add(User(id=1, email='view@example.test', hashed_password='unused'))
            db.add(DramaProject(id=8, user_id=1, title='旧项目', params={}))
            if source is not None:
                db.add(DramaScript(project_id=8, source=source))
            await db.commit()
        async with factory() as db:
            user = await db.get(User, 1)
            project = await get_project(db, 8, user)
            assert 'script' in inspect(project).unloaded
            view = await load_project_view(db, project, user)
            assert view['workflow'] == expected
            assert view['id'] == 8
            # The run guard reloads the project between tool calls.
            await get_project(db, 8, user)
            assert (await load_project_view(db, project, user))['workflow'] == expected
            assert project.params == {}
    finally:
        await engine.dispose()
