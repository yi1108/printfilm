import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

// Mount the actual workspace/menu/React Flow, with deterministic DOM measurements.
// All HTTP is mocked: this test never reads or writes a real user's project.
test('workspace creates, drags and autosaves nodes while a workflow is running', async () => {
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
  const saves = [], workflowQuotes = []
  let forceSaveConflict = true, saveConflicts = 0
  let taskListRequests=0
  let writingStream, writingSignal, writingStops = 0
  let holdNextSave = false, finishHeldSave, generationRequests = 0, activeWorkflow = true, membershipAllowed = true
  let stored = { version: 1, document: { toonflowCanvas: true, version: 1, nodes: [], edges: [], viewport: { x: 816, y: -635, zoom: .5 } } }
  install('fetch', async (input, init) => {
    const path = new URL(String(input), dom.window.location.origin).pathname
    if(path==='/api/tasks') taskListRequests++
    let data
    if (path === '/api/drama/projects/361') data = { id: 361, user_id: 1, team_id: null, title: '测试项目', script: '' }
    else if (path === '/api/printfilm-studio/projects/361/info') data = { id: 361, title: '测试项目', is_owner: true }
    else if (path.endsWith('/canvas') && init?.method === 'PUT') {
      if (holdNextSave) { holdNextSave = false; await new Promise(resolve => { finishHeldSave = resolve }) }
      const body = JSON.parse(init.body)
      if (forceSaveConflict) {
        forceSaveConflict = false
        stored = { version: stored.version + 1, document: { ...stored.document, backgroundUpdate: 'preserved' } }
      }
      if (body.expected_version !== stored.version) { saveConflicts++; return Response.json({ detail: '画布版本冲突' }, { status: 409 }) }
      saves.push(body); stored = { document: body.document, version: stored.version + 1 }; data = stored
    }
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
    else if (path.endsWith('/canvas/assets')) data = { assets: Array.from({ length: 55 }, (_, index) => ({ id: index + 1, name: `分页素材 ${index + 1}`, type: 'image', url: `/media/fixture-asset-${index + 1}.png` })) }
    else if (path.includes('media-models')) data = { image_models: [], video_models: [], defaults: {} }
    else if (path.includes('wallet')) data = { balance_yuan: 0 }
    else if (path.endsWith('/import')) data = { id: 1, name: '分页素材 1', type: 'image', url: '/media/fixture-asset-1.png' }
    else if (path.endsWith('/image/estimate')) data = { estimate_yuan: 0.1 }
    else if (path.endsWith('/generations')) { generationRequests++; data = { status: 'queued', task_id: 'unit-generation' } }
    else if (path.includes('tasks')) data = { items: [] }
    else throw new Error(`Unexpected test request: ${path}`)
    return Response.json(data)
  })
  let server, root
  try {
    server = await createServer({ configFile: false, cacheDir: '.tmp/vite-workspace-tests', optimizeDeps: { noDiscovery: true, include: [] }, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
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
    const add = document.querySelector('[aria-label="添加节点"]')
    assert.equal(add?.disabled, false, document.body.textContent)
    assert.equal(Boolean(document.querySelector('.pf-workspace-access')), false, '后台生成不能显示取得编辑权提示')
    await click(add)
    assert.ok(document.querySelector('.pf-add-menu'))
    await click(add)
    assert.equal(Boolean(document.querySelector('.pf-add-menu')), false, 'clicking the add button twice closes its menu')
    for (const type of ['文本', '图片', '视频', '音频', '图片', '视频', '音频']) {
      await click(add)
      await click([...document.querySelectorAll('.pf-add-item')].find(button => button.querySelector('b')?.textContent === type))
      const created = [...document.querySelectorAll('.react-flow__node')].at(-1)
      assert.ok(created, `${type} must be inserted`)
      assert.equal(created.style.visibility, 'visible', `${type} must be measured and visible`)
      assert.ok(created.textContent.includes(`新${type}`))
      assert.equal(created.classList.contains('selected'), true, `${type} must be visibly selected after insertion`)
    }
    await click(document.querySelector('[aria-label="撤销"]'))
    assert.equal(document.querySelectorAll('.react-flow__node').length, 6, 'node insertion participates in undo')
    await click(document.querySelector('[aria-label="重做"]'))
    assert.equal(document.querySelectorAll('.react-flow__node').length, 7)
    // A menu moved away from the screen edge must preserve the clicked canvas point.
    await act(async () => { document.querySelector('.react-flow__pane').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 800, clientY: 600, button: 2, view: window })) })
    await click([...document.querySelectorAll('.pf-add-item')].find(button => button.querySelector('b')?.textContent === '文本'))
    const last = [...document.querySelectorAll('.react-flow__node')].at(-1)
    assert.ok(last.classList.contains('selected'))
    await settle(1350)
    assert.equal(saves.at(-1)?.document.nodes.length, 8)
    assert.equal(saveConflicts, 1, 'stale save retries automatically')
    assert.equal(stored.document.backgroundUpdate, 'preserved', 'retry retains remote changes')
    assert.ok(saves.at(-1).document.nodes.every(node => Number.isFinite(node.position.x) && Number.isFinite(node.position.y)))
    stored = { ...stored, document: { ...stored.document, edges: [{ id: 'test-reference', source: stored.document.nodes[0].id, target: stored.document.nodes[1].id }] } }
    stored.document.nodes[4].data.prompt = '自动保存期间提交生成测试'
    stored.document.nodes[2].data.prompt = '保留已有分镜提示词'
    stored.document.nodes[2].data.promptNodeId = stored.document.nodes[0].id
    stored.document.nodes[1].data.mediaUrl = 'data:image/png;base64,iVBORw0KGgo='
    await act(async () => root.unmount())
    root = createRoot(document.getElementById('root'))
    await mount()
    assert.equal(document.querySelectorAll('.react-flow__node').length, 8, 'saved nodes survive a workspace remount')
    assert.ok([...document.querySelectorAll('.react-flow__node')].every(node => node.style.visibility === 'visible'))
    const emptyVideo = document.querySelector(`[data-id="${stored.document.nodes[2].id}"]`)
    await click(emptyVideo.querySelector('.pf-story-result-placeholder'))
    assert.ok(emptyVideo.querySelector('.pf-composer-card'), 'single click opens the paired empty video composer')
    assert.ok(emptyVideo.querySelector('.pf-composer-card').textContent.includes('保留已有分镜提示词'))
    assert.ok(emptyVideo.querySelector('.pf-skel-slot.is-top'), 'video toolbar is available before generation')
    await click(emptyVideo.querySelector('[aria-label="视频参数"]'))
    await click([...document.querySelectorAll('[role=radio]')].find(item => item.textContent === '1:1'))
    await click(emptyVideo.querySelector('.pf-story-result-placeholder'))
    assert.ok(emptyVideo.querySelector('[aria-label="视频参数"]').textContent.includes('1:1'), 'clicking the same node preserves composer parameters')
    assert.equal(generationRequests, 0, 'opening the composer never submits generation')
    await click(document.querySelector('.react-flow__pane'))
    const completedImage = document.querySelector(`[data-id="${stored.document.nodes[1].id}"]`)
    await click(completedImage)
    assert.ok(completedImage.querySelector('.pf-composer-card'), 'completed media opens its generation editor')
    await click(completedImage.querySelector('[aria-label="节点操作"]'))
    assert.equal(document.querySelectorAll('.pf-context-menu').length,1,'ellipsis opens only the current node menu')
    assert.ok(completedImage.querySelector('.pf-composer-card'),'ellipsis keeps prompt editor open')
    assert.ok(document.querySelector('.pf-context-menu').textContent.includes('重命名'))
    await click(document.querySelector('.react-flow__pane'))
    const oldBounds=emptyVideo.getBoundingClientRect
    emptyVideo.getBoundingClientRect=()=>({x:700,y:500,left:700,top:500,width:200,height:150,right:900,bottom:650})
    await act(async()=>document.querySelector('.react-flow__pane').dispatchEvent(new MouseEvent('click',{bubbles:true,view:window,clientX:915,clientY:550})))
    await settle()
    assert.ok(emptyVideo.querySelector('.pf-composer-card'),'clicking 15px outside a node opens its editor')
    assert.equal(document.querySelectorAll('.pf-composer-card').length,1)
    emptyVideo.getBoundingClientRect=oldBounds

    await click(document.querySelector('.react-flow__pane'))
    const key = async (key, options = {}, target = document.body, type = 'keydown') => {
      const event = new dom.window.KeyboardEvent(type, { key, bubbles: true, cancelable: true, ...options })
      await act(async () => target.dispatchEvent(event))
      await settle()
      return event
    }
    const count = () => document.querySelectorAll('.react-flow__node').length
    const edge = document.querySelector('.react-flow__edge')
    assert.ok(edge, 'saved reference renders as an edge')
    await click(edge)
    assert.ok(edge.classList.contains('selected'), 'selecting an edge enables its static highlight')
    assert.ok(document.querySelector('[aria-label="剪断连线"]'), 'selected connection exposes its cut control')
    assert.equal(edge.querySelector('.pf-connection-flow'), null, 'selected edges do not add animated duplicate paths')
    await click(document.querySelector('.react-flow__pane'))
    assert.equal(Boolean(document.querySelector('[aria-label="剪断连线"]')), false, 'deselection hides the cut control')
    await act(async () => edge.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, button: 2, clientX: 500, clientY: 350, view: window })))
    await settle()
    await click([...document.querySelectorAll('.pf-context-menu button')].find(button => button.textContent.includes('断开连线')))
    assert.equal(document.querySelectorAll('.react-flow__edge').length, 0)
    assert.equal(count(), 8, 'disconnecting an edge preserves its nodes')
    await key('z', { ctrlKey: true })
    assert.equal(document.querySelectorAll('.react-flow__edge').length, 1, 'disconnect supports undo')
    await key('Tab')
    assert.ok(document.querySelector('.pf-add-menu'), 'Tab opens the actual add menu')
    assert.ok(document.querySelector('.pf-add-menu').contains(document.activeElement), 'menu takes keyboard focus')
    await key('Escape', {}, document.activeElement)
    assert.equal(Boolean(document.querySelector('.pf-add-menu')), false)

    await key(' ')
    assert.equal(document.querySelector('.pf-flow-area').dataset.tool, 'hand', 'Space temporarily pans')
    await key(' ', {}, document.body, 'keyup')
    assert.equal(document.querySelector('.pf-flow-area').dataset.tool, 'select')
    await key(' ')
    await act(async () => window.dispatchEvent(new Event('blur')))
    assert.equal(document.querySelector('.pf-flow-area').dataset.tool, 'select', 'window blur releases panning')

    await click(document.querySelector('[aria-label="平移工具"]'))
    const viewportBeforePan = document.querySelector('.react-flow__viewport').style.transform
    const nodesBeforePan = [...document.querySelectorAll('.react-flow__node')].map(node => node.style.transform)
    for (const [type, target, x, y, buttons] of [
      ['mousedown', document.querySelector('.react-flow__pane'), 800, 600, 1],
      ['mousemove', window, 860, 660, 1],
      ['mouseup', window, 860, 660, 0],
    ]) {
      await act(async () => target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window, button: 0, buttons, clientX: x, clientY: y })))
      await settle()
    }
    assert.notEqual(document.querySelector('.react-flow__viewport').style.transform, viewportBeforePan, 'left drag pans in the hand tool')
    assert.deepEqual([...document.querySelectorAll('.react-flow__node')].map(node => node.style.transform), nodesBeforePan, 'canvas panning never moves individual nodes')
    assert.equal(Boolean(document.querySelector('.react-flow__selection')), false, 'hand tool does not box-select')

    await click(document.querySelector('[aria-label="选择工具"]'))
    const selectionPanBefore=document.querySelector('.react-flow__viewport').style.transform
    for(const [type,target,x,y,buttons] of [['mousedown',document.querySelector('.react-flow__pane'),800,600,1],['mousemove',window,825,625,1],['mouseup',window,825,625,0]]) {
      await act(async()=>target.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,view:window,button:0,buttons,clientX:x,clientY:y})));await settle()
    }
    assert.notEqual(document.querySelector('.react-flow__viewport').style.transform,selectionPanBefore,'select tool also pans on plain left drag')
    const pane = document.querySelector('.react-flow__pane')
    const pointer = async (type,x,y) => {
      const event = new MouseEvent(type,{bubbles:true,cancelable:true,view:window,button:0,buttons:type==='pointerup'?0:1,clientX:x,clientY:y,shiftKey:true})
      Object.defineProperty(event,'isPrimary',{value:true})
      Object.defineProperty(event,'pointerId',{value:1})
      await act(async()=>pane.dispatchEvent(event)); await settle()
    }
    const beforeBox = document.querySelector('.react-flow__viewport').style.transform
    await act(async () => window.dispatchEvent(new Event('blur')))
    await key('Shift',{shiftKey:true})
    await pointer('pointerdown',100,100)
    await pointer('pointermove',850,750)
    assert.ok(document.querySelector('.react-flow__selection'), 'left drag creates a visible selection rectangle')
    assert.equal(document.querySelector('.react-flow__viewport').style.transform,beforeBox,'selection does not pan the canvas')
    await pointer('pointerup',850,750)
    await key('Shift',{},document.body,'keyup')
    await key('a', { ctrlKey: true })
    assert.equal(document.querySelectorAll('.react-flow__node.selected').length, 8)
    assert.equal(!!document.querySelector('[aria-label="批量节点操作"]'),false)
    assert.equal(workflowQuotes.length,0,'selection does not launch a batch workflow')
    await key('g', { ctrlKey: true })
    assert.equal(count(), 9, 'shortcut groups the selected nodes')
    await key('c', { ctrlKey: true })
    await key('v', { ctrlKey: true })
    assert.equal(count(), 18, 'copy and paste include all group descendants')
    await key('z', { ctrlKey: true })
    assert.equal(count(), 9)
    await key('z', { ctrlKey: true, shiftKey: true })
    assert.equal(count(), 18)
    await key('Delete')
    assert.equal(count(), 9, 'deleting copied group also removes descendants')
    await key('a', { ctrlKey: true })
    await key('g', { ctrlKey: true, shiftKey: true })
    assert.equal(count(), 8, 'ungroup retains all original content nodes')

    // Right clicking an unselected node changes the action target, preserving its siblings.
    await key('Escape')
    const rightTarget = document.querySelector('.react-flow__node')
    await act(async () => rightTarget.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, button: 2, clientX: 500, clientY: 350, view: window })))
    await settle()
    assert.equal(document.querySelectorAll('.react-flow__node.selected').length, 1)
    await click([...document.querySelectorAll('.pf-context-menu button')].find(button => button.querySelector('.pf-context-label')?.textContent.startsWith('删除')))
    assert.equal(count(), 7)
    await key('z', { ctrlKey: true })
    assert.equal(count(), 8)

    await key('Escape')
    const dragTarget = document.querySelector('.react-flow__node')
    const originalTransform = dragTarget.style.transform
    for (const [type, target, x, y, buttons] of [
      ['mousedown', dragTarget.querySelector('.pf-skel-title'), 450, 300, 1],
      ['mousemove', window, 510, 350, 1],
      ['mousemove', window, 560, 390, 1],
      ['mouseup', window, 560, 390, 0],
    ]) {
      await act(async () => target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window, button: 0, buttons, clientX: x, clientY: y, altKey: true })))
      await settle()
    }
    assert.equal(count(), 9, 'Alt dragging creates one copy through React Flow')
    assert.equal(dragTarget.style.transform, originalTransform, 'Alt dragging leaves the original in place')
    await key('z', { ctrlKey: true })
    assert.equal(count(), 8, 'one undo removes the entire drag copy')

    await click(document.querySelector('.react-flow__pane'))
    await click(document.querySelector('[aria-label="添加节点"]'))
    await click([...document.querySelectorAll('.pf-add-item')].find(button => button.querySelector('b')?.textContent === '分类框'))
    assert.equal(document.querySelectorAll('.react-flow__node-group').length, 1, 'catalog creates an empty category frame')
    assert.equal(count(), 9)
    await settle(1350)
    const category = saves.at(-1).document.nodes.find(node => node.type === 'group')
    assert.deepEqual(category.data.children, [])
    assert.equal(category.style.width, 600)
    await key('z', { ctrlKey: true })
    assert.equal(count(), 8, 'category creation is a single undoable edit')

    const imageNode = document.querySelector('.pf-image-gallery').closest('.react-flow__node')
    await click(imageNode)
    const sourceId = imageNode.dataset.id
    const sourceImage = imageNode.querySelector('img').getAttribute('src')
    const beforeBranchEdges = document.querySelectorAll('.react-flow__edge').length
    await click([...imageNode.querySelectorAll('button')].find(button => button.textContent.includes('参考生成视频')))
    assert.equal(count(), 9, 'reference generation creates a draft node before submitting a paid task')
    assert.equal(document.querySelectorAll('.react-flow__edge').length, beforeBranchEdges + 1)
    assert.equal(imageNode.querySelector('img').getAttribute('src'), sourceImage, 'source media is preserved')
    assert.ok(document.querySelector('.react-flow__node-videoGeneration.selected .pf-skel-slot.is-bottom'), 'composer belongs to the new video node and toolbar clicks do not reselect the source')
    await settle(1350)
    const branch = saves.at(-1).document.nodes.find(node => node.type === 'videoGeneration' && node.data.editor === 'reference')
    assert.ok(branch)
    assert.equal(branch.data.ratio, '16:9', 'a new reference video defaults to landscape rather than inheriting the source image ratio')
    assert.ok(saves.at(-1).document.edges.some(edge => edge.source === sourceId && edge.target === branch.id))
    await click(document.querySelector('.react-flow__pane'))
    await key('z', { ctrlKey: true })
    assert.equal(count(), 8, 'one undo removes the reference draft and its connection together')
    assert.equal(document.querySelectorAll('.react-flow__edge').length, beforeBranchEdges)
    await click(document.querySelector('[aria-label="项目素材"]'))
    assert.equal(document.querySelectorAll('.pf-library-card').length, 24)
    const nextPage = () => [...document.querySelectorAll('.pf-library-pagination button')].find(button => button.textContent === '下一页')
    await click(nextPage())
    assert.equal(document.querySelectorAll('.pf-library-card').length, 24)
    assert.ok(document.querySelector('.pf-library-card').textContent.includes('分页素材 25'))
    await click(nextPage())
    assert.equal(document.querySelectorAll('.pf-library-card').length, 7)
    assert.equal(nextPage().disabled, true, 'last page cannot overflow')
    await click(document.querySelector('[aria-label="关闭素材库"]'))

    // Search and text editing own keyboard events; they must not alter the graph.
    await key('f', { ctrlKey: true })
    const searchInput = document.querySelector('.pf-canvas-search input')
    assert.ok(searchInput, 'search shortcut opens node search')
    const inInput = await key('a', { ctrlKey: true }, searchInput)
    assert.equal(inInput.defaultPrevented, false, 'text selection remains native inside inputs')
    await key('Delete', {}, searchInput)
    await key('Tab', {}, searchInput)
    assert.equal(count(), 8)
    assert.equal(Boolean(document.querySelector('.pf-add-menu')), false)
    await key('Escape', {}, searchInput)

    await settle(1350)
    assert.equal(saves.at(-1).document.nodes.length, 8)
    await click(document.querySelector('[aria-label="打开 Printfilm Agent"]'))
    await click(document.querySelector('[title="引用节点与素材"]'))
    const agentInput = document.querySelector('[aria-label="Agent 消息"]')
    assert.equal(document.activeElement, agentInput)
    const options = document.querySelectorAll('.pf-agent-mention-options [role="option"]')
    assert.equal(options.length, 8)
    await key('ArrowDown', {}, agentInput)
    const referenced = options[1].querySelector('b').textContent
    assert.equal(options[1].dataset.active, 'true')
    await key('Enter', {}, agentInput)
    assert.equal(Boolean(document.querySelector('.pf-agent-mention-menu')), false, 'Enter inserts a reference instead of sending')
    assert.ok(agentInput.value.includes(referenced))
    assert.equal(document.querySelectorAll('[aria-label="已选参考素材"] .pf-reference-remove').length, 1)
    await click(document.querySelector('[title="引用节点与素材"]'))
    await key('ArrowDown', {}, agentInput)
    await key('Enter', {}, agentInput)
    assert.equal(document.querySelectorAll('[aria-label="已选参考素材"] .pf-reference-remove').length, 1, 'reselecting a reference never removes or duplicates it')
    await click(document.querySelector('[title="引用节点与素材"]'))
    await key('Escape', {}, agentInput)
    assert.equal(Boolean(document.querySelector('.pf-agent-mention-menu')), false)
    await key('Delete', {}, agentInput)
    assert.equal(count(), 8, 'Agent keyboard events do not delete canvas nodes')
    await click(document.querySelector('[title="收起 Agent"]'))
    // Format the rendered text directly, then save it as Markdown with one-step canvas undo.
    const textBody = document.querySelector('.pf-skel-text')
    await act(async () => textBody.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, view: window })))
    for (let attempt = 0; attempt < 40 && !document.querySelector('[aria-label="文本正文"]'); attempt++) await settle(50)
    assert.ok(document.querySelector('[aria-label="编辑文本节点"]'))
    const richText = document.querySelector('[aria-label="文本正文"]')
    assert.equal(richText.getAttribute('contenteditable'), 'true')
    assert.equal(Boolean(document.querySelector('.pf-text-editor textarea')), false)
    await act(async () => {
      richText.focus()
      const paste = new Event('paste', { bubbles: true, cancelable: true })
      Object.defineProperty(paste, 'clipboardData', { value: { getData: type => type === 'text/plain' ? '文字' : '', files: [] } })
      richText.dispatchEvent(paste)
    })
    await settle()
    await key('a', { ctrlKey: true }, richText)
    await click(document.querySelector('[aria-label="加粗"]'))
    assert.equal(richText.querySelector('strong').textContent, '文字')
    await key('s', { ctrlKey: true }, richText)
    assert.equal(Boolean(document.querySelector('.pf-text-editor')), false, 'Ctrl+S saves the editor draft')
    assert.equal(document.querySelector('.pf-skel-text strong').textContent, '文字')
    await act(async () => document.querySelector('.pf-skel-text').dispatchEvent(new MouseEvent('dblclick', { bubbles: true, view: window })))
    await settle()
    assert.equal(document.querySelector('[aria-label="文本正文"] strong').textContent, '文字', 'saved Markdown reopens as rich text')
    await click(document.querySelector('[aria-label="二级标题"]'))
    await click(document.querySelector('[aria-label="关闭文本编辑器"]'))
    assert.equal(document.querySelector('.pf-skel-text h2').textContent, '文字', 'closing saves formatting')
    await key('z', { ctrlKey: true })
    assert.equal(Boolean(document.querySelector('.pf-skel-text h2')), false)
    await key('z', { ctrlKey: true })
    assert.equal(Boolean(document.querySelector('.pf-skel-text strong')), false, 'text changes use canvas undo')
    await settle(1350)
    const emptyImage = [...document.querySelectorAll('.react-flow__node-image')].find(node => node.querySelector('.pf-image-draft'))
    await click(emptyImage)
    assert.ok(emptyImage.querySelector('.pf-composer-card'), 'single click opens the empty image composer')
    assert.ok(emptyImage.querySelector('.pf-skel-slot.is-top'), 'image toolbar is available before generation')
    const refsBeforePick = document.querySelectorAll('.react-flow__edge').length
    await click([...emptyImage.querySelectorAll('button')].find(button => button.textContent.trim() === '参考图'))
    await click([...document.querySelectorAll('.pf-mention button')].find(button => button.textContent === '从素材库选择'))
    assert.ok(document.querySelector('.pf-library').textContent.includes('自动连线'))
    await click(document.querySelector('.pf-library-pick'))
    assert.equal(count(), 9, 'reference asset picker creates an input node')
    assert.equal(document.querySelectorAll('.react-flow__edge').length, refsBeforePick + 1, 'asset picker connects the new input to its target')
    assert.equal(Boolean(document.querySelector('.pf-library')), false)
    await click(document.querySelector('[aria-label="撤销"]'))
    assert.equal(count(), 8, 'asset import and reference connection undo together')
    assert.equal(document.querySelectorAll('.react-flow__edge').length, refsBeforePick)
    await click(emptyImage)
    assert.ok(emptyImage.querySelector('.pf-composer-card'), 'single click opens the empty image composer')
    assert.ok(emptyImage.querySelector('.pf-skel-slot.is-top'), 'image toolbar is available before generation')
    const ratioSelect = emptyImage.querySelector('[aria-label="比例"]')
    await click(ratioSelect)
    await click([...document.querySelectorAll('[role=menuitemradio]')].find((item) => item.textContent === '1:1 方形'))
    holdNextSave = true
    await key('s', { ctrlKey: true })
    assert.equal(typeof finishHeldSave, 'function', 'a canvas save is in flight')
    await click(emptyImage.querySelector('[aria-label="生成"]'))
    assert.equal(generationRequests, 0, 'generation waits for an in-flight autosave')
    assert.equal(document.querySelectorAll('.pf-node-generating').length, 1, 'only the submitting node displays its full-card loading state')
    assert.ok(!document.body.textContent.includes('请先完成画布保存并处理冲突'))
    stored = { version: stored.version + 1, document: { ...stored.document, nodes: stored.document.nodes.map((node, index) => index === 0 ? { ...node, data: { ...node.data, backgroundResult: '/generated.png' } } : node) } }
    await act(async () => finishHeldSave())
    await settle(120)
    assert.equal(generationRequests, 1, 'submission continues automatically after save completes')
    assert.equal(saveConflicts, 2, 'generation completing during PUT causes a safely retried conflict')
    assert.equal(stored.document.nodes[0].data.backgroundResult, '/generated.png')
    assert.ok(!document.body.textContent.includes('保存冲突'))
    assert.equal(document.querySelectorAll('.pf-node-generating').length, 1, 'queued node keeps loading state while other nodes remain usable')
    assert.equal(document.querySelector('.pf-studio-footer').hidden, true, 'generation never opens the task/debug drawer')
    assert.equal(taskListRequests,0,'closed task drawer never polls the global studio task list')
    await click(document.querySelector('.react-flow__pane'))
    await key('z', { ctrlKey: true })
    assert.equal(document.querySelectorAll('.pf-node-generating').length, 0)
    await settle(1350)
    const beforeOrganize = [...document.querySelectorAll('.react-flow__node')].map(node => [node.dataset.id, node.style.transform])
    await click(document.querySelector('[aria-label="整理画布"]'))
    assert.ok(document.querySelectorAll('.pf-group-frame.is-organized').length > 0, 'organize adds named category frames')
    assert.ok(count() > 8)
    assert.equal(Boolean(document.querySelector('[aria-label="正在整理画布"]')), false, 'unsupported motion completes without trapping the user')
    await settle(1350)
    assert.ok(saves.at(-1).document.nodes.some(node => node.data.autoLayoutGroup), 'the complete organization is persisted')
    const organizedCount = count()
    await key('z', { ctrlKey: true })
    assert.equal(count(), 8, 'one undo restores all nodes and removes generated frames')
    assert.deepEqual([...document.querySelectorAll('.react-flow__node')].map(node => [node.dataset.id, node.style.transform]), beforeOrganize)
    await key('z', { ctrlKey: true, shiftKey: true })
    assert.equal(count(), organizedCount, 'redo restores the whole organization')
    await key('z', { ctrlKey: true })
    await settle(1350)
    const videoTry = [...document.querySelectorAll('.pf-video-try button')].find((item) => item.textContent === '参考图生成视频')
    const targetVideoId = videoTry.closest('.react-flow__node').dataset.id
    await click(videoTry)
    assert.ok(document.querySelector('[aria-label="选择视频参考图片"]'))
    await click([...document.querySelectorAll('.pf-video-setup button')].find((item) => item.textContent === '新建图片节点'))
    assert.equal(count(), 9, 'video starter creates an image input node')
    await settle(1350)
    const inputNode = saves.at(-1).document.nodes.find((node) => node.data.label === '参考图片')
    assert.ok(saves.at(-1).document.edges.some((edge) => edge.source === inputNode.id && edge.target === targetVideoId))
    await click(document.querySelector('.react-flow__pane')); await key('z', { ctrlKey: true }); assert.equal(count(), 8)
    await click([...document.querySelectorAll('.pf-video-try button')].find((item) => item.textContent === '先写故事脚本'))
    assert.equal(count(), 9, 'video starter creates a connected script')
    assert.ok(document.querySelector('[aria-label="AI 写作要求"]'), 'script immediately opens inline writing controls')
    const writingNodeId = document.querySelector('.react-flow__node.selected').dataset.id
    await act(async () => { const input = document.querySelector('[aria-label="AI 写作要求"]'); input.textContent = '写一段镜头提示词'; input.dispatchEvent(new Event('input', { bubbles: true })) })
    await click(document.querySelector('[aria-label="开始 AI 写作"]'))
    assert.ok(writingStream, 'writing request started')
    await click(document.querySelector('.react-flow__pane'))
    assert.equal(document.querySelector('[aria-label="AI 写作要求"]'), null, 'clicking outside dismisses the composer')
    assert.equal(writingSignal.aborted, false, 'dismissal does not interrupt generation')
    assert.equal(writingStops, 0, 'dismissal never sends a stop request')
    await act(async () => { writingStream.enqueue(new TextEncoder().encode('{"type":"message_delta","content":"远景，军旗随风展开。"}\n{"type":"done"}\n')); writingStream.close() })
    await settle(1350)
    assert.match(saves.at(-1).document.nodes.find(node => node.id === writingNodeId).data.text, /远景，军旗随风展开。/, 'hidden composer writes its result into the original node and autosaves')
    await key('z', { ctrlKey: true }); assert.equal(count(), 9, 'undo generated text')
    await key('z', { ctrlKey: true }); assert.equal(count(), 8, 'undo input node creation')
    await settle(1350)
    // Storyboard edits operate on the same nodes and survive a view switch.
    await click([...document.querySelectorAll('.pf-view-tabs button')].find(button => button.textContent === '故事板'))
    await click(document.querySelector('.pf-board-section.is-text .pf-board-card'))
    await settle(100)
    assert.ok(document.querySelector('.pf-text-editor-embedded [aria-label="文本正文"]'), 'storyboard opens an embedded rich text editor')
    assert.equal(Boolean(document.querySelector('.pf-text-editor-backdrop')), false, 'editing stays inside the detail panel')
    await click([...document.querySelectorAll('.pf-board-writing-tabs button')].find(button => button.textContent === 'AI 写'))
    assert.ok(document.querySelector('.pf-board-detail [aria-label="AI 写作要求"]'))
    await click([...document.querySelectorAll('.pf-board-tabs button')].find(button => button.textContent === '图片'))
    await click(document.querySelector('.pf-board-section.is-image .pf-board-card'))
    assert.ok(document.querySelector('[aria-label="素材详情"]'))
    const boardPrompt = document.querySelector('.pf-board-composer [aria-label="生成描述"]')
    assert.ok(boardPrompt, 'image generation parameters are available inline')
    await act(async () => { boardPrompt.textContent = '故事板修改的提示词'; boardPrompt.dispatchEvent(new Event('input', { bubbles: true })) })
    await click(document.querySelector('[aria-label="返回分类网格"]'))
    await click(document.querySelector('.pf-board-card'))
    assert.equal(document.querySelector('.pf-board-composer [aria-label="生成描述"]').textContent, '故事板修改的提示词')
    await settle(1350)
    assert.ok(saves.at(-1).document.nodes.some(node => node.data.prompt === '故事板修改的提示词'), 'storyboard draft autosaves without generating')
    await click([...document.querySelectorAll('.pf-board-detail header button')].find(button => button.textContent === '在画布中查看'))
    assert.ok(document.querySelector('.react-flow'))
    assert.equal(count(), 8)
    activeWorkflow = false
    stored = { version: stored.version + 1, document: { ...stored.document, nodes: stored.document.nodes.map((node, index) => index === 0 ? { ...node, data: { ...node.data, label: '其他项目成员的修改' } } : node) } }
    await settle(2200)
    assert.ok(document.body.textContent.includes('其他项目成员的修改'), 'shared edits sync even without a background workflow')
    membershipAllowed = false
    await settle(2200)
    assert.equal(document.querySelector('[aria-label="整理画布"]').disabled, true, 'removed project members become read-only on the next access check')
    const saveCount = saves.length
    await act(async () => window.dispatchEvent(new Event('pf-studio-session-expired')))
    await settle()
    assert.equal(document.querySelector('[aria-label="整理画布"]').disabled, true, 'read-only sessions cannot organize')
    await key('a', { ctrlKey: true })
    for (const [value, modifiers] of [['Delete', {}], ['d', { ctrlKey: true }], ['x', { ctrlKey: true }], ['v', { ctrlKey: true }], ['g', { ctrlKey: true }], ['Tab', {}], ['z', { ctrlKey: true }]]) await key(value, modifiers)
    assert.equal(count(), 8, 'read-only canvas refuses every destructive shortcut')
    assert.equal(Boolean(document.querySelector('.pf-add-menu')), false)
    await settle(1350)
    assert.equal(saves.length, saveCount, 'read-only shortcuts never persist a write')
    await act(async () => document.querySelector('.pf-skel-text').dispatchEvent(new MouseEvent('dblclick', { bubbles: true, view: window })))
    await settle()
    assert.equal(document.querySelector('[aria-label="文本正文"]').getAttribute('contenteditable'), 'false', 'read-only text remains viewable')
    assert.equal(document.querySelector('[aria-label="加粗"]').disabled, true)
    await click(document.querySelector('[aria-label="关闭文本编辑器"]'))
    await settle(1350)
    assert.equal(saves.length, saveCount, 'closing read-only text never saves')
  } finally {
    if (root) { const { act } = await import('react'); await act(async () => root.unmount()) }
    await server?.close()
    dom.window.close()
    for (const [name, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name] }
  }
})

