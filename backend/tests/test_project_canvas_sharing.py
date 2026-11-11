"""Project teams and actor billing, using only the isolated rollback test DB."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import UsageEvent, WalletLedger
from app.models_drama import DramaProject
from app.models_tasks import TaskRun
from app.printfilm_studio import sharing
from app.printfilm_studio.canvas.service import get_project, save
from app.services.billing.settlement import freeze_for_task, settle_task
from app.services.billing.text_tasks import admit_text_task, finish_text_task
from app.schemas_tasks import TaskCreateRequest
from app.services.tasks.service import create_task, _validate_task_scope
from conftest import make_user


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(sharing, 'ensure_enabled', lambda: None)


async def seed(db, *, member_balance=1000):
    owner = await make_user(db, balance_fen=5000)
    member = await make_user(db, balance_fen=member_balance)
    other = await make_user(db, balance_fen=1000)
    project = DramaProject(user_id=owner.id, title='项目团队', params={'workflow': 'canvas'})
    isolated = DramaProject(user_id=owner.id, title='另一个项目', params={'workflow': 'canvas'})
    db.add_all([project, isolated])
    await db.flush()
    return owner, member, other, project, isolated


async def join(db, owner, member, project):
    invitation = await sharing.create_invitation(project.id, sharing.InviteBody(), db, owner)
    await sharing.accept_invitation(sharing.AcceptBody(token=invitation['token']), db, member)
    return invitation


@pytest.mark.asyncio
async def test_project_invite_join_is_idempotent_and_does_not_grant_other_access(db_session):
    db = db_session
    owner, member, other, project, isolated = await seed(db)
    with pytest.raises(HTTPException):
        await get_project(db, project.id, member)
    invite = await join(db, owner, member, project)
    await sharing.accept_invitation(sharing.AcceptBody(token=invite['token']), db, member)
    assert await db.scalar(select(func.count()).select_from(sharing.CanvasMember).where(sharing.CanvasMember.project_id == project.id)) == 1
    assert (await get_project(db, project.id, member)).id == project.id
    await save(db, project, member, {'nodes': [], 'edges': []}, 1)
    for forbidden in (other,):
        with pytest.raises(HTTPException):
            await get_project(db, project.id, forbidden)
    with pytest.raises(HTTPException):
        await get_project(db, isolated.id, member)
    from app.services.drama.access import require_drama_project_access
    with pytest.raises(HTTPException):
        await require_drama_project_access(db, project, member.id)
    assert (await sharing.shared_canvases(db, member))['items'] == [{'id': project.id, 'title': project.title}]
    snapshot = await sharing.sharing(project.id, db, member)
    assert not snapshot['is_owner'] and snapshot['invitations'] == []
    assert 'token' not in str(await sharing.sharing(project.id, db, owner))
    stored = await db.get(sharing.CanvasInvitation, invite['id'])
    assert stored.token_hash != invite['token'] and len(stored.token_hash) == 64


@pytest.mark.asyncio
async def test_only_owner_can_manage_project_members_and_links(db_session):
    db = db_session
    owner, member, other, project, isolated = await seed(db)
    invite = await join(db, owner, member, project)
    for action in (
        lambda: sharing.create_invitation(project.id, sharing.InviteBody(), db, member),
        lambda: sharing.revoke_invitation(project.id, invite['id'], db, member),
        lambda: sharing.remove_member(project.id, owner.id, db, member),
        lambda: sharing.revoke_invitation(isolated.id, invite['id'], db, owner),
    ):
        with pytest.raises(HTTPException):
            await action()
    with pytest.raises(HTTPException):
        await sharing.remove_member(project.id, owner.id, db, owner)


@pytest.mark.asyncio
async def test_revoke_expire_remove_and_pending_submission_denial(db_session):
    db = db_session
    owner, member, other, project, _ = await seed(db)
    invite = await join(db, owner, member, project)
    await sharing.revoke_invitation(project.id, invite['id'], db, owner)
    with pytest.raises(HTTPException) as invalid:
        await sharing.accept_invitation(sharing.AcceptBody(token=invite['token']), db, other)
    assert invalid.value.status_code == 410
    assert (await get_project(db, project.id, member)).id == project.id
    await sharing.remove_member(project.id, member.id, db, owner)
    with pytest.raises(HTTPException):
        await save(db, project, member, {'nodes': []}, 1)
    from app.services.tasks.team_scope import ensure_task_may_submit
    with pytest.raises(HTTPException):
        await ensure_task_may_submit(db, TaskRun(domain='studio', drama_project_id=project.id, requested_by=member.id))
    assert (await sharing.shared_canvases(db, member))['items'] == []
    expired = await sharing.create_invitation(project.id, sharing.InviteBody(), db, owner)
    row = await db.get(sharing.CanvasInvitation, expired['id'])
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    with pytest.raises(HTTPException) as invalid:
        await sharing.accept_invitation(sharing.AcceptBody(token=expired['token']), db, member)
    assert invalid.value.status_code == 410


@pytest.mark.asyncio
@pytest.mark.parametrize('task_type', ['tool_image', 'tool_video', 'tool_audio'])
@pytest.mark.parametrize('legacy_team', [False, True])
async def test_media_freeze_settle_charges_clicker_only(db_session, monkeypatch, task_type, legacy_team):
    db = db_session
    owner, member, _, project, _ = await seed(db)
    if legacy_team:
        from app.models_teams import Team
        team = Team(name='旧团队项目', owner_user_id=owner.id)
        db.add(team)
        await db.flush()
        project.team_id = team.id
        await db.flush()
    await join(db, owner, member, project)
    monkeypatch.setattr('app.services.media_models.planning.prepare_task_media', AsyncMock())
    monkeypatch.setattr('app.services.billing.settlement.estimate_task_fen', AsyncMock(return_value=100))
    task = await create_task(db, member, TaskCreateRequest(domain='studio', task_type=task_type, drama_project_id=project.id, payload={}), commit=False)
    assert task.requested_by == member.id and task.billing_payer_user_id == member.id and task.team_id is None
    await freeze_for_task(db, task)
    assert member.balance_fen == 900 and member.frozen_fen == 100
    assert owner.balance_fen == 5000 and owner.frozen_fen == 0
    db.add(UsageEvent(user_id=member.id, billing_payer_user_id=member.id, task_run_id=task.id, domain='studio', billing_key='seedream', charge_fen=60, cost_fen=30, settled=False))
    task.status = 'succeeded'
    await db.flush()
    await settle_task(db, task.id)
    await settle_task(db, task.id)
    assert member.balance_fen == 940 and member.frozen_fen == 0
    assert owner.balance_fen == 5000
    assert set((await db.scalars(select(WalletLedger.user_id).where(WalletLedger.ref_id == str(task.id), WalletLedger.ref_type == 'task_run'))).all()) == {member.id}


@pytest.mark.asyncio
@pytest.mark.parametrize('succeeded', [True, False])
async def test_text_task_charges_actor_and_refunds_failure(db_session, monkeypatch, succeeded):
    db = db_session
    owner, member, _, project, _ = await seed(db)
    await join(db, owner, member, project)
    monkeypatch.setattr('app.services.billing.settlement.estimate_task_fen', AsyncMock(return_value=5))
    key = f'project-billing-{project.id}'
    task = await admit_text_task(db, member, project, key, 'node_writing')
    await finish_text_task(db, key, succeeded)
    await finish_text_task(db, key, succeeded)
    assert task.billing_payer_user_id == member.id and task.team_id is None
    assert member.balance_fen == (995 if succeeded else 1000)
    assert member.frozen_fen == 0 and owner.balance_fen == 5000


@pytest.mark.asyncio
async def test_insufficient_actor_balance_cannot_use_owner_funds(db_session, monkeypatch):
    db = db_session
    owner, member, _, project, _ = await seed(db, member_balance=0)
    await join(db, owner, member, project)
    monkeypatch.setattr('app.services.media_models.planning.prepare_task_media', AsyncMock())
    monkeypatch.setattr('app.services.billing.settlement.estimate_task_fen', AsyncMock(return_value=100))
    with pytest.raises(ValueError, match='余额不足'):
        await create_task(db, member, TaskCreateRequest(domain='studio', task_type='tool_image', drama_project_id=project.id), commit=False)
    assert owner.balance_fen == 5000
    assert await db.scalar(select(func.count()).select_from(TaskRun).where(TaskRun.drama_project_id == project.id)) == 0


@pytest.mark.asyncio
async def test_forged_team_or_non_canvas_task_rejected(db_session):
    db = db_session
    owner, member, _, project, isolated = await seed(db)
    await join(db, owner, member, project)
    for body in (
        TaskCreateRequest(domain='studio', task_type='tool_image', drama_project_id=project.id, team_id=1),
        TaskCreateRequest(domain='studio', task_type='tool_image', drama_project_id=isolated.id),
        TaskCreateRequest(domain='studio', task_type='tool_image', drama_project_id=project.id, episode_id=1),
        TaskCreateRequest(domain='drama', task_type='script_summary', drama_project_id=project.id),
    ):
        with pytest.raises((ValueError, HTTPException)):
            await _validate_task_scope(db, member, body)
