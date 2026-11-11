import test from 'node:test'
import assert from 'node:assert/strict'
import { tourLayout } from '../src/features/printfilm-studio/canvas/tourLayout.ts'

test('tour cards stay inside narrow and wide viewports and highlights follow target movement', () => {
  for (const viewport of [{ width: 360, height: 640 }, { width: 1440, height: 900 }]) {
    for (const target of [null, { left: 10, top: 10, width: 42, height: 42 }, { left: viewport.width - 50, top: viewport.height - 50, width: 42, height: 42 }, { left: -100, top: -50, width: 300, height: 200 }]) {
      const { card, focus } = tourLayout(target, viewport, 270)
      assert.ok(card.left >= 12 && card.top >= 12)
      assert.ok(card.left + card.width <= viewport.width - 12)
      assert.ok(card.top + 270 <= viewport.height - 12)
      if (focus) assert.ok(focus.left >= 0 && focus.top >= 0 && focus.left + focus.width <= viewport.width && focus.top + focus.height <= viewport.height)
    }
  }
  const target = { left: 400, top: 300, width: 100, height: 40 }
  const first = tourLayout(target, { width: 1440, height: 900 })
  const moved = tourLayout({ ...target, left: 500 }, { width: 1440, height: 900 })
  assert.equal(moved.focus.left - first.focus.left, 100)
  assert.equal(tourLayout({ left: -500, top: 0, width: 10, height: 10 }, { width: 360, height: 640 }).focus, null)
})

test('tour next/back/skip/Escape navigate without clicking the highlighted action', async () => {
  const { JSDOM } = await import('jsdom')
  const { createServer } = await import('vite')
  const { default: react } = await import('@vitejs/plugin-react')
  const { fileURLToPath } = await import('node:url')
  const dom = new JSDOM('<button id="start">操作指引</button><button aria-label="添加节点">添加节点</button><div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const old = new Map()
  const install = (key, value) => { old.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, { configurable: true, writable: true, value }) }
  for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'Event', 'MouseEvent', 'KeyboardEvent']) install(key, dom.window[key])
  for (const key of ['requestAnimationFrame', 'cancelAnimationFrame', 'getComputedStyle']) install(key, dom.window[key].bind(dom.window))
  install('IS_REACT_ACT_ENVIRONMENT', true)
  let server, root
  try {
    server = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
    const { WorkspaceTour, WORKSPACE_TOUR_STEPS } = await server.ssrLoadModule('/src/features/printfilm-studio/WorkspaceTour.tsx')
    const { createElement: h, act } = await import('react'), { createRoot } = await import('react-dom/client')
    root = createRoot(document.getElementById('root'))
    const visited = []; let submitted = 0, closed = 0
    document.querySelector('[aria-label="添加节点"]').onclick = () => { submitted++ }
    const close = () => { closed++; root.render(null) }
    const mount = () => root.render(h(WorkspaceTour, { onClose: close, onStep: id => visited.push(id) }))
    const click = async text => { const button = [...document.querySelectorAll('.pf-tour-card button')].find(item => item.textContent === text); assert.ok(button); await act(async () => button.click()) }
    document.getElementById('start').focus()
    await act(async () => mount())
    assert.equal(document.querySelector('.pf-tour-card button[disabled]').textContent, '上一步')
    await click('下一步'); assert.equal(document.querySelector('.pf-workspace-tour').dataset.step, 'canvas')
    await click('上一步'); assert.equal(document.querySelector('.pf-workspace-tour').dataset.step, 'add')
    for (let i = 1; i < WORKSPACE_TOUR_STEPS.length; i++) await click('下一步')
    await click('完成')
    assert.equal(document.querySelector('.pf-workspace-tour'), null)
    assert.equal(document.activeElement.id, 'start')
    await act(async () => mount()); await click('跳过指引')
    await act(async () => mount())
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    await act(async () => window.dispatchEvent(escape))
    assert.equal(escape.defaultPrevented, true)
    assert.equal(closed, 3)
    assert.equal(submitted, 0)
    assert.ok(visited.includes('agent') && visited.includes('generate'))
  } finally {
    if (root) { const { act } = await import('react'); await act(async () => root.unmount()) }
    await server?.close(); dom.window.close()
    for (const [key, value] of old) { if (value) Object.defineProperty(globalThis, key, value); else delete globalThis[key] }
  }
})
