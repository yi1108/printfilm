import test from 'node:test'
import assert from 'node:assert/strict'
import { videoPromptAudio } from '../src/features/printfilm-studio/canvas/videoPromptAudio.ts'

test('only actual speech enters audio allowlist, never adjacent acting prose',()=>{
  const prompt='传令兵跪在沙地上，用尽最后的力气嘶哑喊出：“关将军急报——襄樊被围……”声音在风沙中撕裂。喊话时身体微微前倾。'
  const result=videoPromptAudio(prompt,'seedance-2.5')
  const [picture,sound]=result.split('\n\n声音执行区：\n')
  assert.match(picture,/声音在风沙中撕裂/)
  assert.ok(!sound.includes('声音在风沙中撕裂'))
  assert.ok(!picture.includes('关将军急报'))
  assert.match(sound,/台词1：\{“关将军急报——襄樊被围……”\}/)
  assert.equal((result.match(/关将军急报/g)||[]).length,1)
  assert.match(sound,/环境声只还原声音，不朗读其名称/)
})

test('structured dialogue preserves speaker mapping and ignores quoted directions',()=>{
  const prompt='画面：门牌写着“军营”。\n运镜：采用“固定镜头”。\n台词：甲：“走！”（语气“急促”）\n台词：乙：“等等。”\n环境声：风声。'
  const result=videoPromptAudio(prompt,'seedance-2.0')
  const [picture,sound]=result.split('\n\n声音执行区：\n')
  assert.match(picture,/台词：甲：〔发声台词1/)
  assert.match(picture,/台词：乙：〔发声台词2/)
  assert.match(sound,/台词1：“走！”\n台词2：“等等。”/)
  for(const text of ['固定镜头','军营','急促']) assert.ok(!sound.includes(text))
})

test('a shot without dialogue preserves ambient sound while explicitly forbidding narration',()=>{
  const result=videoPromptAudio('画面：人物举简。\n环境声：风声、急促呼吸。\n台词：无','seedance-2.5')
  assert.match(result,/环境声：风声、急促呼吸/)
  assert.match(result,/本镜没有指定台词/)
  assert.ok(!result.includes('台词1'))
})
