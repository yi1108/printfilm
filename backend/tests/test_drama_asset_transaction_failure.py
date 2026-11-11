"""资产用量 flush 失败后，必须回滚再保存失败状态，保留原始异常。"""
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models_teams  # noqa: F401
from app.models import User
from app.models_drama import DramaAsset, DramaProject, DramaScript
from app.services.drama import jobs


@pytest.mark.parametrize("kind", ["image", "video"])
async def test_asset_job_recovers_failed_flush(tmp_path: Path, monkeypatch, kind: str):
    """真实数据库使 Session 进入 pending rollback；失败处理仍须可写库。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'assets.db').as_posix()}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            for model in (User, DramaProject, DramaScript, DramaAsset):
                await conn.run_sync(model.__table__.create)
        async with sessions() as db:
            db.add(User(id=1, email="asset@test.local", hashed_password="unused"))
            db.add(DramaProject(id=1, user_id=1, title="资产事务测试"))
            db.add(DramaAsset(id=1, project_id=1, type="none", name="镜头", asset_type=kind,
                              url="/static/previous.mp4", params={"visualPrompt": "镜头"}))
            await db.commit()

        async def failed_generation(db, _user, _project, *args, **kwargs):
            """模拟交付过程中用量落库失败，留下未提交的资产修改。"""
            asset = await db.get(DramaAsset, 1)
            asset.url = "/static/uncommitted.mp4"
            db.add(User(email="asset@test.local", hashed_password="duplicate"))
            await db.flush()

        async def resolve_prompt(*args, **kwargs):
            return "镜头"

        monkeypatch.setattr(jobs, "AsyncSessionLocal", sessions)
        monkeypatch.setattr(jobs, f"generate_asset_{kind}", failed_generation)
        monkeypatch.setattr(jobs, "resolve_visual_prompt_for_asset", resolve_prompt)
        if kind == "video":
            result = await jobs.run_asset_video_job(1, 1, "镜头", 1)
        else:
            result = await jobs.run_asset_image_job(1, 1, "镜头", asset_id=1, name="镜头", kind="none")
        assert result["ok"] is False
        assert "IntegrityError" in result["error"]
        assert "PendingRollbackError" not in result["error"]
        async with sessions() as db:
            asset = await db.get(DramaAsset, 1)
            assert asset.params["generation"]["status"] == "failed"
            assert "IntegrityError" in asset.params["generation"]["error"]
            assert asset.url == "/static/previous.mp4"
    finally:
        await engine.dispose()
