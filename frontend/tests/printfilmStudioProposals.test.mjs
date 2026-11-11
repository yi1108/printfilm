import test from 'node:test'
import assert from 'node:assert/strict'
import { applyProposal, proposalStatus } from '../src/features/printfilm-studio/agent/proposals.ts'
import { batchInputs } from '../src/features/printfilm-studio/agent/batchGeneration.ts'
import { decodeCanvasDocument } from '../src/features/printfilm-studio/canvas/canvasCodec.ts'
const node = (id, type='text', data={}) => ({id,type,position:{x:0,y:0},data})
const initial = decodeCanvasDocument({nodes:[node('script','script',{text:'原文'})],edges:[]})
const proposal = {id:'proposal',nodes:[{id:'g',before:null,after:{...node('g','group',{children:['p','c']}),style:{width:840,height:530}}},{id:'p',before:null,after:{...node('p','text',{text:'角色外貌'}),parentId:'g'}},{id:'c',before:null,after:{...node('c','character',{promptNodeId:'p'}),parentId:'g'}}],edges:[{id:'p-c',before:null,after:{id:'p-c',source:'p',target:'c'}}]}
test('proposal application is idempotent, persists status and has a guarded group undo',()=>{
  const applied = applyProposal(initial,proposal,'apply')
  assert.equal(initial.nodes.length,1)
  assert.equal(applied.nodes.length,4)
  assert.equal(proposalStatus(proposal,applied.agentProposalStates,applied.nodes),'applied')
  assert.deepEqual(applyProposal(applied,proposal,'apply'),applied)
  const measured = structuredClone(applied)
  Object.assign(measured.nodes.find(n=>n.id==='g'),{width:840,height:530,selected:true})
  const undone = applyProposal(measured,proposal,'undo')
  assert.deepEqual(undone.nodes,initial.nodes)
  assert.equal(undone.agentProposalStates.proposal,'undone')
  applied.nodes.find(n=>n.id==='c').data.mediaUrl='/new.png'
  assert.throws(()=>applyProposal(applied,proposal,'undo'),/已运行生成/)
})
test('proposal conflicts never overwrite newer text and unrelated edits survive',()=>{
  const before=initial.nodes[0], after={...before,data:{text:'新版'}}
  const change={id:'edit',nodes:[{id:'script',before,after}],edges:[]}
  const current=structuredClone(initial)
  current.nodes[0].data.label='用户改名'
  assert.equal(applyProposal(current,change,'apply').nodes[0].data.label,'用户改名')
  current.nodes[0].data.text='用户正文'
  assert.throws(()=>applyProposal(current,change,'apply'),/已被修改/)
  assert.equal(applyProposal(current,proposal,'ignore').nodes.length,1)
})
test('undo does not orphan newly connected nodes or children',()=>{
  const doc=applyProposal(initial,proposal,'apply')
  doc.nodes.push(node('other'))
  doc.edges.push({id:'new',source:'c',target:'other'})
  assert.throws(()=>applyProposal(doc,proposal,'undo'),/不存在/)
  doc.edges.pop();doc.nodes.at(-1).parentId='g'
  assert.throws(()=>applyProposal(doc,proposal,'undo'),/其他节点/)
})
test('batch uses the live writing node, skips completed jobs and blocks absent references',()=>{
  const settings={imageModel:'image',videoModel:'video',imageResolution:'1K',videoResolution:'720p',imageRatio:'3:2',videoRatio:'16:9',duration:'5'}
  const nodes=[node('p','text',{text:'最新提示词'}),node('c','character',{label:'角色',promptNodeId:'p',prompt:'旧提示词'})]
  const edges=[{source:'p',target:'c'}]
  assert.equal(batchInputs(['c'],nodes,edges,settings)[0].prompt,'最新提示词')
  assert.throws(()=>batchInputs(['c'],nodes,[],settings),/写作节点/)
  nodes[0].data.text=''
  assert.throws(()=>batchInputs(['c'],nodes,edges,settings),/提示词/)
  nodes[0].data.text='最新提示词'
  nodes[1].data.sourceScriptId='script'
  assert.throws(()=>batchInputs(['c'],nodes,edges,settings),/同一剧本/)
  nodes[0].data.sourceScriptId='script'
  nodes[1].data.status='running'
  assert.deepEqual(batchInputs(['c'],nodes,edges,settings),[])
  nodes[1].data.status='completed';nodes[1].data.mediaUrl='/done.png'
  assert.deepEqual(batchInputs(['c'],nodes,edges,settings),[])
})
