import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

test('topbar actions, model defaults, history selection and image draft persistence', async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const previous = new Map()
  const install = (key, value) => { previous.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, { configurable: true, writable: true, value }) }
  for (const key of ['window','document','navigator','HTMLElement','Node','Event','MouseEvent','KeyboardEvent','localStorage']) install(key, dom.window[key])
  install('IS_REACT_ACT_ENVIRONMENT', true)
  dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true }
  dom.window.HTMLDialogElement.prototype.close = function () { this.open = false }
  const requests = [], picked = [], actions = []
  const run = { id: 42, kind: 'image', status: 'succeeded', prompt: '测试图片', urls: ['/media/test.png'], created_at: '2026-11-06T08:00:00Z' }
  install('fetch', async url => {
    requests.push(String(url))
    if (String(url).includes('/tools/runs')) return Response.json({ items: [run,{...run,id:43,kind:'video',urls:['/media/video.mp4'],preview_url:'/media/poster.png'}], total: 2 })
    if (String(url).endsWith('/agent/config')) return Response.json({models:[{id:'writer-other',label:'其他写作模型'},{id:'writer-test',label:'写作模型'}],default_model:'writer-test'})
    return Response.json({image_models:[{id:'image-test',label:'图片模型'}],video_models:[{id:'video-old',label:'失效模型',available:false},{id:'video-test',label:'视频模型'}],defaults:{image_model:'image-test',video_model:'video-test'}})
  })
  let server, root
  try {
    server = await createServer({configFile:false,root:fileURLToPath(new URL('..',import.meta.url)),plugins:[react()],server:{middlewareMode:true,hmr:false,ws:false,watch:null},logLevel:'error'})
    const {createElement:h,act} = await import('react')
    const {createRoot} = await import('react-dom/client')
    root = createRoot(document.getElementById('root'))
    const click = async el => { assert.ok(el); await act(async()=>el.dispatchEvent(new MouseEvent('click',{bubbles:true}))) }
    const textButton = text => [...document.querySelectorAll('button')].find(el=>el.textContent===text)
    const {WorkspaceChrome} = await server.ssrLoadModule('/src/features/printfilm-studio/WorkspaceChrome.tsx')
    await act(async()=>root.render(h(WorkspaceChrome,{title:'测试项目',status:'已保存',balance:'1.00',mode:'canvas',dockWidth:0,onMode:m=>actions.push(m),onAction:a=>actions.push(a)})))
    await click(textButton('故事板')); await click(textButton('默认模型')); await click(textButton('分享'))
    await click(document.querySelector('[aria-label="更多菜单"]')); await click(textButton('画布设置'))
    assert.deepEqual(actions,['storyboard','defaults','share','settings'])
    assert.equal(document.querySelector('section[aria-label="更多菜单"]'),null)
    const {DefaultModelPanel} = await server.ssrLoadModule('/src/features/printfilm-studio/WorkspacePanels.tsx')
    await act(async()=>root.render(h(DefaultModelPanel,{onClose:()=>{}})))
    assert.match(document.querySelector('button[aria-label="视频默认模型"]').textContent,/视频模型/)
    assert.match(document.querySelector('button[aria-label="文本默认模型"]').textContent,/写作模型/)
    assert.match(document.querySelector('button[aria-label="图片默认模型"]').textContent,/图片模型/)
    assert.equal(document.body.textContent.includes('跟随平台默认'),false)
    await click(document.querySelector('button[aria-label="图片默认模型"]'))
    assert.ok(document.querySelector('dialog .pf-model-options'), 'menu stays inside the native dialog top layer')
    await click(document.querySelector('.pf-model-options [role="menuitemradio"]'))
    const prefs = await server.ssrLoadModule('/src/features/printfilm-studio/workspacePreferences.ts')
    assert.equal(prefs.defaultNodeData('image').modelId,'image-test')
    assert.equal(prefs.defaultNodeData('videoGeneration').modelId,'video-test')
    assert.equal(prefs.defaultNodeData('text').writingModel,'writer-test')
    await click(document.querySelector('button[aria-label="文本默认模型"]'))
    await click([...document.querySelectorAll('.pf-model-options button')].find(el=>el.textContent.includes('其他写作模型')))
    await act(async()=>root.render(h('div')))
    await act(async()=>root.render(h(DefaultModelPanel,{onClose:()=>{}})))
    assert.match(document.querySelector('button[aria-label="文本默认模型"]').textContent,/其他写作模型/)
    const {HistoryPicker} = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/HistoryPicker.tsx')
    await act(async()=>root.render(h(HistoryPicker,{onPick:r=>picked.push(r.id),onClose:()=>{}})))
    await click(document.querySelector('[aria-label="播放视频"]'))
    assert.equal(new URL(document.querySelector('video').src).pathname,'/media/video.mp4')
    assert.equal(document.querySelector('video').controls,true)
    await act(async()=>{const input=document.querySelector('[aria-label="搜索提示词"]');Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(input,'桃园 100%');input.dispatchEvent(new Event('input',{bubbles:true}))})
    await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})))
    assert.ok(requests.some(url=>new URL(url,'http://localhost').searchParams.get('q')==='桃园 100%'))
    await click(document.querySelector('[aria-label="选择生成记录"]')); await click(textButton('加入项目（1）'))
    assert.deepEqual(picked,[42])
    const {nodeDraft,normalizeImageDraft} = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/nodeDraft.ts')
    const scene={type:'image',height:1800,style:{width:240,height:1800},measured:{height:1800},data:{text:'旧剧本正文'.repeat(80),prompt:'酒馆全景，暖光，无人物'}}
    assert.equal(nodeDraft(scene),scene.data.prompt)
    const fixed=normalizeImageDraft(scene)
    assert.equal(fixed.height,280);assert.equal(fixed.style.width,240);assert.equal(fixed.measured,undefined)
    assert.equal(fixed.data.text,scene.data.text);assert.equal(nodeDraft(fixed),scene.data.prompt)
    assert.equal(nodeDraft({...scene,data:{...scene.data,prompt:''}}),'')
    for(const data of [{...scene.data,userResized:true},{...scene.data,mediaUrl:'/image.png'}]) { const node={...scene,data}; assert.equal(normalizeImageDraft(node),node) }
  } finally {
    if(root){const {act}=await import('react');await act(async()=>root.unmount())}
    await server?.close();dom.window.close()
    for(const [key,value] of previous){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key]}
  }
})
