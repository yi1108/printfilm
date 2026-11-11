import test from 'node:test'
import assert from 'node:assert/strict'
import { compositeMaskPixels, validateInpaintAspect, InpaintAspectMismatchError } from '../src/features/printfilm-studio/canvas/maskPixels.ts'

test('inpaint rejects a provider aspect mismatch instead of stretching the patch', () => {
  assert.throws(() => validateInpaintAspect(864, 496, 2048, 2048), InpaintAspectMismatchError)
  assert.throws(() => validateInpaintAspect(0, 496, 2048, 2048), InpaintAspectMismatchError)
  assert.doesNotThrow(() => validateInpaintAspect(864, 496, 1728, 992))
  assert.doesNotThrow(() => validateInpaintAspect(864, 496, 1792, 1024))
})
test('inpainting leaves every unselected channel byte-identical', () => {
  const src = new Uint8ClampedArray([12, 34, 56, 78, 10, 20, 30, 255])
  const generated = new Uint8ClampedArray([255, 255, 255, 255, 100, 110, 120, 255])
  assert.deepEqual([...compositeMaskPixels(src, generated, new Uint8ClampedArray([255, 0, 0, 0, 255, 0, 0, 255]))], [12, 34, 56, 78, 100, 110, 120, 255])
})
test('mask boundaries blend smoothly and invalid sizes fail', () => {
  const source = new Uint8ClampedArray([0, 0, 0, 255])
  const result = compositeMaskPixels(source, new Uint8ClampedArray([255, 255, 255, 255]), new Uint8ClampedArray([0, 0, 0, 128]))
  assert.deepEqual([...result], [128, 128, 128, 255])
  assert.throws(() => compositeMaskPixels(source, new Uint8ClampedArray(0), source))
})
