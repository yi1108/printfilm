import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

// Mount the actual workspace/menu/React Flow, with deterministic DOM measurements.
// All HTTP is mocked: this test never reads or writes a real user's project.
test('connected writing and the saved character voice reach both video requests', async () => {
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
  const generationBodies = []
  const assets = [
    { id: 7, asset_type: 'image', name: '祭台夜景.png', url: '/altar.png' },
    { id: 8, asset_type: 'image', name: '舞者', url: '/role.png' },
  ]
  let stored = { version: 1, document: { toonflowCanvas: true, version: 1, nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } } }
  install('fetch', async (input, init) => {
    const path = new URL(String(input), dom.window.location.origin).pathname
    let data
    if (path === '/api/drama/projects/361') data = { id: 361, user_id: 1, team_id: null, title: '测试项目', script: '' }
    else if (path.endsWith('/info')) data = { id: 361, title: '测试项目', is_owner: true }
    else if (path.endsWith('/canvas') && init?.method === 'PUT') {
      const body = JSON.parse(init.body)
      assert.equal(body.expected_version, stored.version)
      stored = { document: body.document, version: stored.version + 1 }; data = stored
    }
    else if (path.endsWith('/canvas')) data = stored
    else if (path.endsWith('/workflow')) data = { ...stored, run: null }
    else if (path.endsWith('/agent/sessions')) data = { sessions: [] }
    else if (path.endsWith('/agent/config')) data = { models: [], tools: [] }
    else if (path.endsWith('/canvas/assets')) data = { assets }
    else if (path.endsWith('/canvas/assets/upload')) {
      assert.equal(init.body.get('file').name, 'voice.wav')
      data = { id: 42, asset_type: 'audio', name: 'voice.wav', url: '/voice.wav' }
      assets.push(data)
    }
    else if (path.includes('media-models')) data = { image_models: [], video_models: [], defaults: {} }
    else if (path.includes('wallet')) data = { balance_yuan: 0 }
    else if (path === '/api/tools/estimate') data = { estimate_fen: 588, price_version: 1 }
    else if (path.endsWith('/generations')) { generationBodies.push(init.body); data = { status: 'queued', task_id: 'unit-generation' } }
    else if (path.includes('tasks')) data = { items: [] }
    else throw new Error(`Unexpected test request: ${path}`)
    return Response.json(data)
  })
  let server, root
  try {
    server = await createServer({ configFile: false, cacheDir: '.tmp/vite-connected-generation-tests', optimizeDeps: { noDiscovery: true, include: [] }, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
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
    const writing = '16:9 横幅，7 秒，动漫舞者在飞机客舱跳舞。' + '镜'.repeat(10_000) + '尾部标记'
    stored.document.nodes = [
      {id:'writing',type:'text',position:{x:0,y:0},data:{label:'新文本',text:writing}},
      {id:'video',type:'video',position:{x:450,y:0},data:{label:'新视频',editor:'video',modelId:'seedance-2.5',ratio:'16:9',duration:'7',resolution:'720p'}},
      {id:'other',type:'video',position:{x:450,y:260},data:{label:'第二镜',editor:'video',modelId:'seedance-2.5',ratio:'16:9',duration:'7',resolution:'720p'}},
      {id:'role',type:'character',position:{x:0,y:240},data:{label:'舞者',mediaType:'image',mediaUrl:'/role.png'}},
    ]
    stored.document.edges = ['video', 'other'].map(target => ({ id: `writing-${target}`, source: 'writing', target }))
    await mount()
    await act(async () => document.querySelector('.react-flow__node[data-id="role"]').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true })))
    await click([...document.querySelectorAll('button')].find(button => button.textContent.includes('绑定角色参考音频')))
    const voiceInput = document.querySelector('input[aria-label="上传角色参考音频"]')
    Object.defineProperty(voiceInput, 'files', { value: [new File(['shared voice bytes'], 'voice.wav', { type: 'audio/wav' })] })
    await act(async () => voiceInput.dispatchEvent(new Event('change', { bubbles: true })))
    await settle(100)
    const video = document.querySelector('.react-flow__node[data-id="video"]')
    const paste = async (input, text, offset) => {
      await act(async () => {
        input.focus()
        const range = document.createRange()
        range.selectNodeContents(input)
        if (offset !== undefined) {
          range.setStart(input.firstChild, offset)
          range.collapse(true)
        }
        window.getSelection().removeAllRanges()
        window.getSelection().addRange(range)
        const event = new Event('paste', { bubbles: true, cancelable: true })
        Object.defineProperty(event, 'clipboardData', { value: { getData: () => text } })
        input.dispatchEvent(event)
      })
      await settle()
      assert.ok(input.querySelector('.pf-inline-reference'))
    }
    await click(video)
    const input = video.querySelector('[aria-label="生成描述"]')
    assert.equal(input.textContent, stored.document.nodes[0].data.text)
    await paste(input, '，@舞者抬头。', writing.indexOf('尾部标记'))
    assert.match(input.textContent, /，@舞者抬头。尾部标记\n参考素材：舞者$/)
    assert.equal(video.querySelector('[aria-label="生成"]').disabled, false)
    assert.equal(generationBodies.length, 0, 'opening a node does not create a paid task')
    await click(video.querySelector('[aria-label="生成"]'))
    await settle(120)
    assert.equal(generationBodies.length, 1, video.textContent)
    assert.equal(generationBodies[0].get('tool_id'), 't2v')
    assert.match(generationBodies[0].get('prompt'), /动漫舞者在飞机客舱跳舞/)
    assert.equal(generationBodies[0].get('node_id'), 'video')
    const other = document.querySelector('.react-flow__node[data-id="other"]')
    await click(other)
    await paste(other.querySelector('[aria-label="生成描述"]'), writing + '，@舞者抬头。')
    await click(other.querySelector('[aria-label="生成"]'))
    await settle(120)
    assert.equal(generationBodies.length, 2)
    assert.equal(stored.document.nodes.find(node => node.id === 'role').data.voiceReferenceAssetId, 42)
    assert.equal(stored.document.edges.filter(edge => edge.source === 'role').length, 2)
    for (const body of generationBodies) {
      assert.equal(body.get('video_mode'), 'omni_reference')
      assert.match(body.get('prompt'), /尾部标记/)
      assert.match(body.get('prompt'), /@舞者抬头/)
      assert.match(body.get('prompt'), /参考素材：舞者（@图片1）/)
      assert.match(body.get('prompt'), /@音频1：仅用于舞者的对白音色/)
      assert.deepEqual(JSON.parse(body.get('references')), [
        { asset_id: 8, role: 'reference_image' },
        { asset_id: 42, role: 'reference_audio' },
      ])
      assert.equal(body.getAll('files').length, 0)
    }
    const writer = document.querySelector('.react-flow__node[data-id="writing"]')
    await click(writer)
    await click([...writer.querySelectorAll('button')].find(button => button.textContent === 'AI 写'))
    await paste(document.querySelector('[aria-label="AI 写作要求"]'), '场景使用祭台夜景.png，保留祭台夜景。')
    await settle(1350) // Flush autosave and React Flow's deferred layout before teardown.
    const libraryNode = stored.document.nodes.find(node => node.data.assetId === 7)
    assert.ok(libraryNode, 'library-only asset should become a canvas node')
    assert.equal(stored.document.nodes.filter(node => node.data.assetId === 7).length, 1)
    assert.deepEqual(stored.document.edges.filter(edge => edge.source === libraryNode.id).map(edge => edge.target).sort(), ['other', 'video', 'writing'])
  } finally {
    if (root) { const { act } = await import('react'); await act(async () => root.unmount()) }
    await server?.close()
    dom.window.close()
    for (const [name, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name] }
  }
})
