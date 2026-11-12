import test from 'node:test'
import assert from 'node:assert/strict'
import { connectedGenerationPrompt } from '../src/features/printfilm-studio/canvas/generationPrompt.ts'

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
