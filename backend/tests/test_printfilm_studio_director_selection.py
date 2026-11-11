from copy import deepcopy
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models_agent import AgentSkill
from app.printfilm_studio.agent.director_skills import director_skill_block, director_skill_ids
from app.printfilm_studio.agent.routes import StreamRequest
from app.services.agent.parse import parse_skill_markdown
from app.services.agent.store import BUILTIN_SKILLS_DIR


@pytest_asyncio.fixture
async def skills_db(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{(tmp_path / "director.db").as_posix()}')
    async with engine.begin() as conn:
        await conn.run_sync(AgentSkill.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add_all([
            AgentSkill(id=1, slug='short-drama-storyboard', name='分镜', body='分镜规则', tasks=['shot_plan'], is_builtin=True, is_active=True),
            AgentSkill(id=2, slug='other', name='外部用户技能', body='private', tasks=['shot_plan'], user_id=2, is_builtin=False, is_active=True),
            AgentSkill(id=3, slug='own', name='我的导演', body='my rule', tasks=['all'], user_id=1, is_builtin=False, is_active=True),
            AgentSkill(id=4, slug='disabled', name='已停用', body='disabled', tasks=['shot_plan'], is_builtin=True, is_active=False),
        ])
        await db.commit()
        yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_default_selection_is_one_builtin_not_all_matching_skills(skills_db):
    assert await director_skill_ids(skills_db, 1, 'shot_plan') == [1]
    assert await director_skill_ids(skills_db, 1, 'video_prompt') == []
    assert await director_skill_block(skills_db, 1, 'shot_plan', []) == ''
    assert 'my rule' in await director_skill_block(skills_db, 1, 'shot_plan', [3])


@pytest.mark.asyncio
@pytest.mark.parametrize('task,ids', [('shot_plan',[2]), ('shot_plan',[4]), ('video_prompt',[1]), ('shot_plan',[1,3]), ('shot_plan',[True]), ('shot_plan',[-1])])
async def test_invalid_foreign_disabled_or_mixed_stage_skill_is_rejected(skills_db, task, ids):
    with pytest.raises(ValueError):
        await director_skill_ids(skills_db, 1, task, ids)


def test_new_director_library_has_scoped_stages_and_display_names():
    for slug, tasks in {
        'printfilm-script-director':['script_write'],
        'printfilm-edit-director':['edit_plan'],
        'printfilm-product-director':['shot_plan','video_prompt'],
        'printfilm-documentary-director':['shot_plan','video_prompt'],
    }.items():
        parsed = parse_skill_markdown((BUILTIN_SKILLS_DIR / slug / 'SKILL.md').read_text(encoding='utf-8'))
        assert parsed['slug'] == slug and parsed['tasks'] == tasks
        assert '导演' in parsed['name'] and len(parsed['body']) < 12000


def test_request_accepts_per_stage_selection_and_rejects_multiple_or_boolean_ids():
    request=StreamRequest(prompt='规划', agent_mode='director', skill_task='edit_plan', director_skill_selection={'shot_plan':1,'video_prompt':None})
    assert request.director_skill_selection == {'shot_plan':1,'video_prompt':None}
    for values in [{'skill_ids':[1,2]}, {'skill_ids':[True]}, {'director_skill_selection':{'shot_plan':True}}, {'director_skill_selection':{'unknown':1}}]:
        with pytest.raises(ValidationError):
            StreamRequest(prompt='规划',**values)


@pytest.mark.asyncio
async def test_planned_writers_inherit_selected_skills_without_overwriting_existing_writers():
    from app.printfilm_studio.agent.story_workflow import apply_story_plan
    class Canvas:
        def __init__(self):
            self.document={'nodes':[{'id':'script','type':'script','position':{'x':0,'y':0},'data':{'text':'场1：城门 - 日\n甲等候。'}}],'edges':[]}
            self.db=SimpleNamespace(info={'studio_director_selection':{'asset_plan':[8],'video_prompt':[9]}})
        async def load(self):
            return deepcopy(self.document),1
        async def save(self,doc):
            self.document=doc
            return 2
    canvas=Canvas()
    await apply_story_plan('plan_story_assets',{'script_node_id':'script','assets':[{'kind':'scene','name':'城门','prompt':'古城门环境'}]},canvas)
    scene=next(n for n in canvas.document['nodes'] if n['type']=='scene')
    asset_writer=next(n for n in canvas.document['nodes'] if n['id']==scene['data']['promptNodeId'])
    assert asset_writer['data']['writingDirectorSkillIds']==[8]
    payload={'script_node_id':'script','shots':[{'index':1,'name':'等待','description':'固定镜头等待','prompt':'写抬头动作','reference_node_ids':[scene['id']]}]}
    await apply_story_plan('plan_story_shots',payload,canvas)
    writer=next(n for n in canvas.document['nodes'] if n['data'].get('storyKind')=='shot_prompt')
    assert writer['data']['writingDirectorSkillIds']==[9]
    writer['data']['writingDirectorSkillIds']=[]
    await apply_story_plan('plan_story_shots',payload,canvas)
    assert next(n for n in canvas.document['nodes'] if n['id']==writer['id'])['data']['writingDirectorSkillIds']==[]


@pytest.mark.asyncio
async def test_director_request_disables_paid_tools_by_default_and_validates_before_admission(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from fastapi import HTTPException
    from app.printfilm_studio.agent import routes, director_skills
    monkeypatch.setattr(routes, 'ensure_enabled', lambda: None)
    monkeypatch.setattr(routes, '_session', AsyncMock(return_value=SimpleNamespace(id='session',project_id=7)))
    monkeypatch.setattr(routes, 'get_project', AsyncMock(return_value=SimpleNamespace(id=7,team_id=None)))
    monkeypatch.setattr(routes.runs, 'latest_run', AsyncMock(return_value=None))
    reserve=AsyncMock(return_value=(SimpleNamespace(id='run'),True))
    monkeypatch.setattr(routes.runs, 'reserve_run', reserve)
    monkeypatch.setattr(routes.runs, 'launch_run', Mock())
    monkeypatch.setattr(routes, '_stream_response', lambda _session,_run,_user,info:info)
    monkeypatch.setattr(director_skills, 'director_skill_ids', AsyncMock(return_value=[]))
    result=await routes.stream_session('session',StreamRequest(prompt='写剧本',agent_mode='director'),SimpleNamespace(info={}),SimpleNamespace(id=1),None,None,None)
    assert 'read_canvas' in result['studio_enabled_tools']
    assert not {'create_image_task','create_video_task','create_audio_task'}.intersection(result['studio_enabled_tools'])
    reserve.reset_mock()
    monkeypatch.setattr(director_skills, 'director_skill_ids', AsyncMock(side_effect=ValueError('技能不可用')))
    with pytest.raises(HTTPException) as error:
        await routes.stream_session('session',StreamRequest(prompt='规划',agent_mode='director',skill_ids=[999]),SimpleNamespace(info={}),SimpleNamespace(id=1),None,None,None)
    assert error.value.status_code==422
    reserve.assert_not_awaited()
