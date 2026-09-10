"""管理端只读列表筛选：users / works / usage / templates / drama-projects。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin.drama_projects import list_drama_projects
from app.api.admin.templates import list_templates
from app.api.admin.usage import list_usage_events
from app.api.admin.users import list_users
from app.api.admin.works import list_works
from app.models import Template, UsageEvent, User, Work
from app.models_drama import DramaProject, DramaScript
from tests.conftest import make_user


async def _make_admin(db: AsyncSession) -> User:
    admin = await make_user(db)
    admin.email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    admin.role = "admin"
    await db.flush()
    return admin


async def _valid_user(db: AsyncSession, **kwargs: object) -> User:
    user = await make_user(db)
    user.email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    for key, value in kwargs.items():
        setattr(user, key, value)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_admin_users_filter_plan(db_session: AsyncSession) -> None:
    admin = await _make_admin(db_session)
    pro = await _valid_user(db_session, plan="pro")
    await _valid_user(db_session, plan="free")
    await db_session.commit()

    res = await list_users(
        plan="pro",
        role=None,
        q=None,
        page=1,
        page_size=20,
        _admin=admin,
        db=db_session,
    )
    ids = {u.id for u in res.items}
    assert pro.id in ids
    assert all(u.plan == "pro" for u in res.items)


@pytest.mark.asyncio
async def test_admin_users_search_by_numeric_id(db_session: AsyncSession) -> None:
    admin = await _make_admin(db_session)
    target = await _valid_user(db_session)
    await db_session.commit()

    res = await list_users(
        q=str(target.id),
        plan=None,
        role=None,
        page=1,
        page_size=5,
        _admin=admin,
        db=db_session,
    )
    assert any(u.id == target.id for u in res.items)


@pytest.mark.asyncio
async def test_admin_works_filter_q_and_user_id(db_session: AsyncSession) -> None:
    admin = await _make_admin(db_session)
    owner = await _valid_user(db_session)
    other = await _valid_user(db_session)
    tpl = Template(
        id=f"t-{uuid.uuid4().hex[:8]}",
        name="Test Template",
        style_prefix="test",
    )
    db_session.add(tpl)
    await db_session.flush()
    from app.models import Project

    project = Project(user_id=owner.id, template_id=tpl.id, source_text="x", title="p")
    db_session.add(project)
    await db_session.flush()
    db_session.add(
        Work(
            project_id=project.id,
            user_id=owner.id,
            title="UniqueWorkTitle",
            video_url="/v.mp4",
        )
    )
    other_project = Project(user_id=other.id, template_id=tpl.id, source_text="y", title="p2")
    db_session.add(other_project)
    await db_session.flush()
    db_session.add(
        Work(project_id=other_project.id, user_id=other.id, title="OtherWork", video_url="/v2.mp4")
    )
    await db_session.commit()

    res = await list_works(
        audit_status=None,
        visibility=None,
        q="UniqueWork",
        user_id=owner.id,
        page=1,
        page_size=20,
        _admin=admin,
        db=db_session,
    )
    assert len(res.items) == 1
    assert res.items[0].title == "UniqueWorkTitle"


@pytest.mark.asyncio
async def test_admin_usage_filter_project_ids(db_session: AsyncSession) -> None:
    admin = await _make_admin(db_session)
    user = await _valid_user(db_session)
    tpl = Template(id=f"u-{uuid.uuid4().hex[:8]}", name="u", style_prefix="s")
    db_session.add(tpl)
    await db_session.flush()
    from app.models import Project

    project = Project(user_id=user.id, template_id=tpl.id, source_text="u", title="u")
    db_session.add(project)
    await db_session.flush()
    ev1 = UsageEvent(
        user_id=user.id,
        project_id=project.id,
        domain="kepu",
        capability="llm",
        billing_key="llm_chat",
        model="m",
        charge_fen=10,
        cost_fen=5,
        provider="ark",
    )
    ev2 = UsageEvent(
        user_id=user.id,
        drama_project_id=202,
        domain="drama",
        capability="video",
        billing_key="seedance",
        model="m",
        charge_fen=20,
        cost_fen=8,
    )
    db_session.add_all([ev1, ev2])
    await db_session.commit()

    by_project = await list_usage_events(
        project_id=project.id,
        drama_project_id=None,
        user_id=None,
        task_run_id=None,
        domain=None,
        billing_key=None,
        capability=None,
        estimated=None,
        billing_basis=None,
        created_from=None,
        created_to=None,
        page=1,
        page_size=20,
        _admin=admin,
        db=db_session,
    )
    assert len(by_project.items) == 1
    assert by_project.items[0].project_id == project.id
    assert by_project.items[0].provider == "ark"

    by_drama = await list_usage_events(
        project_id=None,
        drama_project_id=202,
        user_id=None,
        task_run_id=None,
        domain=None,
        billing_key=None,
        capability=None,
        estimated=None,
        billing_basis=None,
        created_from=None,
        created_to=None,
        page=1,
        page_size=20,
        _admin=admin,
        db=db_session,
    )
    assert len(by_drama.items) == 1
    assert by_drama.items[0].drama_project_id == 202


@pytest.mark.asyncio
async def test_admin_templates_filter_active_and_category(db_session: AsyncSession) -> None:
    admin = await _make_admin(db_session)
    db_session.add_all(
        [
            Template(id="tpl-a", name="Alpha", style_prefix="a", category=["science"], is_active=True),
            Template(id="tpl-b", name="Beta", style_prefix="b", category=["drama"], is_active=False),
        ]
    )
    await db_session.commit()

    res = await list_templates(
        q="Alpha",
        is_active=True,
        category="science",
        page=1,
        page_size=20,
        _admin=admin,
        db=db_session,
    )
    assert len(res.items) == 1
    assert res.items[0].id == "tpl-a"


@pytest.mark.asyncio
async def test_admin_drama_projects_filter_status(db_session: AsyncSession) -> None:
    admin = await _make_admin(db_session)
    user = await _valid_user(db_session)
    p1 = DramaProject(user_id=user.id, title="DramaA", params={"assets_seed_status": "ready"})
    p2 = DramaProject(user_id=user.id, title="DramaB", params={"assets_seed_status": "pending"})
    db_session.add_all([p1, p2])
    await db_session.flush()
    db_session.add(DramaScript(project_id=p1.id, params={"summary_status": "done"}, name="s1"))
    db_session.add(DramaScript(project_id=p2.id, params={"summary_status": "draft"}, name="s2"))
    await db_session.commit()

    res = await list_drama_projects(
        page=1,
        page_size=20,
        q=None,
        user_id=None,
        summary_status="done",
        assets_seed_status="ready",
        _admin=admin,
        db=db_session,
    )
    assert len(res.items) == 1
    assert res.items[0].title == "DramaA"


@pytest.mark.asyncio
async def test_admin_drama_assets_filter_project_and_type(db_session: AsyncSession) -> None:
    from app.api.admin.drama_assets import list_drama_assets
    from app.models_drama import DramaAsset

    admin = await _make_admin(db_session)
    user = await _valid_user(db_session)
    p1 = DramaProject(user_id=user.id, title="Proj1")
    p2 = DramaProject(user_id=user.id, title="Proj2")
    db_session.add_all([p1, p2])
    await db_session.flush()
    db_session.add_all(
        [
            DramaAsset(project_id=p1.id, type="character", name="Hero", params={"generation": {"status": "done"}}),
            DramaAsset(project_id=p2.id, type="prop", name="Sword"),
        ]
    )
    await db_session.commit()

    by_project = await list_drama_assets(
        page=1,
        page_size=20,
        q=None,
        user_id=None,
        project_id=p1.id,
        asset_kind=None,
        asset_type=None,
        generation_status=None,
        _admin=admin,
        db=db_session,
    )
    assert len(by_project.items) == 1
    assert by_project.items[0].name == "Hero"

    by_type = await list_drama_assets(
        page=1,
        page_size=20,
        q=None,
        user_id=None,
        project_id=p2.id,
        asset_kind="prop",
        asset_type=None,
        generation_status=None,
        _admin=admin,
        db=db_session,
    )
    assert len(by_type.items) == 1
    assert by_type.items[0].name == "Sword"
    assert by_type.meta.total == 1


@pytest.mark.asyncio
async def test_admin_drama_assets_filter_generation_status(db_session: AsyncSession) -> None:
    from app.api.admin.drama_assets import list_drama_assets
    from app.models_drama import DramaAsset

    admin = await _make_admin(db_session)
    user = await _valid_user(db_session)
    project = DramaProject(user_id=user.id, title="GenFilter")
    db_session.add(project)
    await db_session.flush()
    db_session.add_all(
        [
            DramaAsset(
                project_id=project.id,
                type="character",
                name="DoneHero",
                params={"generation": {"status": "done"}},
            ),
            DramaAsset(
                project_id=project.id,
                type="prop",
                name="FailedProp",
                params={"generation": {"status": "failed"}},
            ),
        ]
    )
    await db_session.commit()

    done_only = await list_drama_assets(
        page=1,
        page_size=20,
        q=None,
        user_id=None,
        project_id=project.id,
        asset_kind=None,
        asset_type=None,
        generation_status="done",
        _admin=admin,
        db=db_session,
    )
    assert len(done_only.items) == 1
    assert done_only.items[0].name == "DoneHero"
    assert done_only.items[0].generation_status == "done"
