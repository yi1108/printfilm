import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

test('Studio menus support keyboard and mouse without triggering canvas commands', async (t) => {
  const dom = new JSDOM('<button id="trigger">打开菜单</button><input id="outside"><div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const previous = new Map()
  for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'MouseEvent', 'KeyboardEvent']) {
    previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name))
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value: dom.window[name] })
  }
  previous.set('IS_REACT_ACT_ENVIRONMENT', Object.getOwnPropertyDescriptor(globalThis, 'IS_REACT_ACT_ENVIRONMENT'))
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  let server, root
  try {
    server = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
    const { StudioContextMenu } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/NodePanels.tsx')
    const { AddNodeMenu } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/AddNodeMenu.tsx')
    const { createElement: h, act, useState } = await import('react')
    const { createRoot } = await import('react-dom/client')
    const trigger = document.getElementById('trigger')
    const selected = []
    let closed = 0
    const actions = [{ id: 'disabled', label: '不可用', disabled: true }, { id: 'copy', label: '复制' }, { id: 'hidden', label: '不可用删除', disabled: true }, { id: 'duplicate', label: '副本' }, { id: 'remove', label: '删除' }]
    const key = async (value, target = document.activeElement) => {
      const event = new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true })
      await act(async () => target.dispatchEvent(event))
      return event
    }
    const click = async (target) => { await act(async () => target.click()) }
    const mount = async (kind = 'context', overrides = {}) => {
      if (root) await act(async () => root.unmount())
      selected.length = 0; closed = 0; trigger.focus()
      function Harness() {
        const [open, setOpen] = useState(true)
        const close = () => { closed += 1; setOpen(false) }
        const select = (item) => { selected.push(item); close() }
        return open ? kind === 'add' ? h(AddNodeMenu, { onAdd: select, onClose: close }) : h(StudioContextMenu, { menu: { left: 50, top: 50 }, actions, onSelect: select, onClose: close, ...overrides }) : null
      }
      root = createRoot(document.getElementById('root'))
      await act(async () => root.render(h(Harness)))
    }

    await t.test('context menu focuses enabled actions, wraps arrows, and supports Home/End', async () => {
      await mount()
      assert.equal(document.activeElement.textContent, '复制')
      await key('ArrowDown'); assert.equal(document.activeElement.textContent, '副本')
      await key('End'); assert.equal(document.activeElement.textContent, '删除')
      await key('ArrowDown'); assert.equal(document.activeElement.textContent, '复制')
      await key('ArrowUp'); assert.equal(document.activeElement.textContent, '删除')
      await key('Home'); assert.equal(document.activeElement.textContent, '复制')
    })
    await t.test('Enter and Space activate exactly once and return focus to the opener', async () => {
      for (const activation of ['Enter', ' ']) {
        await mount()
        await key(activation)
        assert.deepEqual(selected, ['copy'])
        assert.equal(closed, 1)
        assert.equal(document.querySelector('[role="menu"]'), null)
        assert.equal(document.activeElement, trigger)
      }
    })
    await t.test('Escape and Tab close without selecting, including an all-disabled menu', async () => {
      for (const closing of ['Escape', 'Tab']) {
        await mount('context', { actions: [{ id: 'none', label: '不可操作', disabled: true }] })
        assert.equal(document.activeElement.getAttribute('role'), 'menu')
        await key(closing)
        assert.deepEqual(selected, [])
        assert.equal(closed, 1)
        assert.equal(document.activeElement, trigger)
      }
    })
    await t.test('menu keys do not escape to canvas, while an outside input is untouched', async () => {
      await mount()
      const received = []
      const handler = event => received.push(event.key)
      document.addEventListener('keydown', handler)
      try {
        for (const value of ['Delete', 'Backspace', 'c', 'ArrowRight']) await key(value)
        assert.deepEqual(received, [])
        const input = document.getElementById('outside')
        input.focus()
        const event = await key('ArrowDown', input)
        assert.equal(event.defaultPrevented, false)
        assert.deepEqual(received, ['ArrowDown'])
        assert.equal(closed, 0)
        await act(async () => root.unmount()); root = null
        assert.equal(document.activeElement, input, 'unmount must not steal focus from another editor')
      } finally { document.removeEventListener('keydown', handler) }
    })
    await t.test('mouse selection uses the same action and disabled buttons never execute', async () => {
      await mount()
      await click(document.querySelector('[disabled]'))
      assert.deepEqual(selected, [])
      await click([...document.querySelectorAll('[role="menuitem"]')].find(item => item.textContent === '副本'))
      assert.deepEqual(selected, ['duplicate'])
      assert.equal(closed, 1)
    })
    await t.test('add menu focuses text, supports group navigation and returns to the group', async () => {
      await mount('add')
      assert.equal(document.activeElement.querySelector('b')?.textContent, '文本')
      const group = document.querySelector('[aria-haspopup="menu"]')
      assert.ok(group)
      group.focus()
      await key('ArrowRight')
      assert.equal(group.getAttribute('aria-expanded'), 'true')
      assert.equal(document.activeElement.textContent, '项目资产')
      await key('End'); assert.equal(document.activeElement.textContent, '本地上传')
      await key('ArrowDown'); assert.equal(document.activeElement.textContent, '项目资产')
      await key('ArrowLeft')
      assert.equal(document.activeElement, group)
      assert.equal(group.getAttribute('aria-expanded'), 'false')
      await key('Enter')
      assert.equal(document.activeElement.textContent, '项目资产')
      await key('Escape')
      assert.equal(document.activeElement, group)
      assert.equal(closed, 0, 'Escape first leaves the submenu')
      await key('Escape')
      assert.equal(closed, 1)
    })
    await t.test('add menu keyboard selects the real catalogue entry', async () => {
      await mount('add')
      await key('ArrowDown')
      await key('Enter')
      assert.equal(selected[0]?.id, 'image')
      assert.equal(selected[0]?.editor, 'edit')
      assert.equal(closed, 1)
    })
  } finally {
    if (root) { const { act } = await import('react'); await act(async () => root.unmount()) }
    await server?.close()
    dom.window.close()
    for (const [name, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name] }
  }
})
