import test from 'node:test'
import assert from 'node:assert/strict'
import { connectedGenerationPrompt } from '../src/features/printfilm-studio/canvas/generationPrompt.ts'
import { bindUploadedImageMentions, mentionToken } from '../src/features/printfilm-studio/canvas/promptMentions.ts'

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
