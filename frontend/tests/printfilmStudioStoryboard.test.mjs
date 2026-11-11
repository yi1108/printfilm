import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

test('storyboard categories, details, media actions, sequence persistence and read-only controls', async () => {
  const dom = new JSDOM('<div id="root"></div>', {url:'http://localhost',pretendToBeVisual:true})
  const previous = new Map()
  for(const name of ['window','document','navigator','HTMLElement','Element','Node','Event','MouseEvent','KeyboardEvent','localStorage']) {
    previous.set(name,Object.getOwnPropertyDescriptor(globalThis,name))
    Object.defineProperty(globalThis,name,{configurable:true,writable:true,value:dom.window[name]})
  }
  previous.set('IS_REACT_ACT_ENVIRONMENT',Object.getOwnPropertyDescriptor(globalThis,'IS_REACT_ACT_ENVIRONMENT'))
  globalThis.IS_REACT_ACT_ENVIRONMENT=true
  dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true}
  dom.window.HTMLDialogElement.prototype.close=function(){this.open=false}
  let server,root
  try {
    server=await createServer({configFile:false,root:fileURLToPath(new URL('..',import.meta.url)),plugins:[react()],server:{middlewareMode:true,hmr:false,ws:false,watch:null},logLevel:'error'})
    const {createElement:h,act,useState}=await import('react')
    const {createRoot}=await import('react-dom/client')
    const {StoryboardWorkspace}=await server.ssrLoadModule('/src/features/printfilm-studio/storyboard/StoryboardWorkspace.tsx')
    const {StudioNodeActionsContext}=await server.ssrLoadModule('/src/features/printfilm-studio/canvas/studioNodeContext.ts')
    const {setStorySequence,storySequence,storyDuration,storyStatus}=await server.ssrLoadModule('/src/features/printfilm-studio/storyboard/storyboardState.ts')
    const {encodeCanvasDocument,decodeCanvasDocument}=await server.ssrLoadModule('/src/features/printfilm-studio/canvas/canvasCodec.ts')
    const make=(id,type,data={})=>({id,type,position:{x:0,y:0},data:{label:id,...data}})
    const original=[make('角色图','image',{mediaUrl:'/a.png',mediaUrls:['/a.png','/b.png']}),make('镜头一','videoGeneration',{mediaUrl:'/v1.mp4',duration:'5'}),make('镜头二','video',{mediaUrl:'/v2.mp4',duration:'7'}),make('剧本','text',{text:'# 测试'}),make('配音','audio'),make('未完成','video',{status:'running'})]
    const ordered=setStorySequence(original,['镜头二','镜头一','镜头二','剧本','missing'])
    assert.deepEqual(storySequence(ordered).map(n=>n.id),['镜头二','镜头一'])
    assert.equal(storyDuration(ordered[0]),3)
    assert.equal(storyStatus(original.at(-1)),'生成中…')
    const canvasDocument={toonflowCanvas:true,version:1,nodes:ordered,edges:[],viewport:{x:0,y:0,zoom:1}}
    assert.deepEqual(storySequence(decodeCanvasDocument(JSON.parse(JSON.stringify(encodeCanvasDocument(canvasDocument)))).nodes).map(n=>n.id),['镜头二','镜头一'])
    assert.equal(storySequence(setStorySequence(ordered,[])).length,0)
    assert.equal(original[0].data.storyboardOrder,undefined)
    const calls=[];let currentNodes, writable=true
    const actions={writable:true,submittingNodeIds:new Set(),openComposer:(...args)=>calls.push(args),preview:id=>calls.push(['preview',id]),history:id=>calls.push(['history',id]),download:id=>calls.push(['download',id]),ask:id=>calls.push(['ask',id]),rename:()=>{},duplicate:()=>{},remove:()=>{},upload:()=>{},mediaEdit:()=>{},setMediaIndex:()=>{},compareVariants:()=>{},splitVariants:()=>{}}
    function Harness(){const [nodes,setNodes]=useState(original),[selected,setSelected]=useState(null);currentNodes=nodes;return h(StudioNodeActionsContext.Provider,{value:{...actions,writable}},h(StoryboardWorkspace,{nodes,selectedId:selected,onSelect:setSelected,onAdd:()=>null,onLocate:id=>calls.push(['locate',id]),onSequence:ids=>setNodes(n=>setStorySequence(n,ids)),onDuration:()=>{},onCompose:ids=>calls.push(['compose',...ids]),onSave:()=>{},onUndo:()=>{},onRedo:()=>{},canUndo:false,canRedo:false,onAssets:()=>{},onAgent:()=>{}}))}
    root=createRoot(document.getElementById('root'))
    await act(async()=>root.render(h(Harness)))
    const click=async el=>{assert.ok(el);await act(async()=>el.dispatchEvent(new MouseEvent('click',{bubbles:true})))}
    const byLabel=label=>document.querySelector(`[aria-label="${label}"]`)
    const byText=text=>[...document.querySelectorAll('button')].find(el=>el.textContent===text)
    assert.equal(document.querySelectorAll('.pf-board-section').length,4)
    await click([...document.querySelectorAll('.pf-board-tabs button')].find(el=>el.textContent==='图片'))
    assert.equal(document.querySelectorAll('.pf-board-section').length,1)
    await click(byLabel('打开角色图'))
    assert.ok(byLabel('素材详情'))
    await click(byText('裁剪'));await click(byText('图生视频'));await click(byText('参考生成视频'))
    assert.deepEqual(calls.slice(0,3),[['角色图','crop'],['角色图','video'],['角色图','reference']])
    await click(byLabel('预览素材'));assert.deepEqual(calls.at(-1),['preview','角色图'])
    await click(byText('加入分镜'));assert.deepEqual(storySequence(currentNodes).map(n=>n.id),['角色图'])
    await click(byLabel('分镜配音'));assert.ok(byLabel('预览背景音'))
    await click(byText('清空'));assert.equal(storySequence(currentNodes).length,0);assert.equal(currentNodes.length,original.length)
    await click(byLabel('返回分类网格'));assert.equal(byLabel('素材详情'),null)
    await click([...document.querySelectorAll('.pf-board-tabs button')].find(el=>el.textContent==='视频'))
    await click(byLabel('打开镜头二'));await click(byText('加入分镜'))
    await click(byLabel('打开镜头一'));await click(byText('加入分镜'))
    await click(byLabel('剪辑合成分镜'));assert.deepEqual(calls.at(-1),['compose','镜头二','镜头一'])
    await click(document.querySelectorAll('[aria-label="分镜前移"]')[1]);assert.deepEqual(storySequence(currentNodes).map(n=>n.id),['镜头一','镜头二'])
    writable=false;await act(async()=>root.render(h(Harness)))
    assert.equal(byLabel('添加视频').disabled,true)
    assert.equal(byLabel('剪辑合成分镜').disabled,true)
    assert.equal(byLabel('下载素材').disabled,false)
  } finally {
    if(root){const {act}=await import('react');await act(async()=>root.unmount())}
    await server?.close();dom.window.close()
    for(const [key,value] of previous){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key]}
  }
})
