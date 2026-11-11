import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {JSDOM} from 'jsdom'
import {createServer} from 'vite'
import react from '@vitejs/plugin-react'

test('cursor traffic and another node action do not rerender an unchanged media card',async()=>{
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true}),old=new Map()
  for(const key of ['window','document','navigator','HTMLElement','Node','Event','MouseEvent','localStorage']){old.set(key,Object.getOwnPropertyDescriptor(globalThis,key));Object.defineProperty(globalThis,key,{configurable:true,writable:true,value:dom.window[key]})}
  old.set('IS_REACT_ACT_ENVIRONMENT',Object.getOwnPropertyDescriptor(globalThis,'IS_REACT_ACT_ENVIRONMENT'));globalThis.IS_REACT_ACT_ENVIRONMENT=true
  let server,root
  try {
    server=await createServer({configFile:false,root:fileURLToPath(new URL('..',import.meta.url)),plugins:[react()],server:{middlewareMode:true,hmr:false,ws:false,watch:null},logLevel:'error'})
    const {useCanvasPresence}=await server.ssrLoadModule('/src/features/printfilm-studio/collaboration.ts')
    const {StudioNodeCard}=await server.ssrLoadModule('/src/features/printfilm-studio/canvas/StudioNodeCard.tsx')
    const {StudioNodeActionsContext,StudioComposerContext}=await server.ssrLoadModule('/src/features/printfilm-studio/canvas/studioNodeContext.ts')
    const {createElement:h,act,useSyncExternalStore}=await import('react'),{createRoot}=await import('react-dom/client'),{ReactFlowProvider}=await import('@xyflow/react')
    let pageRenders=0,labelReads=0,store,clicked=''
    const data={get label(){labelReads++;return '不变的图片'},mediaUrl:'/preview.png'}
    function Overlay({store}){const snapshot=useSyncExternalStore(store.subscribe,store.getSnapshot);return h('span',{'data-testid':'peers'},String(snapshot.peers.length))}
    function Canvas({version}){
      pageRenders++;const presence=useCanvasPresence(1,false,0);store=presence.store
      const actions={writable:true,selectionCount:version,panelsSuppressed:!!version,submittingNodeIds:new Set(['other']),moreMenu:()=>{clicked=String(version)}}
      return h(ReactFlowProvider,null,h(StudioNodeActionsContext.Provider,{value:actions},h(StudioComposerContext.Provider,{value:null},h(StudioNodeCard,{id:'image',type:'image',data,selected:false,width:320,height:200}))),h(Overlay,{store}))
    }
    root=createRoot(document.getElementById('root'))
    await act(async()=>root.render(h(Canvas,{version:0})))
    const before=labelReads
    for(let i=0;i<20;i++) await act(async()=>store.update({peers:Array.from({length:i%3},()=>({session_id:'peer'}))}))
    assert.equal(pageRenders,1,'presence only updates its overlay')
    assert.equal(labelReads,before,'cursor packets never render the media card')
    await act(async()=>root.render(h(Canvas,{version:1})))
    assert.equal(labelReads,before,'another selection leaves unchanged card render intact')
    await act(async()=>document.querySelector('[aria-label="节点操作"]').dispatchEvent(new MouseEvent('click',{bubbles:true})))
    assert.equal(clicked,'1','memoized handlers still read the latest action')
  } finally {
    if(root){const {act}=await import('react');await act(async()=>root.unmount())}
    await server?.close();dom.window.close();for(const [key,value]of old){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key]}
  }
})
