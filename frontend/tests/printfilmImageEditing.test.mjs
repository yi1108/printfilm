import test from 'node:test'
import assert from 'node:assert/strict'
import { centeredCrop, dragCrop } from '../src/features/printfilm-studio/canvas/imageCropGeometry.ts'
import { imageNodeSize } from '../src/features/printfilm-studio/canvas/nodePresentation.ts'
import { mentionToken, plainPrompt, splitPrompt } from '../src/features/printfilm-studio/canvas/promptMentions.ts'

test('crop resizing and moving stay inside the source without distorting locked ratios', () => {
  const bounds = { width: 1200, height: 800 }, initial = centeredCrop(1200, 800, 1)
  assert.deepEqual(initial, { x: 200, y: 0, width: 800, height: 800 })
  for (const handle of ['nw', 'n', 'ne', 'w', 'e', 'sw', 's', 'se', 'move']) {
    for (const dx of [-2000, -200, 200, 2000]) for (const dy of [-2000, -200, 200, 2000]) {
      const rect = dragCrop(initial, handle, dx, dy, bounds, 1)
      assert.ok(rect.x >= 0 && rect.y >= 0 && rect.width > 0 && rect.height > 0)
      assert.ok(rect.x + rect.width <= 1200 && rect.y + rect.height <= 800)
      assert.ok(Math.abs(rect.width / rect.height - 1) < .001)
    }
  }
  assert.deepEqual(dragCrop(initial, 'move', -1000, 1000, bounds), { ...initial, x: 0 })
  assert.deepEqual(dragCrop(initial, 'nw', 100, 100, bounds), { x: 300, y: 100, width: 700, height: 700 })
})

test('image node height follows portrait, landscape, manual width and multi-image strip', () => {
  for (const [width, height] of [[1200, 800], [800, 1200], [2000, 300]]) {
    const node = imageNodeSize(width, height, 400)
    assert.ok(Math.abs((node.height - 46) / (node.width - 18) - height / width) < .002)
    assert.equal(imageNodeSize(width, height, 400, 2).height, node.height + 52)
  }
})

test('inline references retain distinct stable IDs and convert to readable generation text', () => {
  const a = { id: 'node-a', source: 'node', label: '首帧 [1] (特写)' }, b = { ...a, id: 'node-b' }
  const text = `镜头从 ${mentionToken(a)} 到 ${mentionToken(b)}。`
  assert.deepEqual(splitPrompt(text).filter((part) => part.reference).map((part) => part.reference.id), ['node-a', 'node-b'])
  assert.equal(plainPrompt(text), '镜头从 @首帧 [1] (特写) 到 @首帧 [1] (特写)。')
  assert.equal(plainPrompt('@[%XX](node:a)'), '@[%XX](node:a)')
})
