"""Stage-scoped director skills; selection never grants permission to run tools."""
from app.services.agent.compose import render_skill_block, skill_matches_task
from app.services.agent.store import list_injectable_skills, list_skills_by_ids

DEFAULT_DIRECTOR_SKILLS = {
    'script_write': 'printfilm-script-director',
    'asset_plan': 'short-drama-assets',
    'shot_plan': 'short-drama-storyboard',
    'video_prompt': 'short-drama-video-prompts',
    'edit_plan': 'printfilm-edit-director',
}
DIRECTOR_SKILL_TASKS = frozenset(DEFAULT_DIRECTOR_SKILLS)


def resolve_director_skill_task(story_step, requested_task):
    return {'assets': 'asset_plan', 'shots': 'shot_plan'}.get(story_step) or (requested_task if requested_task in DIRECTOR_SKILL_TASKS else 'shot_plan')


async def director_skill_ids(db, user_id, task, ids=None):
    if task not in DIRECTOR_SKILL_TASKS:
        raise ValueError('未知导演技能阶段')
    if ids is None:
        rows = await list_injectable_skills(db, user_id) if db is not None else []
        return [row.id for row in rows if row.is_builtin and row.slug == DEFAULT_DIRECTOR_SKILLS[task] and skill_matches_task(row, task)][:1]
    if not isinstance(ids, list) or len(ids) > 1 or any(type(identity) is not int or identity <= 0 for identity in ids):
        raise ValueError('每个阶段请选择一个导演技能，或不使用技能')
    if not ids:
        return []
    rows = await list_skills_by_ids(db, user_id, ids) if db is not None else []
    if len(rows) != len(ids) or any(not row.is_active or not skill_matches_task(row, task) for row in rows):
        raise ValueError('所选导演技能不可用或不适用于当前阶段，请重新选择')
    return ids


async def director_skill_block(db, user_id, task, ids=None, *, writing=False):
    selected = await director_skill_ids(db, user_id, task, ids)
    if writing and task == 'asset_plan':
        from app.printfilm_studio.image_prompt_policy import IMAGE_PROMPT_RULES
        rows = await list_skills_by_ids(db, user_id, selected) if selected else []
        # The built-in asset skill owns tool-based planning, not prose execution.
        # Preserve explicit custom skills, followed by the current output contract.
        custom = [row for row in rows if not (row.is_builtin and row.slug == 'short-drama-assets')]
        return render_skill_block(custom) + '\n' + IMAGE_PROMPT_RULES
    if not selected:
        return ''
    return render_skill_block(await list_skills_by_ids(db, user_id, selected))


async def load_director_skill_block(db, user_id, info):
    if info.get('studio_agent_mode') != 'director':
        return ''
    task = resolve_director_skill_task(None, info.get('studio_skill_task'))
    options = {'writing': True} if info.get('studio_enabled_tools') == [] else {}
    block = await director_skill_block(db, user_id, task, info.get('studio_skill_ids'), **options)
    if info.get('studio_required_tool') == 'plan_story_shots' and block:
        block += '\n当前处于分镜规划阶段：只创建写作要求与视频节点，正文留空。参考图完成后才在写作节点执行最终提示词规则。不可因为技能包含提示词规范而越过当前阶段。'
    return block
