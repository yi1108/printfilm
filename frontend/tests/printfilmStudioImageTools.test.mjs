import test from 'node:test'
import assert from 'node:assert/strict'
import { panoramaUv, imageToolPrompt } from '../src/features/printfilm-studio/canvas/imageToolParameters.ts'
import { validateStudioConnection } from '../src/features/printfilm-studio/canvas/nodeOperations.ts'

test('panorama camera wraps horizontally without seams and looks up/down correctly', () => {
  assert.deepEqual(panoramaUv(0, 0, 16 / 9, 0, 0, 70), [.5, .5])
  assert.deepEqual(panoramaUv(0, 0, 16 / 9, 360, 0, 70), [.5, .5])
  assert.equal(panoramaUv(0, 0, 1, 180, 0, 70)[0], 0)
  assert.ok(panoramaUv(0, 0, 1, 0, 45, 70)[1] < .5)
  assert.ok(panoramaUv(0, 0, 1, 0, -45, 70)[1] > .5)
  assert.notEqual(panoramaUv(0, 0, 1, 0, 30, 70, true)[1], panoramaUv(0, 0, 1, 0, 30, 70)[1])
})

test('lighting and angle requests preserve configured parameters', () => {
  const settings = { yaw: -90, pitch: 35, brightness: 65, color: '#ffad69', distance: 7, lens: 24, panorama: 'sphere' }
  const lighting = imageToolPrompt('lighting', settings), angle = imageToolPrompt('angle', settings)
  assert.match(lighting, /-90°/); assert.match(lighting, /35°/); assert.match(lighting, /65%/); assert.match(lighting, /#ffad69/)
  assert.match(angle, /7 米/); assert.match(angle, /24mm/)
  assert.match(imageToolPrompt('panorama', settings), /2:1/)
})

test('frame analysis accepts one video input and exposes no output', () => {
  const nodes = ['video', 'image', 'frameAnalysis'].map((type) => ({ id: type, type, position: { x: 0, y: 0 }, data: {} }))
  assert.equal(validateStudioConnection({ source: 'video', target: 'frameAnalysis' }, nodes, []), undefined)
  assert.match(validateStudioConnection({ source: 'image', target: 'frameAnalysis' }, nodes, []), /只能接入视频/)
  assert.match(validateStudioConnection({ source: 'frameAnalysis', target: 'video' }, nodes, []), /不提供输出/)
})
