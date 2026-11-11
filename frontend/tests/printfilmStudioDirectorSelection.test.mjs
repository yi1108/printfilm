import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

test('director skill picker changes phase and skill; Agent sends chosen phase and restores choices',async()=>{
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
  const old=new Map()
  const install=(key,value)=>{old.set(key,Object.getOwnPropertyDescriptor(globalThis,key));Object.defineProperty(globalThis,key,{configurable:true,writable:true,value})}
  for(const key of ['window','document','navigator','HTMLElement','Element','Node','Event','MouseEvent','KeyboardEvent','localStorage'])install(key,dom.window[key])
  install('IS_REACT_ACT_ENVIRONMENT',true)
  install('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}})
  const skills=[
    {id:1,slug:'printfilm-script-director',name:'剧本导演',description:'按场创作',tasks:['script_write'],is_active:true,body:'剧本规则'},
    {id:2,slug:'short-drama-storyboard',name:'剧情分镜',description:'空间连续性',tasks:['shot_plan'],is_active:true,body:'分镜规则'},
    {id:3,slug:'printfilm-product-director',name:'产品广告导演',description:'产品外形和光线',tasks:['shot_plan','video_prompt'],is_active:true,body:'产品规则'},
  ]
  install('fetch',async url=>{
    if(String(url).endsWith('/drama/skills'))return Response.json({items:skills})
    if(String(url).endsWith('/agent/config'))return Response.json({models:[],tools:['read_canvas','plan_story_assets','plan_story_shots','create_video_task']})
    return Response.json({sessions:[]})
  })
  let server,root
  try{
    server=await createServer({configFile:false,root:fileURLToPath(new URL('..',import.meta.url)),plugins:[react()],server:{middlewareMode:true,hmr:false,ws:false,watch:null},logLevel:'error'})
    const {AgentPanel}=await server.ssrLoadModule('/src/features/printfilm-studio/agent/AgentPanel.tsx')
    const {createElement:h,act}=await import('react')
    const {createRoot}=await import('react-dom/client')
    const noop=()=>{},sent=[]
    const props={projectId:7,sessionId:null,events:[],answer:'',running:false,prompt:'请规划分镜',nodes:[],edges:[],assets:[],headers:{},writable:true,onDockWidth:noop,onHistoryChange:noop,onPrompt:noop,onSend:async(...args)=>sent.push(args),onGenerateMedia:noop,onRepairStory:async()=>{},onStop:noop,onSelectSession:noop,onClose:noop}
    root=createRoot(document.getElementById('root'))
    await act(async()=>root.render(h(AgentPanel,props)))
    const click=async element=>{assert.ok(element);await act(async()=>element.dispatchEvent(new MouseEvent('click',{bubbles:true})))}
    const byText=text=>[...document.querySelectorAll('button')].find(item=>item.textContent===text)
    await click(byText('按场拆镜'))
    await click([...document.querySelectorAll('[role="radio"]')].find(item=>item.textContent.includes('产品广告导演')))
    assert.match(document.querySelector('[aria-label="选择导演技能"]').textContent,/产品广告导演/)
    await click(document.querySelector('[aria-label="发送消息"]'))
    assert.equal(sent[0][0].skill_task,'shot_plan')
    assert.deepEqual(sent[0][0].skill_ids,[3])
    assert.equal(sent[0][0].director_skill_selection.shot_plan,3)
    assert.ok(!sent[0][0].enabled_tools.includes('create_video_task'))
    await act(async()=>root.unmount())
    root=createRoot(document.getElementById('root'))
    await act(async()=>root.render(h(AgentPanel,props)))
    assert.equal(JSON.parse(localStorage.getItem('pf-director-skills:7')).shot_plan,3)
    await click(byText('按场拆镜'))
    assert.ok(document.querySelector('[role=radio][aria-checked=true]').textContent.includes('产品广告导演'),'selected director is restored after remount')
    await act(async()=>root.render(h(AgentPanel,{...props,running:true})))
    assert.ok([...document.querySelectorAll('[role="radio"]')].every(item=>item.disabled))
  }finally{
    if(root){const {act}=await import('react');await act(async()=>root.unmount())}
    await server?.close();dom.window.close()
    for(const [key,descriptor] of old){if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key]}
  }
})
