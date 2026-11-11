import test from 'node:test'
import assert from 'node:assert/strict'
import {fileURLToPath} from 'node:url'
import {JSDOM} from 'jsdom'
import {createServer} from 'vite'
import react from '@vitejs/plugin-react'

test('project categories, asset pagination and project teams use project APIs',async()=>{
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/canvas',pretendToBeVisual:true}),old=new Map()
  const install=(key,value)=>{old.set(key,Object.getOwnPropertyDescriptor(globalThis,key));Object.defineProperty(globalThis,key,{configurable:true,writable:true,value})}
  for(const key of ['window','document','navigator','HTMLElement','Node','Event','MouseEvent','localStorage']) install(key,dom.window[key])
  install('IS_REACT_ACT_ENVIRONMENT',true)
  dom.window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}})
  localStorage.setItem('token','test')
  const calls=[],projects=[{id:1,title:'我创建的画布',is_owner:true,workflow:'canvas',asset_count:1,episode_count:0,has_script:true},{id:2,title:'参与的画布',is_owner:false,workflow:'canvas',asset_count:1,episode_count:0,has_script:true}]
  install('fetch',async(input)=>{
    const url=new URL(String(input),'http://localhost');calls.push(url)
    if(url.pathname==='/api/drama/projects') {
      const relation=url.searchParams.get('relation'),items=projects.filter(p=>relation==='owned'?p.is_owner:relation==='joined'?!p.is_owner:true)
      return Response.json({items,meta:{total:items.length,page:1,page_size:Number(url.searchParams.get('page_size')||8)}})
    }
    if(url.pathname==='/api/drama/library-assets') {
      const page=Number(url.searchParams.get('page')||1)
      return Response.json({items:Array.from({length:page===1?8:1},(_,i)=>({key:`image:${page}-${i}`,id:i,source_kind:'drama',type:'image',media_kind:'image',name:`图片${i}`,url:'/image.png',project_id:1,project_title:'项目'})),meta:{total:9,total_all:9,page,page_size:8}})
    }
    if(url.pathname==='/api/projects') return Response.json({items:[],meta:{total:0,page:1,page_size:50}})
    if(url.pathname.includes('capabilities')) return Response.json({enabled:false})
    if(url.pathname.includes('/me')) return Response.json({id:1,email:'local@test.invalid',name:'用户',balance_fen:100})
    return Response.json({items:[],meta:{total:0,page:1,page_size:8}})
  })
  let server,root
  try {
    server=await createServer({configFile:false,root:fileURLToPath(new URL('..',import.meta.url)),plugins:[react()],server:{middlewareMode:true,hmr:false,ws:false,watch:null},logLevel:'error'})
    const {I18nProvider}=await server.ssrLoadModule('/src/i18n/context.tsx')
    const {default:Projects}=await server.ssrLoadModule('/src/pages/drama/DramaListPage.tsx')
    const {default:Assets}=await server.ssrLoadModule('/src/pages/drama/AssetLibraryPage.tsx')
    const {default:Teams}=await server.ssrLoadModule('/src/features/printfilm-studio/CanvasProjectTeams.tsx')
    const {createElement:h,act}=await import('react'),{createRoot}=await import('react-dom/client'),{MemoryRouter}=await import('react-router-dom')
    root=createRoot(document.getElementById('root'))
    const settle=()=>act(async()=>{await new Promise(r=>setTimeout(r,360))})
    const mount=async(Component,props={})=>{await act(async()=>root.render(h(I18nProvider,null,h(MemoryRouter,null,h(Component,props)))));await settle()}
    const click=async(el)=>{assert.ok(el,document.body.textContent+JSON.stringify([...document.querySelectorAll("button")].map(b=>b.getAttribute("aria-label"))));await act(async()=>el.dispatchEvent(new MouseEvent('click',{bubbles:true})));await settle()}
    await mount(Projects,{workflow:'canvas'})
    assert.ok(document.querySelector('section[aria-label="我的项目"]'))
    assert.equal(document.querySelectorAll('.pf-shared-project-card').length,2)
    const joined=[...document.querySelectorAll('.pf-shared-project-card')].find(el=>el.textContent.includes('参与的画布'))
    assert.equal(!!joined.querySelector('.pf-shared-project-menu'),false)
    assert.equal(!!joined.querySelector('input[type=checkbox]'),false)
    await click([...document.querySelectorAll('button')].find(el=>el.textContent==='我参与的'))
    assert.equal(document.querySelectorAll('.pf-shared-project-card').length,1)
    assert.equal(calls.filter(url=>url.pathname==='/api/drama/projects').at(-1).searchParams.get('relation'),'joined')
    await mount(Assets)
    assert.equal(document.querySelectorAll('.pf-digital-library .pf-library-card').length,8)
    assert.equal(calls.filter(url=>url.pathname==='/api/drama/library-assets').at(-1).searchParams.get('page_size'),'8')
    await click(document.querySelector('button[aria-label="下一页"],button[aria-label="Next page"]'))
    assert.equal(document.querySelectorAll('.pf-digital-library .pf-library-card').length,1)
    await mount(Teams)
    assert.equal(document.querySelectorAll('.pf-project-teams-grid article').length,2)
    assert.ok(document.body.textContent.includes('管理成员与邀请'))
    assert.ok(document.body.textContent.includes('查看项目成员'))
    assert.equal(calls.some(url=>url.pathname.startsWith('/api/teams')),false)
  } finally {
    if(root){const {act}=await import('react');await act(async()=>root.unmount())}
    await server?.close();dom.window.close()
    for(const [key,descriptor]of old){if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key]}
  }
})
