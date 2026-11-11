"""Project directory, retirement and migration regressions (isolated test DB)."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import select, func
from app.models_drama import DramaProject, DramaAsset
from app.models_teams import Team, TeamMember
from app.models_tasks import TaskRun
from app.printfilm_studio.sharing import CanvasMember, require_canvas_access
from app.printfilm_studio.project_team_migration import migrate_project_teams
from app.api.drama.projects import list_projects
from app.api.retired_teams import retired
from app.services.drama.access import require_drama_project_access
from app.services.drama.media_library import library_page
from app.services.teams.write_access import workspace_team
from app.schemas_tasks import TaskCreateRequest
from app.services.tasks.service import _validate_task_scope
from conftest import make_user

async def listing(db,user,relation='all',**kw):
    return await list_projects(db=db,user=user,scope_team_id=None,workflow='canvas',relation=relation,status=None,q=kw.get('q'),page=kw.get('page',1),page_size=kw.get('size',8))

@pytest.mark.asyncio
async def test_directory_unifies_owned_joined_and_revocation(db_session):
    db=db_session
    owner=await make_user(db); member=await make_user(db); stranger=await make_user(db)
    own=DramaProject(user_id=member.id,title='自己创建',params={'workflow':'canvas'})
    joined=DramaProject(user_id=owner.id,title='合作项目',params={'workflow':'canvas'})
    hidden=DramaProject(user_id=owner.id,title='不可见',params={'workflow':'canvas'})
    db.add_all([own,joined,hidden]);await db.flush()
    grant=CanvasMember(project_id=joined.id,user_id=member.id);db.add(grant);await db.flush()
    all_rows=await listing(db,member)
    assert {x.id for x in all_rows.items}=={own.id,joined.id}
    assert {x.id:x.is_owner for x in all_rows.items}=={own.id:True,joined.id:False}
    assert [x.id for x in (await listing(db,member,'owned')).items]==[own.id]
    assert [x.id for x in (await listing(db,member,'joined')).items]==[joined.id]
    page=await listing(db,member,q='合作',page=99,size=1)
    assert page.meta.total==1 and page.meta.page==1 and page.items[0].id==joined.id
    assert (await listing(db,stranger)).meta.total==0
    with pytest.raises(HTTPException): await require_drama_project_access(db,joined,member.id)
    await db.delete(grant);await db.flush()
    assert (await listing(db,member,'joined')).meta.total==0
    with pytest.raises(HTTPException): await require_canvas_access(db,joined,member.id)

@pytest.mark.asyncio
async def test_retired_scope_cannot_create_charge_or_grant_access(db_session):
    db=db_session;user=await make_user(db)
    with pytest.raises(HTTPException) as exc: await retired('1/members')
    assert exc.value.status_code==410
    request=Request({'type':'http','headers':[(b'x-team-id',b'1')],'query_string':b''})
    with pytest.raises(HTTPException) as exc: await workspace_team(request,db,user)
    assert exc.value.status_code==410
    body=TaskCreateRequest(domain='tools',task_type='tool_image',team_id=1,payload={})
    with pytest.raises(ValueError,match='独立团队已停用'): await _validate_task_scope(db,user,body)

@pytest.mark.asyncio
async def test_migration_is_idempotent_preserves_history_and_narrows_grants(db_session):
    db=db_session;owner=await make_user(db);member=await make_user(db)
    team=Team(name='legacy',owner_user_id=owner.id);db.add(team);await db.flush()
    db.add(TeamMember(team_id=team.id,user_id=member.id,role='member',active=True))
    canvas=DramaProject(user_id=owner.id,team_id=team.id,title='旧画布',params={'workflow':'canvas'})
    drama=DramaProject(user_id=owner.id,team_id=team.id,title='旧漫剧',params={'workflow':'script'})
    db.add_all([canvas,drama]);await db.flush()
    history=TaskRun(requested_by=member.id,team_id=team.id,drama_project_id=canvas.id,task_type='asset_image',status='succeeded',billing_payer_user_id=owner.id,billing_status='settled',billing_charged_fen=25)
    db.add(history);await db.flush()
    assert await migrate_project_teams(db)=={'projects':2,'project_members':1}
    assert history.team_id==team.id and history.billing_payer_user_id==owner.id and history.billing_charged_fen==25
    assert canvas.team_id is None and drama.team_id is None
    assert canvas.params['legacy_team_id']==team.id
    assert await db.get(Team,team.id) is team
    await require_canvas_access(db,canvas,member.id)
    with pytest.raises(HTTPException): await require_drama_project_access(db,drama,member.id)
    assert await migrate_project_teams(db)=={'projects':0,'project_members':0}
    body=TaskCreateRequest(domain='drama',task_type='asset_image',drama_project_id=canvas.id,payload={})
    await _validate_task_scope(db,owner,body)
    assert body.team_id is None

@pytest.mark.asyncio
async def test_shared_assets_are_paged_eight_and_revoked(db_session):
    db=db_session;owner=await make_user(db);member=await make_user(db)
    project=DramaProject(user_id=owner.id,title='共享资产',params={'workflow':'canvas'})
    db.add(project);await db.flush()
    grant=CanvasMember(project_id=project.id,user_id=member.id);db.add(grant)
    for i in range(9): db.add(DramaAsset(project_id=project.id,type='image',name=f'图片{i}',url=f'/assets/example-{i}.png'))
    await db.flush()
    result=await library_page(db,member.id,None,project_id=project.id,page_size=8)
    assert len(result.items)==8 and result.meta.total==9
    result=await library_page(db,member.id,None,project_id=project.id,page_size=8,page=2)
    assert len(result.items)==1
    await db.delete(grant);await db.flush()
    with pytest.raises(HTTPException): await library_page(db,member.id,None,project_id=project.id,page_size=8)
