from types import SimpleNamespace

import pytest

from app.printfilm_studio.agent import director_skills
from app.printfilm_studio.agent.story_workflow import writing_requirements
from app.printfilm_studio.image_prompt_policy import image_writing_requirements
from app.printfilm_studio.writing_context import writing_context


@pytest.mark.parametrize('prefix', [
    '仅填写生成参考图提示词的写作要求，正文留空。',
    '只写参考图提示词的创作要求写作要求，正文留空。',
    '只填写参考图提示词写作要求，正文留空。',
    '写作节点正文留空，运行时再按素材和下游模型生成最终提示词。',
    '仅记录提示词写作要求，正文留空，最终提示词运行时生成。',
    '只写参考图提示词的创作要求写作要求，写作正文留空。',
])
def test_legacy_planning_directives_are_removed_without_losing_visual_facts(prefix):
    facts = '现代小饭馆后厨，灶台与取餐窗相邻。招牌留空，无字幕。'
    assert image_writing_requirements(prefix + facts) == facts
    wrapped = writing_requirements(prefix + facts)
    assert image_writing_requirements(wrapped) == facts
    assert '正文留空' not in wrapped
    assert image_writing_requirements(facts) == facts


def test_workflow_image_writer_executes_old_requirements_with_live_parameters():
    writer = {'id': 'w', 'type': 'text', 'data': {
        'writingPrompt': '仅填写生成参考图提示词的写作要求，正文留空。现代后厨，白天。',
        'outputNodeId': 'image',
    }}
    document = {'nodes': [writer, {'id': 'image', 'type': 'scene', 'data': {
        'label': '后厨', 'modelId': 'image-model', 'ratio': '2:3',
    }}], 'edges': []}
    prompt, outputs = writing_context(writer, document, {})
    assert '当前图片视觉要求：\n现代后厨，白天。' in prompt
    assert '仅填写生成参考图' not in prompt
    assert '不能再次要求另一个写作者生成提示词' in prompt
    assert outputs[0]['ratio'] == '2:3'


@pytest.mark.asyncio
async def test_asset_skill_is_planning_only_and_writing_uses_execution_rules(monkeypatch):
    row = SimpleNamespace(id=4, is_builtin=True, slug='short-drama-assets', name='资产导演',
                          body='必须调用 plan_story_assets，只填写作要求，正文留空。')
    async def ids(*_args):
        return [4]
    async def rows(*_args):
        return [row]
    monkeypatch.setattr(director_skills, 'director_skill_ids', ids)
    monkeypatch.setattr(director_skills, 'list_skills_by_ids', rows)
    info = {'studio_agent_mode': 'director', 'studio_skill_task': 'asset_plan', 'studio_skill_ids': [4]}
    planning = await director_skills.load_director_skill_block(None, 1, info)
    writing = await director_skills.load_director_skill_block(None, 1, {**info, 'studio_enabled_tools': []})
    background = await director_skills.director_skill_block(None, 1, 'asset_plan', [4], writing=True)
    assert '必须调用 plan_story_assets' in planning
    assert 'plan_story_assets' not in writing
    assert writing == background
    assert '输出可直接用于生图的中文提示词正文' in writing
    row.slug, row.is_builtin, row.body = 'custom', False, '黑白摄影与侧光'
    custom = await director_skills.director_skill_block(None, 1, 'asset_plan', [4], writing=True)
    assert '黑白摄影与侧光' in custom
    assert custom.endswith('不能再次要求另一个写作者生成提示词。')
