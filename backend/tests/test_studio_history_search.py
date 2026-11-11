import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.deps import get_current_user
from app.models import ToolRun, User


@pytest.mark.asyncio
async def test_history_search_is_literal_paginated_and_owner_scoped():
    import app.main  # Register referenced tables without starting the application.
    from app.api.tools import router

    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            owner = User(email='search-owner@test.local', hashed_password='test')
            other = User(email='search-other@test.local', hashed_password='test')
            db.add_all([owner, other])
            await db.flush()
            for user, prompt, status in [(owner, '桃园 100%_a', 'succeeded'),
                                         (owner, '桃园 100%_b', 'succeeded'),
                                         (owner, '桃园 100xZa', 'succeeded'),
                                         (owner, '桃园 100%_failed', 'failed'),
                                         (other, '桃园 100%_private', 'succeeded')]:
                db.add(ToolRun(user_id=user.id, tool_id='t2i', kind='image', status=status, prompt=prompt))
            await db.commit()
        app = FastAPI()
        app.include_router(router, prefix='/api')

        async def database():
            async with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: owner
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            params = {'q': '  桃园 100%_  ', 'kind': 'image', 'status': 'succeeded', 'page_size': 1}
            first = await client.get('/api/tools/runs', params=params)
            assert first.status_code == 200, first.text
            result = first.json()
            assert result['total'] == 2
            assert result['counts']['all'] == 3
            assert result['items'][0]['prompt'] == '桃园 100%_b'
            second = (await client.get('/api/tools/runs', params={**params, 'page': 2})).json()
            assert second['items'][0]['prompt'] == '桃园 100%_a'
            assert (await client.get('/api/tools/runs', params={'q': 'private'})).json()['total'] == 0
    finally:
        await engine.dispose()
