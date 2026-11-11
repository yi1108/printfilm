import test from 'node:test'
import assert from 'node:assert/strict'
import { compositionClips,compositionError } from '../src/features/printfilm-studio/canvas/composition.ts'
import { disconnectStudioEdge } from '../src/features/printfilm-studio/canvas/connections.ts'
import { generationControls } from '../src/features/printfilm-studio/canvas/generationControls.ts'
import { validateStudioConnection } from '../src/features/printfilm-studio/canvas/nodeOperations.ts'

const node=(id,type,data={})=>({id,type,data,position:{x:0,y:0}})
test('composition respects saved order and active video versions, blocks pending clips and never drops inputs silently',()=>{
  const nodes=[node('v1','video',{mediaUrls:['a.mp4','b.mp4'],mediaIndex:1}),node('v2','video',{label:'镜头2',status:'running',mediaUrl:'old.mp4'}),node('out','compose',{compositionOrder:['v2','deleted','v1']})]
  const edges=[{id:'e1',source:'v1',target:'out'},{id:'e2',source:'v2',target:'out'}]
  const clips=compositionClips('out',nodes,edges)
  assert.deepEqual(clips.map(item=>item.id),['v2','v1'])
  assert.equal(clips[1].url,'b.mp4')
  assert.match(compositionError(clips),/镜头2.*仍在生成/)
  nodes[1].data.status='completed'
  assert.equal(compositionError(compositionClips('out',nodes,edges)),'')
  assert.match(compositionError(clips.slice(0,1)),/至少 2/)
  assert.match(compositionError(Array.from({length:9},()=>clips[1])),/最多.*8/)
})
test('cutting an edge also clears input and output bindings without modifying unrelated data',()=>{
  const nodes=[node('writer','text',{outputNodeId:'video',text:'保留正文'}),node('video','video',{promptNodeId:'writer',referenceNodeIds:['writer','image'],compositionOrder:['writer','image'],mediaUrl:'keep.mp4'})]
  const edges=[{id:'cut',source:'writer',target:'video'},{id:'keep',source:'image',target:'video'}]
  const result=disconnectStudioEdge(nodes,edges,'cut')
  assert.equal(result.edges.length,1)
  assert.equal(result.nodes[0].data.outputNodeId,undefined)
  assert.equal(result.nodes[1].data.promptNodeId,undefined)
  assert.deepEqual(result.nodes[1].data.referenceNodeIds,['image'])
  assert.equal(result.nodes[1].data.mediaUrl,'keep.mp4')
  assert.equal(nodes[0].data.outputNodeId,'video','original graph supports undo')
})
test('image choices follow reference layout and composition only accepts videos',()=>{
  assert.deepEqual(generationControls(undefined,false).ratios,['auto','1:1','3:2','2:3'])
  const nodes=[node('image','image'),node('video','video'),node('out','compose')]
  assert.match(validateStudioConnection({source:'image',target:'out'},nodes,[]),/只接受视频/)
  assert.equal(validateStudioConnection({source:'video',target:'out'},nodes,[]),undefined)
})
