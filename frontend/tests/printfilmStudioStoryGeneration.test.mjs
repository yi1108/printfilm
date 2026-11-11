import test from 'node:test'
import assert from 'node:assert/strict'
import { storyVideoInputs } from '../src/features/printfilm-studio/canvas/storyGenerationInputs.ts'

test('stable image mentions resolve to actual upload order instead of canvas edge order',()=>{
  const {nodes,edges,video}=graph()
  nodes[0].data.text='@[刘备](node:role)在@[桃园](node:scene)抬头'
  video.data.referenceNodeIds=['scene','role']
  const result=storyVideoInputs(video,nodes,edges)
  assert.ok(result.providerPrompt.startsWith('@图片2在@图片1抬头'))
  assert.match(result.providerPrompt,/@图片1：桃园，用于场景空间与光线/)
  assert.match(result.providerPrompt,/@图片2：刘备，仅用于人物身份/)
  assert.ok(!result.providerPrompt.includes('(node:'))
  assert.deepEqual(result.references.map(ref=>ref.url),['/garden.png','/chosen.png'])
})

function graph() {
  const nodes = [
    { id: 'prompt', type: 'text', data: { sourceScriptId: 'script', text: '最新文本中的分镜提示词' } },
    { id: 'role', type: 'character', data: { sourceScriptId: 'script', storyKind: 'character', label: '刘备', mediaType: 'image', mediaUrls: ['/old.png', '/chosen.png'], mediaIndex: 1 } },
    { id: 'scene', type: 'scene', data: { sourceScriptId: 'script', storyKind: 'scene', label: '桃园', mediaType: 'image', mediaUrl: '/garden.png' } },
    { id: 'video', type: 'videoGeneration', data: { sourceScriptId: 'script', storyKind: 'shot_video', prompt: '过期提示词', promptNodeId: 'prompt', referenceNodeIds: ['role', 'scene'], mediaUrl: '/old-video.mp4' } },
  ]
  return { nodes, edges: ['prompt', 'role', 'scene'].map((source) => ({ source, target: 'video' })), video: nodes[3] }
}

test('shot video consumes latest text and selected reference images, excluding an older video result', () => {
  const { nodes, edges, video } = graph()
  const result = storyVideoInputs(video, nodes, edges)
  assert.equal(result.prompt, '最新文本中的分镜提示词')
  assert.equal(result.mode, 'omni_reference')
  assert.deepEqual(result.references.map((ref) => ref.url), ['/chosen.png', '/garden.png'])
  nodes[0].data.text = '再次编辑'; assert.equal(storyVideoInputs(video, nodes, edges).prompt, '再次编辑')
})

test('missing scene media and disconnected prompt or image block shot video generation', () => {
  const { nodes, edges, video } = graph()
  assert.throws(() => storyVideoInputs(video, nodes, edges.slice(1)), /提示词文本/)
  assert.throws(() => storyVideoInputs(video, nodes, edges.slice(0, 2)), /连线不完整/)
  nodes[2].data.mediaUrl = ''; assert.throws(() => storyVideoInputs(video, nodes, edges), /先生成参考图.*桃园/)
  nodes[2].data.mediaUrl = '/old.png'; nodes[2].data.status = 'running'
  assert.throws(() => storyVideoInputs(video, nodes, edges), /先完成参考图/)
  assert.equal(storyVideoInputs({ id: 'generic', data: {} }, [], []), undefined)
})

test('shot video rejects cross-script references and character-only references', () => {
  const { nodes, edges, video } = graph()
  nodes[0].data.sourceScriptId = 'other'
  assert.throws(() => storyVideoInputs(video, nodes, edges), /同一个剧本/)
  nodes[0].data.sourceScriptId = 'script'
  nodes[2].data.sourceScriptId = 'other'
  assert.throws(() => storyVideoInputs(video, nodes, edges), /同一剧本/)
  nodes[2].data.sourceScriptId = 'script'
  video.data.referenceNodeIds = ['role']
  assert.throws(() => storyVideoInputs(video, nodes, edges), /缺少场景/)
})
