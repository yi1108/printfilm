import test from 'node:test'
import assert from 'node:assert/strict'
import { storyGuide, storyImageState, storyStagePrompt } from '../src/features/printfilm-studio/agent/storyWorkflow.ts'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

test('story guide advances from persisted nodes, scopes assets to the selected script and sorts shots', () => {
  const script = { id: 's', type: 'script', data: { label: '桃园结义', text: '剧本正文' } }
  const other = { id: 'other', type: 'script', data: { label: '另一个故事', text: '正文' } }
  const role = { id: 'role', type: 'character', data: { sourceScriptId: 's', storyKind: 'character', prompt: '角色提示词' } }
  const scene = { id: 'scene', type: 'scene', data: { sourceScriptId: 's', storyKind: 'scene', prompt: '场景提示词' } }
  assert.equal(storyGuide([script, other], ['s']).assetsReady, false)
  script.data.storyAssetsReady = true
  script.data.storyShotsReady = true
  const shots = [2, 1].map((index) => ({ id: `shot-${index}`, type: 'imageGeneration', data: { sourceScriptId: 's', storyKind: 'shot', shotIndex: index } }))
  const guide = storyGuide([script, other, role, scene, ...shots], ['role'], [{source: 's', target: 'role'}, {source: 's', target: 'scene'}])
  assert.equal(guide.script.id, 's')
  assert.equal(guide.assetsReady, true)
  assert.equal(guide.shotsReady, true)
  assert.deepEqual(guide.shots.map((node) => node.id), ['shot-1', 'shot-2'])
  assert.equal(storyGuide([script, other, role, scene], ['other']).assets.length, 0)
  assert.equal(storyGuide([script, other], ['s']).assetsReady, false)
  assert.doesNotMatch(storyStagePrompt('assets', script), /plan_story|node_id/)
})

test('queued and failed image tasks never look completed just because an older image exists', () => {
  const node = { id: 's', data: { mediaUrl: '/old.png', status: 'queued' } }
  assert.equal(storyImageState(node), 'running')
  node.data.status = 'failed'; assert.equal(storyImageState(node), 'failed')
  node.data.status = 'completed'; assert.equal(storyImageState(node), 'completed')
  assert.equal(storyImageState({ id: 's', data: { prompt: '提示词' } }), 'pending')
})

test('generating status and pinned plan remain visible after partial assistant text', async () => {
  const server = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
  try {
    const { AgentConversation } = await server.ssrLoadModule('/src/features/printfilm-studio/agent/AgentConversation.tsx')
    const { createElement: h } = await import('react')
    const { renderToStaticMarkup } = await import('react-dom/server')
    const props = { events: [{ type: 'user', text: '写剧本' }], answer: '正在写剧本正文', sessionId: 's', labels: {}, onPrompt() {}, async onAction() {}, guide: h('div', null, '引导下一步') }
    const running = renderToStaticMarkup(h(AgentConversation, { ...props, running: true }))
    assert.match(running, /正在写剧本正文/)
    assert.match(running, /pf-agent-progress/)
    assert.match(running, /生成中/)
    assert.match(running, /引导下一步/)
    const done = renderToStaticMarkup(h(AgentConversation, { ...props, running: false }))
    assert.doesNotMatch(done, /pf-agent-progress/)
    assert.match(done, /引导下一步/)
    const proposal = {id:'card',nodes:[],edges:[]}
    const controls = {nodes:[],states:{},writable:true,busy:false,async onAction(){},onRun(){}}
    const events = [{type:'user',text:'写剧本'}, {type:'proposal',text:'',data:proposal}, {type:'assistant',text:'长剧本最后一段'}]
    const history = renderToStaticMarkup(h(AgentConversation,{...props,events,answer:'',running:false,proposals:controls}))
    assert.ok(history.indexOf('长剧本最后一段') < history.indexOf('pf-agent-proposal'))
    const live = renderToStaticMarkup(h(AgentConversation,{...props,events:events.slice(0,2),answer:'流式正文最后一段',running:true,proposals:controls}))
    assert.ok(live.indexOf('流式正文最后一段') < live.indexOf('pf-agent-proposal'))
    const progress = renderToStaticMarkup(h(AgentConversation,{...props,events:[{type:'user',text:'规划'}, {type:'model_progress',text:'正在接收分镜方案，已收到 2048 字符'}],answer:'',running:true}))
    assert.equal(progress.split('正在接收分镜方案').length-1,1)
    assert.match(progress,/已收到 2048 字符/)
  } finally { await server.close() }
})

test('legacy split is recognized, missing scenes and links require repair instead of splitting again', () => {
  const script = { id: 's', type: 'script', data: { text: '剧本正文', storyAssetsReady: true } }
  const role = { id: 'c', type: 'character', data: { label: '刘备', prompt: '角色', mediaUrl: '/c.png' } }
  const outline = { id: 'o', type: 'storyboard', data: { label: '分镜桃园', text: '镜头1，镜头2' } }
  const guide = storyGuide([script, role, outline])
  assert.equal(guide.planningReady, true)
  assert.equal(guide.assetsReady, false)
  assert.equal(guide.graphReady, false)
  assert.equal(guide.needsRepair, true)
  assert.deepEqual(guide.missingScenes, ['场景'])
})

test('video becomes available only after prompt and generated scene references are connected', () => {
  const script = { id: 's', type: 'script', data: { text: '正文', storyCharacterNames: [], storySceneNames: ['桃园'] } }
  const scene = { id: 'c', type: 'scene', data: { sourceScriptId: 's', label: '桃园', prompt: '场景' } }
  const prompt = { id: 'p', type: 'text', data: { sourceScriptId: 's', storyKind: 'shot_prompt', text: '全景', shotIndex: 1, referenceNodeIds: ['c'] } }
  const video = { id: 'v', type: 'videoGeneration', data: { sourceScriptId: 's', storyKind: 'shot_video', promptNodeId: 'p', referenceNodeIds: ['c'], shotIndex: 1 } }
  const nodes = [script, scene, prompt, video]
  const edges = [{source: 's', target: 'c'}, {source: 's', target: 'p'}, {source: 'p', target: 'v'}, {source: 'c', target: 'v'}]
  assert.equal(storyGuide(nodes, [], edges).graphReady, true)
  assert.equal(storyGuide(nodes, [], edges).shotPlans[0].canGenerate, false)
  scene.data.mediaUrl = '/scene.png'
  assert.equal(storyGuide(nodes, [], edges).shotPlans[0].canGenerate, true)
  assert.equal(storyGuide(nodes, [], edges.slice(0, -1)).shotPlans[0].canGenerate, false)
  const other = { id: 'other', type: 'script', data: { text: '其他剧本' } }
  assert.equal(storyGuide([...nodes, other], ['other'], edges).shots.length, 0)
})

import { visibleStoryEdges } from '../src/features/printfilm-studio/canvas/storyEdgeVisibility.ts'

test('focused story wires show a whole selected shot without deleting saved connections', () => {
  const nodes = [{id: 'v1', data: {storyKind: 'shot_video'}}, {id: 'v2', data: {storyKind: 'shot_video'}}, {id:'p1',data:{storyKind:'shot_prompt'}}, {id:'p2',data:{storyKind:'shot_prompt'}}]
  const edges = [{id:'p1-v1',source:'p1',target:'v1'}, {id:'i-v1',source:'image',target:'v1'}, {id:'i-p1',source:'image',target:'p1'}, {id:'p2-v2',source:'p2',target:'v2'}, {id:'i-p2',source:'image',target:'p2'}, {id:'other',source:'a',target:'b'}]
  assert.deepEqual(visibleStoryEdges(nodes, edges, [], true).map(e=>e.id), ['p1-v1','p2-v2','other'])
  for(const selected of ['p1','v1']) assert.deepEqual(visibleStoryEdges(nodes, edges, [selected], true).map(e=>e.id), ['p1-v1','i-v1','i-p1','p2-v2','other'])
  assert.equal(visibleStoryEdges(nodes, edges, ['image'], true).length,edges.length)
  assert.equal(visibleStoryEdges(nodes, edges, [], false), edges)
  assert.equal(edges.length, 6)
  assert.ok(visibleStoryEdges(nodes,[...edges,{id:'selected',source:'another',target:'p2',selected:true}],[],true).some(edge=>edge.id==='selected'))
  assert.equal(visibleStoryEdges(nodes,edges,['p1','p2'],true).length,edges.length)
})

test('script ownership does not require visible script edges', () => {
  const script = {id:'s',type:'script',data:{text:'正文',storyCharacterNames:[],storySceneNames:['场景']}}
  const scene = {id:'scene',type:'scene',data:{label:'场景',prompt:'环境',sourceScriptId:'s',storyKind:'scene',mediaUrl:'/scene.png'}}
  const prompt = {id:'p',type:'text',data:{text:'镜头',sourceScriptId:'s',storyKind:'shot_prompt',referenceNodeIds:['scene']}}
  const video = {id:'v',type:'videoGeneration',data:{sourceScriptId:'s',storyKind:'shot_video',promptNodeId:'p',referenceNodeIds:['scene']}}
  const guide = storyGuide([script,scene,prompt,video], [], [{source:'p',target:'v'},{source:'scene',target:'v'}])
  assert.equal(guide.assetsReady,true)
  assert.equal(guide.graphReady,true)
  assert.equal(guide.shotPlans[0].canGenerate,true)
})
