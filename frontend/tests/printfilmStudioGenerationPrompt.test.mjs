import test from 'node:test'
import assert from 'node:assert/strict'
import { connectedGenerationPrompt } from '../src/features/printfilm-studio/canvas/generationPrompt.ts'
import { bindNamedPromptReferences, bindUploadedImageMentions, mentionToken } from '../src/features/printfilm-studio/canvas/promptMentions.ts'

test('pasted material names bind once and preserve ambiguous names and existing tokens', () => {
  const character = { source: 'node', id: 'role', label: '尧帝.png', identity: 'asset:42' }
  const library = { source: 'asset', id: '42', label: '尧帝.png', identity: 'asset:42' }
  const duplicate = [
    { source: 'node', id: 'scene-1', label: '祭台.png' },
    { source: 'node', id: 'scene-2', label: '祭台.png' },
  ]
  const token = mentionToken(character)
  const calls = []
  const original = '  @尧帝.png、尧帝、祭台.png、未知素材。  '
  const bind = value => bindNamedPromptReferences(value, [character, library, ...duplicate], item => {
    calls.push(item.id)
    return item
  })
  assert.equal(bind(original), `${original}\n参考素材：${token}`)
  assert.deepEqual(calls, ['role'])
  assert.equal(bind(original + token), original + token)
})

test('omni reference binds canvas and library image mentions in upload order by ID', () => {
  const uploadedImages = [{ nodeId: 'scene' }, { nodeId: 'character', assetId: '42' }]
  const scene = mentionToken({ source: 'node', id: 'scene', label: '同名' })
  const character = mentionToken({ source: 'asset', id: '42', label: '同名' })
  const removed = mentionToken({ source: 'node', id: 'removed', label: '已移除' })
  const video = mentionToken({ source: 'node', id: 'clip', label: '动作参考' })
  assert.equal(
    bindUploadedImageMentions(`${character}走进${scene}，参考${video}与${removed}，最后回到${scene}`, uploadedImages),
    '@图片2走进@图片1，参考@动作参考与@已移除，最后回到@图片1',
  )
})

test('a connected writing result supplies an otherwise empty image prompt', () => {
  const writing = { type: 'text', data: { label: '新文本', text: '原创动漫角色在舞蹈室跳舞' } }
  assert.equal(connectedGenerationPrompt(' ', [writing]), writing.data.text)
  assert.equal(connectedGenerationPrompt('改为全景', [writing]), '改为全景')
  assert.equal(connectedGenerationPrompt('', []), '')
})

test('video generation keeps long connected text and its ending', () => {
  const text = '镜'.repeat(14_990) + '保留最后的内容'
  const writing = { type: 'text', data: { text } }
  assert.equal(connectedGenerationPrompt('', [writing], true), text)
  assert.equal(connectedGenerationPrompt('', [writing]).length, 6000)
})

test('empty and media references cannot unlock generation; multiple text sources keep labels', () => {
  const refs = [
    { type: 'text', data: { text: '  ' } },
    { type: 'image', data: { text: '图片元数据' } },
  ]
  assert.equal(connectedGenerationPrompt('', refs), '')
  assert.equal(connectedGenerationPrompt('', [...refs,
    { type: 'text', data: { label: '人物', text: '舞者' } },
    { type: 'script', data: { label: '场景', text: '练习室' } },
  ]), '人物：舞者\n\n场景：练习室')
})
