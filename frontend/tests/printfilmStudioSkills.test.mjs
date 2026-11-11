import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultStudioSkillSelection, emptyStudioSkillSelection, studioSkillOptions, studioSkillsForTask, restoreStudioSkillSelection, inferredStudioSkillTask } from '../src/features/printfilm-studio/agent/skills.ts'

const skills = [
  { id: 1, slug: 'short-drama-assets', name: '资产', tasks: ['asset_plan'], is_active: true },
  { id: 2, slug: 'short-drama-storyboard', name: '分镜', tasks: ['shot_plan'], is_active: true },
  { id: 3, slug: 'short-drama-video-prompts', name: '视频提示词', tasks: ['video_prompt'], is_active: true },
  { id: 4, slug: 'seedance-2-5-video-director', name: 'Seedance', tasks: ['video_prompt'], is_active: true },
  { id: 5, slug: 'cinedance-seedance', name: '旧导演', tasks: ['shot_plan', 'video_prompt'], is_active: true },
  { id: 6, slug: 'custom', name: '自定义', tasks: ['all'], is_active: true },
  { id: 7, slug: 'disabled', name: '停用', tasks: ['shot_plan'], is_active: false },
]

test('director defaults select the three general skills without stacking Seedance specialists', () => {
  assert.deepEqual(defaultStudioSkillSelection(skills), {script_write:null, asset_plan: 1, shot_plan: 2, video_prompt: 3, edit_plan:null })
})

test('missing preferred skills stay disabled instead of injecting every matching skill', () => {
  assert.deepEqual(defaultStudioSkillSelection([skills[4]]), emptyStudioSkillSelection())
})

test('skill choices respect stage and active state while allowing custom all-task skills', () => {
  assert.deepEqual(studioSkillsForTask(skills, 'shot_plan').map((skill) => skill.id), [2, 5, 6])
  assert.deepEqual(studioSkillsForTask(skills, 'video_prompt').map((skill) => skill.id), [3, 4, 5, 6])
})

test('one request carries one stage skill and assistant mode never injects director skills', () => {
  const selection = defaultStudioSkillSelection(skills)
  assert.deepEqual(studioSkillOptions(selection, 'video_prompt', 'director'), { agent_mode: 'director', skill_task: 'video_prompt', skill_ids: [3] })
  assert.deepEqual(studioSkillOptions({ ...selection, video_prompt: 4 }, 'video_prompt', 'director').skill_ids, [4])
  assert.deepEqual(studioSkillOptions(selection, 'shot_plan', 'assistant'), { agent_mode: 'assistant', skill_task: 'shot_plan', skill_ids: [] })
})


test('saved choices validate permissions/stage and preserve explicit none',()=>{
  const result=restoreStudioSkillSelection(skills,{shot_plan:7,video_prompt:4,asset_plan:null,script_write:2})
  assert.deepEqual(result,{script_write:null,asset_plan:null,shot_plan:2,video_prompt:4,edit_plan:null})
  assert.equal(inferredStudioSkillTask('生成三国演义的剧本','shot_plan'),'script_write')
  assert.equal(inferredStudioSkillTask('按场拆分镜头并写提示词要求','script_write'),'shot_plan')
})
