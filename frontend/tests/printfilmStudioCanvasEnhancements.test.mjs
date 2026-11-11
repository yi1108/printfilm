import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

// Mount the actual workspace/menu/React Flow, with deterministic DOM measurements.
// All HTTP is mocked: this test never reads or writes a real user's project.
test('canvas references, candidate versions, composition export and edge cutting persist together', async () => {
  const dom = new JSDOM('<style>.react-flow__pane{z-index:1}</style><div id="root"></div>', { url: 'http://localhost/drama/projects/361/printfilm-studio', pretendToBeVisual: true })
  const previous = new Map()
  const install = (name, value) => { previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name)); Object.defineProperty(globalThis, name, { configurable: true, writable: true, value }) }
  for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'SVGElement', 'Node', 'Event', 'MouseEvent', 'DOMException', 'localStorage', 'sessionStorage']) install(name, dom.window[name])
  install('getComputedStyle', dom.window.getComputedStyle.bind(dom.window))
  install('requestAnimationFrame', dom.window.requestAnimationFrame.bind(dom.window))
  install('cancelAnimationFrame', dom.window.cancelAnimationFrame.bind(dom.window))
  install('IS_REACT_ACT_ENVIRONMENT', true)
  install('ResizeObserver', class {
    constructor(callback) { this.callback = callback; this.targets = new Set() }
    observe(target) { this.targets.add(target); queueMicrotask(() => { if (this.targets.has(target)) this.callback([{ target, contentRect: target.getBoundingClientRect() }]) }) }
    unobserve(target) { this.targets.delete(target) }
    disconnect() { this.targets.clear() }
  })
  dom.window.DOMMatrixReadOnly = class { constructor(value) { this.m22 = Number(value?.match(/scale\(([^)]+)\)/)?.[1] || 1) } }
  for (const [name, axis] of [['offsetWidth', 'width'], ['offsetHeight', 'height'], ['clientWidth', 'width'], ['clientHeight', 'height']]) {
    Object.defineProperty(dom.window.HTMLElement.prototype, name, { configurable: true, get() {
      if (!this.classList.contains('react-flow__node')) return axis === 'width' ? 1100 : 884
      // A skeleton explicitly given height:0 has zero layout height, even if its
      // children overflow. Do not mask React Flow's initial measurement deadlock.
      const explicit = this.querySelector('.pf-skel')?.style[axis]
      return explicit ? parseFloat(explicit) : axis === 'width' ? 320 : 200
    } })
  }
  dom.window.HTMLElement.prototype.getBoundingClientRect = function () {
    const [left, top] = this.getAttribute('aria-label') === '添加节点' ? [468, 830] : [0, 0]
    return { x: left, y: top, left, top, width: this.offsetWidth, height: this.offsetHeight, right: left + this.offsetWidth, bottom: top + this.offsetHeight }
  }
  dom.window.Range.prototype.getClientRects = () => []
  dom.window.Range.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 })
  dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
  localStorage.setItem('token', 'unit-test-token')
  const saves = [], workflowQuotes = [], exports = []
  let taskListRequests=0
  let writingStream, writingSignal, writingStops = 0
  let holdNextSave = false, finishHeldSave, generationRequests = 0, activeWorkflow = false, membershipAllowed = true
  let stored = { version: 1, document: { toonflowCanvas: true, version: 1, nodes: [
      {id:'image',type:'image',position:{x:0,y:0},data:{label:'角色',mediaUrl:'/image-new.png',mediaType:'image',prompt:'当前要求',mediaHistory:[{mediaUrl:'/image-old.png',mediaType:'image',prompt:'历史要求',savedAt:'2026-11-01'}]}},
      {id:'v1',type:'video',position:{x:400,y:0},data:{label:'镜头甲',mediaUrl:'/v1.mp4',mediaType:'video',status:'completed',prompt:'视频要求',referenceNodeIds:['image']}},
      {id:'v2',type:'video',position:{x:400,y:300},data:{label:'镜头乙',mediaUrl:'/v2.mp4',mediaType:'video',status:'completed'}},
      {id:'out',type:'compose',position:{x:800,y:0},data:{label:'编排导出'}}
    ],edges:[{id:'ref',source:'image',target:'v1'},{id:'clip1',source:'v1',target:'out'},{id:'clip2',source:'v2',target:'out'}],viewport:{x:0,y:0,zoom:1} } }
  install('fetch', async (input, init) => {
    const path = new URL(String(input), dom.window.location.origin).pathname
    if(path==='/api/tasks') taskListRequests++
    let data
    if (path === '/api/drama/projects/361') data = { id: 361, user_id: 1, team_id: null, title: '测试项目', script: '' }
    else if (path === '/api/printfilm-studio/projects/361/info') data = { id: 361, title: '测试项目', is_owner: true }
    else if (path.endsWith('/canvas') && init?.method === 'PUT') { if (holdNextSave) { holdNextSave = false; await new Promise(resolve => { finishHeldSave = resolve }) }; saves.push(JSON.parse(init.body)); stored = { document: saves.at(-1).document, version: stored.version + 1 }; data = stored }
    else if (path.endsWith('/canvas')) data = stored
    else if (path.endsWith('/workflow/quote')) { const body = JSON.parse(init.body); workflowQuotes.push(body); data = {runId:'mock-quote',total:0,settings:body.settings,items:body.target_ids.map(id=>({input:{id,label:id,kind:'text'},yuan:0}))} }
    else if (path.endsWith('/workflow')) { if (!membershipAllowed) return Response.json({ detail: '项目成员已移除' }, { status: 404 }); data = { ...stored, run: activeWorkflow ? { id: 'active-workflow', status: 'running', completed: 0, count: 1 } : null } }
    else if (path.endsWith('/agent/sessions')) data = init?.method === 'POST' ? { id: 'writing-test-session' } : { sessions: [] }
    else if (path.endsWith('/agent/config')) data = { models: [{ id: 'writer-test', label: '测试文字模型' }], tools: ['read_canvas', 'add_canvas_node'] }
    else if (path.endsWith('/agent/sessions/writing-test-session')) data = { id: 'writing-test-session' }
    else if (path.endsWith('/agent/sessions/writing-test-session/stop')) { writingStops++; data = {} }
    else if (path.endsWith('/agent/sessions/writing-test-session/stream')) {
      writingSignal = init.signal
      return new Response(new ReadableStream({ start(controller) { writingStream = controller; init.signal.addEventListener('abort', () => controller.error(new DOMException('Stopped', 'AbortError')), { once: true }) } }))
    }
    else if (path.endsWith('/canvas/assets')) data = { assets: Array.from({ length: 55 }, (_, index) => ({ id: index + 1, name: `分页素材 ${index + 1}`, type: 'image', url: 'data:image/png;base64,iVBORw0KGgo=' })) }
    else if (path.includes('media-models')) data = { image_models: [], video_models: [], defaults: {} }
    else if (path.includes('wallet')) data = { balance_yuan: 0 }
    else if (path.endsWith('/import')) data = { id: 1, name: '分页素材 1', type: 'image', url: 'data:image/png;base64,iVBORw0KGgo=' }
    else if (path.endsWith('/media/compose')) {exports.push(JSON.parse(init.body));data={assets:[{id:100,url:'/joined.mp4',name:'合成.mp4',type:'video'}]}}
    else if (path.endsWith('/estimate')) data={estimate_yuan:1}
    else if (path.endsWith('/image/estimate')) data = { estimate_yuan: 0.1 }
    else if (path.endsWith('/generations')) { generationRequests++; data = { status: 'queued', task_id: 'unit-generation' } }
    else if (path.includes('tasks')) data = { items: [] }
    else throw new Error(`Unexpected test request: ${path}`)
    return Response.json(data)
  })
  let server, root
  try {
    server = await createServer({ configFile: false, cacheDir: '.tmp/vite-enhancements-tests', optimizeDeps: { noDiscovery: true, include: [] }, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
    const { default: Workspace } = await server.ssrLoadModule('/src/features/printfilm-studio/PrintfilmStudioPage.tsx')
    const { createElement: h, act, StrictMode } = await import('react')
    const { createRoot } = await import('react-dom/client')
    const { MemoryRouter, Routes, Route } = await import('react-router-dom')
    root = createRoot(document.getElementById('root'))
    const settle = async (ms = 40) => { await act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) }) }
    const click = async (element) => {
      assert.ok(element, 'expected clickable element')
      await act(async () => { for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) { const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: element.classList.contains("react-flow__pane") ? 1000 : 0, clientY: element.classList.contains("react-flow__pane") ? 800 : 0, view: window }); Object.defineProperty(event, 'isPrimary', { value: true }); Object.defineProperty(event, 'pointerId', { value: 1 }); element.dispatchEvent(event) } })
      await settle()
    }
    const mount = async () => { await act(async () => { root.render(h(StrictMode, null, h(MemoryRouter, { initialEntries: ['/drama/projects/361/printfilm-studio'] }, h(Routes, null, h(Route, { path: '/drama/projects/:projectId/printfilm-studio', element: h(Workspace) }))))) }); await settle() }
    await mount()
    await settle()
    const byId=id=>document.querySelector(`.react-flow__node[data-id="${id}"]`)
    const button=text=>[...document.querySelectorAll('button')].find(item=>item.textContent===text)
    await click(byId('v1').querySelector('.pf-skel-title'))
    await click(document.querySelector('[aria-label="定位关联节点 角色"]'))
    assert.equal(byId('image').classList.contains('selected'),true,'reference chip selects the linked node')
    await click(byId('image').querySelector('.pf-variant-controls button:nth-last-child(2)'))
    assert.ok(document.querySelector('[aria-label="候选对比"]'))
    await click(button('滑杆'))
    const range=document.querySelector('.pf-compare-slider input')
    await act(async()=>{Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(range,'25');range.dispatchEvent(new Event('input',{bubbles:true}))})
    assert.equal(document.querySelectorAll('.pf-compare-stage img').length,2)
    await click(button('采用 B'))
    assert.equal(byId('image').querySelector('.pf-skel-media img').getAttribute('src'),'/image-old.png')
    await settle(1350)
    assert.equal(stored.document.nodes.find(node=>node.id==='image').data.mediaUrl,'/image-old.png')
    await click(byId('out').querySelector('.pf-skel-title'))
    await click(byId('out').querySelector('.pf-composition-node-footer button'))
    await click(document.querySelector('[aria-label="前移 镜头乙"]'))
    await click(button('合成并导出'))
    assert.deepEqual(exports,[{urls:['/v2.mp4','/v1.mp4']}])
    assert.ok(document.querySelector('.pf-composition-result video'))
    await click(document.querySelector('[aria-label="关闭编排"]'))
    await settle(1350)
    assert.equal(stored.document.nodes.find(node=>node.id==='out').data.mediaUrl,'/joined.mp4')
    const edge=document.querySelector('[data-id="ref"].react-flow__edge')
    assert.ok(edge)
    await click(edge)
    await click(document.querySelector('[aria-label="剪断连线"]'))
    await settle(1350)
    assert.ok(!stored.document.edges.some(edge=>edge.id==='ref'))
    assert.deepEqual(stored.document.nodes.find(node=>node.id==='v1').data.referenceNodeIds,[])
    await click(document.querySelector('[aria-label="撤销"]'))
    assert.ok(document.querySelector('[data-id="ref"].react-flow__edge'),'edge cut participates in undo')
    await click(document.querySelector('[aria-label="添加节点"]'))
    await click([...document.querySelectorAll('.pf-add-item')].find(button=>button.querySelector('b')?.textContent==='编排导出'))
    assert.equal(document.querySelectorAll('.react-flow__node-compose').length,2)
  } finally {
    if (root) { const { act } = await import('react'); await act(async () => root.unmount()) }
    await server?.close()
    dom.window.close()
    for (const [name, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name] }
  }
})

