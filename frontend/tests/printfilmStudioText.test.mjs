import test from 'node:test'
import assert from 'node:assert/strict'
import { formatStudioText } from '../src/features/printfilm-studio/canvas/textFormatting.ts'

test('inline formatting wraps only the selection, preserves Unicode and toggles off', () => {
  const original = '开场：人物走入房间。'
  const formatted = formatStudioText(original, 3, 5, 'bold')
  assert.equal(formatted.text, '开场：**人物**走入房间。')
  assert.equal(formatted.text.slice(formatted.start, formatted.end), '人物')
  assert.deepEqual(formatStudioText(formatted.text, formatted.start, formatted.end, 'bold'), { text: original, start: 3, end: 5 })
  assert.deepEqual(formatStudioText('', 0, 0, 'code'), { text: '`代码`', start: 1, end: 3 })
})

test('list formatting operates on complete selected lines without touching following content', () => {
  const original = '镜头一\n镜头二\n尾声'
  const result = formatStudioText(original, 1, 8, 'ordered')
  assert.equal(result.text, '1. 镜头一\n2. 镜头二\n尾声')
  assert.equal(formatStudioText(result.text, result.start, result.end, 'ordered').text, original)
  assert.equal(formatStudioText(original, 4, 5, 'heading').text, '镜头一\n## 镜头二\n尾声')
  assert.equal(formatStudioText('开头', 0, 2, 'quote').text, '> 开头')
})
