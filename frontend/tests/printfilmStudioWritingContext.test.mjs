import test from 'node:test'
import assert from 'node:assert/strict'
import { createWritingReferenceResolver, writingContext, linkedWritingPrompt, linkedWritingResult, writingRequest, toggleWritingReference, writingParametersChanged, assertWritingParameters } from '../src/features/printfilm-studio/canvas/writingContext.ts'
import { studioGenerationError } from '../src/features/printfilm-studio/canvas/generationError.ts'
import { dependencyPlan, dependencySignature } from '../src/features/printfilm-studio/agent/dependencyRun.ts'
import { splitPrompt, plainPrompt } from '../src/features/printfilm-studio/canvas/promptMentions.ts'
import { editableWritingRequirements } from '../src/features/printfilm-studio/canvas/textWriting.ts'
import { currentImageModel, currentTextModel } from '../src/features/printfilm-studio/modelPreferences.ts'

test('retired model preferences fall forward and legacy preamble is hidden without losing user requirements',()=>{
  assert.equal(currentTextModel('kimi-k2.6'),'gpt-6.1-sol')
  assert.equal(currentTextModel('gpt-5.5','deepseek-v4-pro'),'deepseek-v4-pro')
  assert.equal(currentTextModel('deepseek-v4-pro'),'deepseek-v4-pro')
  assert.equal(currentImageModel('seedream-5.0-pro'),'seedream-5.0')
  assert.equal(currentImageModel('gpt-image-2'),'gpt-image-2.5')
  const requirements='4 秒，军队向北行进，旗帜飘扬。'
  const saved='根据下游视频模型、已连接的参考素材和以下创作要求，生成最终可执行的中文视频提示词。只输出提示词正文。\n\n创作要求：\n'+requirements
  assert.equal(editableWritingRequirements(saved),requirements)
  assert.equal(editableWritingRequirements('创作要求：\n'+requirements),'创作要求：\n'+requirements)
  assert.equal(writingRequest(saved,[],[]),requirements)
})

test('Seedance switches keep usable prose but duration, ratio and other families invalidate it',()=>{
  const writer = {id:'writer',data:{writingOutputSettings:[{id:'video',model:'seedance-2.0-fast',ratio:'16:9',duration:'6'}]}}
  const output = {id:'video',label:'视频',kind:'video',model:'seedance-2.5',ratio:'16:9',duration:'6'}
  for (const model of ['seedance-2.0','seedance-2.5','doubao-seedance-2-0-fast-260128']) assert.doesNotThrow(()=>assertWritingParameters(writer,{...output,model}))
  for (const patch of [{duration:'8'},{ratio:'9:16'},{model:'MiniMax-H3'},{model:'seedance-1.5'}]) assert.throws(()=>assertWritingParameters(writer,{...output,...patch}),/重新生成/)
  const error=studioGenerationError('ModelNotOpen: doubao-seedance-2-0-fast-260128 not activated')
  assert.match(error,/上次任务.*2.0 Fast/)
  assert.match(error,/不代表当前所选模型/)
})

test('generated prose retains stable image IDs, handles @names and ambiguous names safely',()=>{
  const {nodes,edges,writer}=graph()
  const refs=writingContext(writer,nodes,edges).references
  const result=linkedWritingResult('@角色·司马懿在城门抬头。',refs)
  assert.deepEqual(splitPrompt(result).filter(p=>'reference'in p).map(p=>p.reference.id),['role','scene'])
  assert.ok(!result.includes('@@'))
  assert.equal(linkedWritingResult(result,refs),result)
  const ambiguous=[{...refs[0],label:'人'},{...refs[1],label:'人'}]
  const withRefs=linkedWritingResult('人群走过。',ambiguous)
  assert.ok(withRefs.startsWith('人群走过。\n参考图片：'))
  assert.deepEqual(splitPrompt(withRefs).filter(p=>'reference'in p).map(p=>p.reference.id),['role','scene'])
  assert.equal(linkedWritingResult('',refs),'')
})

function graph() {
  const nodes = [
    {id:'writer',type:'text',data:{text:'',writingPrompt:'角色·司马懿抬头，约5秒，16:9。前2秒站立。',sourceScriptId:'s',outputNodeId:'video'}},
    {id:'role',type:'character',data:{label:'角色·司马懿',sourceScriptId:'s',storyKind:'character',mediaUrls:['/old.png','/chosen.png'],mediaIndex:1}},
    {id:'scene',type:'scene',data:{label:'城门',sourceScriptId:'s',storyKind:'scene',mediaUrl:'/scene.png'}},
    {id:'foreign',type:'image',data:{label:'其他剧本',sourceScriptId:'other',mediaUrl:'/foreign.png'}},
    {id:'video',type:'videoGeneration',data:{label:'镜头1',sourceScriptId:'s',storyKind:'shot_video',promptNodeId:'writer',referenceNodeIds:['role','scene'],modelId:'video-model',ratio:'9:16',duration:'8'}},
  ]
  const edges = ['writer','role','scene'].map(source=>({id:source,source,target:'video'}))
  return {nodes,edges,writer:nodes[0],video:nodes[4]}
}

test('writing resolves downstream reference images, selected variants and node parameters',()=>{
  const {nodes,edges,writer}=graph()
  const context=writingContext(writer,nodes,edges,{imageModel:'img',videoModel:'wrong',imageRatio:'1:1',videoRatio:'16:9',duration:'5'})
  assert.deepEqual(context.references.map(ref=>ref.url),['/chosen.png','/scene.png'])
  assert.deepEqual([context.outputs[0].model,context.outputs[0].ratio,context.outputs[0].duration],['video-model','9:16','8'])
  const value=linkedWritingPrompt(writer.data.writingPrompt,context.references,context.outputs)
  assert.match(plainPrompt(value),/约 8 秒，9:16。前2秒/)
  assert.deepEqual(splitPrompt(value).filter(part=>'reference'in part).map(part=>part.reference.id),['role','scene'])
  assert.equal(linkedWritingPrompt(value,context.references,context.outputs),value,'idempotent stable image tokens')
  assert.match(writingRequest(value,context.references,context.outputs),/下游实际生成参数.*\n镜头1：模型 video-model，比例 9:16，时长 8 秒/s)
})

test('changing references updates writer and video edges and preserves existing IDs',()=>{
  const {nodes,edges,writer}=graph()
  const next={id:'new',type:'character',data:{sourceScriptId:'s',storyKind:'character',label:'斥候'}}
  const added=toggleWritingReference(writer,[...nodes,next],edges,'new')
  assert.deepEqual(added.nodes.find(n=>n.id==='video').data.referenceNodeIds,['role','scene','new'])
  assert.ok(added.edges.some(e=>e.source==='new'&&e.target==='writer'))
  assert.ok(added.edges.some(e=>e.source==='new'&&e.target==='video'))
  const removed=toggleWritingReference(added.nodes[0],added.nodes,added.edges,'role')
  assert.ok(!removed.edges.some(e=>e.source==='role'))
  assert.ok(!removed.nodes.find(n=>n.id==='video').data.referenceNodeIds.includes('role'))
  assert.throws(()=>toggleWritingReference(writer,nodes,edges,'foreign'),/同一剧本/)
})

test('changed downstream parameters invalidate the binding and writer-only run signature',()=>{
  const {nodes,edges,writer,video}=graph()
  writer.data.text='完成的提示词'
  writer.data.writingOutputSettings=writingContext(writer,nodes,edges).outputs
  assert.deepEqual(dependencyPlan(['writer'],nodes,edges),[])
  const before=dependencySignature(['writer'],nodes,edges)
  video.data.duration='10'
  const outputs=writingContext(writer,nodes,edges).outputs
  assert.ok(writingParametersChanged(writer,outputs))
  assert.throws(()=>assertWritingParameters(writer,outputs[0]),/重新生成/)
  assert.notEqual(dependencySignature(['writer'],nodes,edges),before)
  assert.deepEqual(dependencyPlan(['writer'],nodes,edges).map(n=>n.id),['writer'])
})


test('pending connected references remain visible and update without changing linkage', async () => {
  const {linkedNodeReferences,referenceState}=await import('../src/features/printfilm-studio/canvas/linkedNodeReferences.ts')
  const writer={id:'w',type:'text',data:{text:'',label:'提示词'}}
  const image={id:'i',type:'image',data:{label:'角色'}}
  const video={id:'v',type:'videoGeneration',data:{promptNodeId:'w',referenceNodeIds:['i','missing']}}
  const nodes=[writer,image,video],edges=[{source:'i',target:'v'},{source:'w',target:'v'}]
  assert.deepEqual(linkedNodeReferences(video,nodes,edges).map(n=>n.id),['i','w'])
  assert.equal(referenceState(writer),'待生成');assert.equal(referenceState(image),'待生成')
  assert.equal(referenceState({...image,data:{status:'running'}}),'生成中')
  assert.equal(referenceState({...image,data:{status:'failed'}}),'生成失败')
  assert.equal(referenceState({...image,data:{mediaUrl:'/ready.png'}}),'')
  assert.equal(referenceState({...writer,data:{text:'镜头提示词'}}),'')
})

test('writing reference cache survives selection and movement, invalidates generated content',()=>{
  const {nodes,edges,writer}=graph(),resolve=createWritingReferenceResolver()
  const first=resolve(writer.id,nodes,edges)
  const moved=nodes.map(n=>({...n,selected:true,position:{x:100,y:200}}))
  assert.equal(resolve(moved[0].id,moved,[...edges]),first)
  const changed=moved.map(n=>n.id==='scene'?{...n,data:{...n.data,mediaUrl:'/new.png'}}:n)
  assert.notEqual(resolve(changed[0].id,changed,edges),first)
})
