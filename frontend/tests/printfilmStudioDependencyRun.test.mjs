import test from 'node:test'
import assert from 'node:assert/strict'
import { selectedRunTargets, dependencyPlan, dependencyQuoteInputs, dependencySignature, executeDependencies } from '../src/features/printfilm-studio/agent/dependencyRun.ts'

const writer = (id) => ({ id, type: 'text', data: { label: id, text: '', writingPrompt: `为 ${id} 写提示词`, sourceScriptId: 'script' } })
const nodes = [writer('character-write'), {id:'character',type:'character',data:{storyKind:'character',sourceScriptId:'script',promptNodeId:'character-write'}}, writer('scene-write'), {id:'scene',type:'scene',data:{storyKind:'scene',sourceScriptId:'script',promptNodeId:'scene-write'}}, {...writer('shot-write'),data:{...writer('shot-write').data,referenceNodeIds:['character','scene']}}, {id:'video',type:'videoGeneration',data:{storyKind:'shot_video',sourceScriptId:'script',promptNodeId:'shot-write',referenceNodeIds:['character','scene']}},writer('unrelated')]
const edges = [['character-write','character'],['scene-write','scene'],['character','shot-write'],['scene','shot-write'],['shot-write','video'],['character','video'],['scene','video']].map(([source,target])=>({source,target}))
const settings = {textModel:'llm',imageModel:'image-model',videoModel:'video-model',imageRatio:'1:1',videoRatio:'16:9',imageResolution:'1K',videoResolution:'720p',duration:'5'}

test('run to a writer includes only its ancestors and quotes deferred text/media without altering graph', () => {
  const plan = dependencyPlan(['shot-write'],nodes,edges)
  assert.deepEqual(plan.map(node=>node.id),['character-write','character','scene-write','scene','shot-write'])
  const before = JSON.stringify(nodes)
  const inputs = dependencyQuoteInputs(plan,nodes,edges,settings)
  assert.equal(inputs.filter(input=>input.kind==='text').length,3)
  assert.equal(inputs.filter(input=>input.kind==='image').length,2)
  assert.equal(JSON.stringify(nodes),before)
  const videoPlan = dependencyPlan(['video'],nodes,edges)
  const video = dependencyQuoteInputs(videoPlan,nodes,edges,settings).at(-1)
  assert.deepEqual(video.references.map(ref=>ref.id),['character','scene'])
})

test('valid results are reused and running dependencies are waited for without requoting', () => {
  const copy=structuredClone(nodes)
  copy.find(node=>node.id==='character').data.mediaUrl='/character.png'
  copy.find(node=>node.id==='scene').data.status='running'
  const plan=dependencyPlan(['shot-write'],copy,edges)
  assert.ok(!plan.some(node=>node.id==='character-write'||node.id==='character'))
  const inputs=dependencyQuoteInputs(plan,copy,edges,settings)
  assert.ok(!inputs.some(input=>input.id==='scene'))
  assert.equal(inputs.at(-1).id,'shot-write')
})

test('missing dependencies and cycles fail before submitting anything', () => {
  assert.throws(()=>dependencyPlan(['video'],nodes,edges.filter(edge=>!(edge.source==='scene'&&edge.target==='video'))),/连线/)
  assert.throws(()=>dependencyPlan(['video'],nodes,[...edges,{source:'video',target:'character-write'}]),/循环/)
  assert.throws(()=>dependencyPlan(['unknown'],nodes,edges),/删除/)
})

test('scheduler starts independent branches together and waits for actual results', async () => {
  const plan=dependencyPlan(['shot-write'],nodes,edges), started=[], finished=new Set(), releases={}
  const run=executeDependencies(plan,edges,async node=>{
    started.push(node.id)
    for(const edge of edges.filter(edge=>edge.target===node.id))assert.ok(finished.has(edge.source),'upstream result exists')
    await new Promise(resolve=>{releases[node.id]=resolve})
    finished.add(node.id)
  },()=>{})
  assert.deepEqual(started,['character-write','scene-write'])
  releases['character-write'](); releases['scene-write']()
  await new Promise(resolve=>setImmediate(resolve))
  assert.deepEqual(started.slice(2),['character','scene'])
  releases.character()
  await new Promise(resolve=>setImmediate(resolve))
  assert.ok(!started.includes('shot-write'))
  releases.scene()
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(started.at(-1),'shot-write')
  releases['shot-write']();await run
})

test('upstream failure stops downstream, and cancellation prevents another layer', async () => {
  const started=[]
  await assert.rejects(executeDependencies(dependencyPlan(['video'],nodes,edges),edges,async node=>{started.push(node.id);if(node.id==='scene-write')throw Error('模型失败')},()=>{}),/模型失败/)
  assert.deepEqual(started,['character-write','scene-write'])
  let stop=false
  await assert.rejects(executeDependencies(dependencyPlan(['video'],nodes,edges),edges,async()=>{stop=true},()=>{if(stop)throw Error('停止')}),/停止/)
})

test('runtime media layout does not invalidate approval, but requirements and reused inputs do', () => {
  const copy=structuredClone(nodes), ids=dependencyPlan(['shot-write'],copy,edges).map(node=>node.id)
  const before=dependencySignature(ids,copy,edges)
  Object.assign(copy[1].data,{mediaUrl:'/generated.png',mediaLayoutUrl:'/generated.png',naturalWidth:1024,naturalHeight:768,status:'completed'})
  assert.equal(dependencySignature(ids,copy,edges),before)
  copy[0].data.writingPrompt='用户更改要求'
  assert.notEqual(dependencySignature(ids,copy,edges),before)
  const remaining=dependencyPlan(['shot-write'],copy,edges).map(node=>node.id)
  const reuse=dependencySignature(remaining,copy,edges)
  copy[1].data.mediaUrl='/replacement.png'
  assert.notEqual(dependencySignature(remaining,copy,edges),reuse)
})

test('box-selection run targets expand selected groups and exclude non-executable nodes', () => {
  const group = {id:'group', type:'group', data:{}}
  const grouped = [group, {...nodes[0],parentId:'group'}, {...nodes[1],parentId:'group'}, {id:'audio',type:'audio',data:{}}]
  assert.deepEqual(selectedRunTargets(['group','audio'],grouped), ['character-write','character'])
  assert.deepEqual(selectedRunTargets(['character-write'],grouped), ['character-write'])
})
