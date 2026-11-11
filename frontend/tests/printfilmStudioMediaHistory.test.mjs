import test from 'node:test'
import assert from 'node:assert/strict'
import { replaceNodeMedia, mediaHistory, mediaCandidates, adoptMediaCandidate } from '../src/features/printfilm-studio/canvas/mediaHistory.ts'

test('candidate gallery combines complete historical batches and adoption keeps order and original parameters',()=>{
  const original={mediaUrl:'a.png',mediaUrls:['a.png','b.png'],prompt:'第一版',modelId:'model-old',ratio:'2:3',mediaType:'image'}
  const next={...replaceNodeMedia(original,{mediaUrl:'c.png'}),prompt:'第二版',modelId:'model-new'}
  const choices=mediaCandidates(next)
  assert.deepEqual(choices.map(item=>item.mediaUrl),['a.png','b.png','c.png'])
  assert.equal(choices[0].prompt,'第一版')
  const adopted=adoptMediaCandidate(next,choices[1])
  assert.equal(adopted.mediaUrl,'b.png')
  assert.equal(adopted.prompt,'第二版','selection must not overwrite current generation instructions')
  assert.deepEqual(mediaCandidates(adopted).map(item=>item.mediaUrl),['a.png','b.png','c.png'])
  assert.equal(mediaCandidates(adopted)[1].modelId,'model-old','comparison displays the actual output parameters')
  const again=adoptMediaCandidate(adopted,mediaCandidates(adopted)[2])
  assert.deepEqual(mediaCandidates(again).map(item=>item.mediaUrl),['a.png','b.png','c.png'])
  assert.equal(mediaCandidates(again)[0].prompt,'第一版')
  assert.equal(original.mediaUrl,'a.png')
  let toggled=again
  for(let i=0;i<80;i++)toggled=adoptMediaCandidate(toggled,mediaCandidates(toggled)[i%3])
  assert.deepEqual(mediaCandidates(toggled).map(item=>item.mediaUrl),['a.png','b.png','c.png'])
  assert.ok(mediaHistory(toggled).length<=3,'navigation does not duplicate historical runs')
})

test('replacing media clears old task and gallery, and preserves a restorable snapshot', () => {
  const original = { mediaUrl: 'old.png', mediaUrls: ['old.png', 'variant.png'], assetId: 12, taskId: 'task-old', inpaint: { maskUrl: 'mask' }, prompt: 'original prompt', mediaType: 'image' }
  const replacement = replaceNodeMedia(original, { mediaUrl: 'new.png', assetId: 13 })
  assert.deepEqual(replacement.mediaUrls, ['new.png'])
  assert.equal(replacement.taskId, undefined)
  assert.equal(replacement.inpaint, undefined)
  assert.equal(replacement.prompt, original.prompt)
  assert.equal(mediaHistory(replacement)[0].assetId, 12)
  const restored = replaceNodeMedia(replacement, mediaHistory(replacement)[0])
  assert.deepEqual(restored.mediaUrls, original.mediaUrls)
  assert.equal(restored.assetId, 12)
  assert.equal(mediaHistory(restored).at(-1).mediaUrl, 'new.png')
  assert.equal(original.taskId, 'task-old')
})

test('history is bounded and identical media does not create another entry', () => {
  let data = { mediaUrl: '0.png' }
  for (let i = 1; i < 45; i++) data = replaceNodeMedia(data, { mediaUrl: `${i}.png` })
  assert.equal(mediaHistory(data).length, 30)
  assert.equal(mediaHistory(replaceNodeMedia(data, { mediaUrl: '44.png' })).length, 30)
})
