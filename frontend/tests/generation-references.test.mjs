import assert from 'node:assert/strict'
import { videoReferenceError } from '../src/features/printfilm-studio/canvas/generationReferences.ts'
import test from 'node:test'
import { generationReferenceFileKind, generationReferenceLimits, serializeGenerationReferences, validateGenerationReferences } from '../src/lib/generationReferences.ts'

const limits = { images: 9, videos: 3, audios: 3 }

/** 构造资产引用，测试关注提交契约而非 UI 内部状态。 */
function asset(id, kind, role = `reference_${kind}`) {
  return { id: String(id), assetId: id, role, kind, name: `asset ${id}`, url: `/static/${id}` }
}

test('首尾帧要求首帧，尾帧可选，每个帧位只能有一张图片', () => {
  const first = asset(1, 'image', 'first_frame')
  const last = asset(2, 'image', 'last_frame')
  assert.match(validateGenerationReferences('first_last_frame', [], limits), /首帧/)
  assert.match(validateGenerationReferences('first_last_frame', [last], limits), /首帧/)
  assert.equal(validateGenerationReferences('first_last_frame', [first], limits), null)
  assert.equal(validateGenerationReferences('first_last_frame', [first, last], limits), null)
  assert.match(validateGenerationReferences('first_last_frame', [first, asset(3, 'image', 'first_frame')], limits), /分别只能/)
  assert.match(validateGenerationReferences('first_last_frame', [first, asset(3, 'video')], limits), /仅支持/)
})

test('切换模型后保留引用，但拒绝模型不支持或超出数量的引用', () => {
  const first = asset(1, 'image', 'first_frame')
  const last = asset(2, 'image', 'last_frame')
  assert.match(validateGenerationReferences('first_last_frame', [first], { ...limits, images: 0 }), /不支持/)
  assert.match(validateGenerationReferences('first_last_frame', [first, last], { ...limits, images: 1 }), /最多支持 1/)
  assert.match(validateGenerationReferences('omni_reference', [asset(1, 'video')], { ...limits, videos: 0 }), /不支持参考视频/)
  assert.match(validateGenerationReferences('omni_reference', [asset(1, 'audio'), asset(2, 'audio')], { ...limits, audios: 1 }), /最多支持 1/)
})

test('全能参考支持混合媒体且同时限制分类数量和总数量', () => {
  assert.match(validateGenerationReferences('omni_reference', [], limits), /至少一份/)
  assert.equal(validateGenerationReferences('omni_reference', [asset(1, 'image'), asset(2, 'video'), asset(3, 'audio')], limits), null)
  assert.match(validateGenerationReferences('omni_reference', [asset(1, 'image', 'first_frame')], limits), /全能参考/)
  const images = Array.from({ length: 9 }, (_, index) => asset(index + 1, 'image'))
  const videos = Array.from({ length: 3 }, (_, index) => asset(index + 20, 'video'))
  assert.equal(validateGenerationReferences('omni_reference', [...images, ...videos], limits), null)
  assert.match(validateGenerationReferences('omni_reference', [...images, ...videos, asset(30, 'audio')], limits), /最多支持 12/)
  assert.match(validateGenerationReferences('omni_reference', [...images, asset(31, 'image')], limits), /最多支持 9/)
})

test('文件和资产混用时 multipart 索引只统计文件，序列化不提交资产地址', () => {
  const firstFile = new File(['image'], 'first.png', { type: 'image/png' })
  const audioFile = new File(['audio'], 'voice.mp3', { type: 'audio/mpeg' })
  const value = [
    { id: 'file-1', kind: 'image', role: 'reference_image', file: firstFile, name: firstFile.name, url: '' },
    asset(42, 'video'),
    { id: 'file-2', kind: 'audio', role: 'reference_audio', file: audioFile, name: audioFile.name, url: '' },
  ]
  const serialized = serializeGenerationReferences(value)
  assert.deepEqual(serialized.files, [firstFile, audioFile])
  assert.deepEqual(serialized.references, [
    { role: 'reference_image', file_index: 0 },
    { role: 'reference_video', asset_id: 42 },
    { role: 'reference_audio', file_index: 1 },
  ])
  assert.equal(validateGenerationReferences('omni_reference', value, limits), null)
})

test('文生视频不携带引用，失效资料和过大文件不可提交', () => {
  assert.equal(validateGenerationReferences('text_to_video', [], limits), null)
  assert.match(validateGenerationReferences('text_to_video', [asset(1, 'image')], limits), /无需参考/)
  assert.match(validateGenerationReferences('omni_reference', [{ ...asset(1, 'image'), assetId: undefined }], limits), /失效/)
  const file = { size: 40 * 1024 * 1024 + 1 }
  assert.match(validateGenerationReferences('omni_reference', [{ ...asset(1, 'image'), assetId: undefined, file }], limits), /40MB/)
})

test('Seedance 2.5 使用目录配置的 30 图、10 视频、10 音频', () => {
  const limits = { images: 30, videos: 10, audios: 10, total: 50 }
  const references = ['image', 'video', 'audio'].flatMap((kind, index) =>
    Array.from({ length: kind === 'image' ? 30 : 10 }, (_, offset) => asset(index * 100 + offset + 1, kind)),
  )
  assert.deepEqual(generationReferenceLimits(limits), limits)
  assert.equal(validateGenerationReferences('omni_reference', references, limits), null)
  assert.match(validateGenerationReferences('omni_reference', [...references, asset(900, 'image')], limits), /30/)
  const kinds = references.map(reference => reference.kind)
  assert.equal(videoReferenceError(kinds, 'omni_reference', limits, limits.total), undefined)
  assert.match(videoReferenceError([...kinds, 'video'], 'omni_reference', limits, limits.total), /50/)
})

test('文件类型与服务端格式白名单一致', () => {
  assert.equal(generationReferenceFileKind({ type: 'audio/webm', name: 'recording.webm' }), null)
  assert.equal(generationReferenceFileKind({ type: '', name: 'clip.MOV' }), 'video')
  assert.equal(generationReferenceFileKind({ type: '', name: 'photo.jpeg' }), 'image')
  assert.equal(generationReferenceFileKind({ type: 'application/pdf', name: 'brief.pdf' }), null)
  assert.equal(generationReferenceFileKind({ type: 'image/svg+xml', name: 'vector.svg' }), null)
  assert.equal(generationReferenceFileKind({ type: 'image/gif', name: 'animated.gif' }), null)
  assert.equal(generationReferenceFileKind({ type: 'image/png', name: 'clip.mp4' }), null)
  assert.equal(generationReferenceFileKind({ type: 'audio/flac', name: 'voice.flac' }), 'audio')
  assert.match(validateGenerationReferences('omni_reference', [{ ...asset(1, 'image'), assetId: undefined, file: new File([], 'empty.png', { type: 'image/png' }) }], limits), /不能为空/)
})
