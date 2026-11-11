import test from 'node:test'
import assert from 'node:assert/strict'
import { videoFileReferences, videoReferenceError } from '../src/features/printfilm-studio/canvas/generationReferences.ts'

test('video without references uses text mode rather than requiring a first frame', () => {
  assert.deepEqual(videoFileReferences([]), { mode: 'text_to_video', references: [] })
})

test('empty omni references require input while adding media or selecting text mode clears the error', () => {
  assert.equal(videoReferenceError([], 'omni_reference'), '请选择至少一份参考素材')
  assert.equal(videoReferenceError(['image'], 'omni_reference'), undefined)
  assert.equal(videoFileReferences(['image'], false, 'omni_reference').references[0].role, 'reference_image')
  assert.equal(videoReferenceError([], 'text_to_video'), undefined)
  assert.deepEqual(videoFileReferences([], false, 'text_to_video'), { mode: 'text_to_video', references: [] })
})

test('explicit modes preserve upload roles and reject incompatible inputs before submit', () => {
  assert.deepEqual(videoFileReferences(['image'], false, 'image_to_video'), { mode: 'first_last_frame', references: [{ file_index: 0, role: 'first_frame' }] })
  assert.equal(videoFileReferences(['image'], false, 'omni_reference').references[0].role, 'reference_image')
  assert.equal(videoFileReferences(['image', 'image'], false, 'first_last_frame').references[1].role, 'last_frame')
  assert.match(videoReferenceError(['video'], 'image_to_video'), /一张首帧/)
  assert.match(videoReferenceError(['image'], 'first_last_frame'), /两张图片/)
  assert.match(videoReferenceError(['image'], 'text_to_video'), /不使用媒体/)
  assert.match(videoReferenceError(['video'], 'omni_reference', { images: 2, videos: 0, audios: 0 }), /0 份视频/)
  assert.equal(videoReferenceError(['image', 'image'], 'first_last_frame', { images: 2, videos: 0, audios: 0 }), undefined)
})
test('one or two images map to exact upload indices for first and last frames', () => {
  assert.deepEqual(videoFileReferences(['image', 'image']), { mode: 'first_last_frame', references: [{ file_index: 0, role: 'first_frame' }, { file_index: 1, role: 'last_frame' }] })
})
test('mixed media and multiple images retain correct roles and indices', () => {
  assert.deepEqual(videoFileReferences(['image', 'video', 'audio']), { mode: 'omni_reference', references: [{ file_index: 0, role: 'reference_image' }, { file_index: 1, role: 'reference_video' }, { file_index: 2, role: 'reference_audio' }] })
  assert.equal(videoFileReferences(['image'], true).references[0].role, 'reference_image')
  assert.equal(videoFileReferences(['image', 'image', 'image']).mode, 'omni_reference')
})
