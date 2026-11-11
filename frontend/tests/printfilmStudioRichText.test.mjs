import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

test('rich text dialog formats, copies, saves on close, and preserves read-only content', async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const previous = new Map()
  const install = (name, value) => { previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name)); Object.defineProperty(globalThis, name, { configurable: true, writable: true, value }) }
  for (const name of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'MouseEvent', 'MutationObserver']) install(name, dom.window[name])
  install('getComputedStyle', dom.window.getComputedStyle.bind(dom.window))
  install('requestAnimationFrame', dom.window.requestAnimationFrame.bind(dom.window))
  install('cancelAnimationFrame', dom.window.cancelAnimationFrame.bind(dom.window))
  install('IS_REACT_ACT_ENVIRONMENT', true)
  dom.window.Range.prototype.getClientRects = () => []
  dom.window.Range.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 })
  let copied = '', server, root
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async value => { copied = value } } })
  try {
    server = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
    const { TextNodeEditor } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/TextNodeEditor.tsx')
    const { createElement: h, act, useState, StrictMode } = await import('react')
    const { createRoot } = await import('react-dom/client')
    root = createRoot(document.getElementById('root'))
    const initial = { label: '剧本', prompt: '保留提示词', text: '司马懿\n\n城中为何空无一人？', clipStart: '', clipEnd: '' }
    let saved, closed = 0, changes = 0
    function Harness({ writable = true, text = initial.text, references = [] }) {
      const [draft, setDraft] = useState({ ...initial, text })
      return h(TextNodeEditor, { draft, writable, references, onChange: value => { changes++; setDraft(value) }, onSave: () => { saved = draft }, onClose: () => { closed++ } })
    }
    const settle = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)) }) }
    const render = async props => { await act(async () => root.render(h(StrictMode, null, h(Harness, props)))); await settle() }
    const click = async label => { await act(async () => document.querySelector(`[aria-label="${label}"]`).dispatchEvent(new MouseEvent('click', { bubbles: true }))); await settle() }
    const key = async (value, options = {}) => { await act(async () => document.querySelector('[aria-label="文本正文"]').dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true, ...options }))); await settle() }
    await render({ key: 'editable' })
    const body = document.querySelector('[aria-label="文本正文"]')
    assert.equal(body.getAttribute('contenteditable'), 'true')
    assert.equal(body.querySelectorAll('p').length, 2)
    assert.equal(changes, 0, 'opening does not normalize or save the source')
    assert.equal(document.querySelector('textarea'), null)
    await click('关闭文本编辑器')
    assert.equal(closed, 1)
    assert.equal(saved, undefined)
    await key('a', { ctrlKey: true })
    await click('加粗')
    assert.equal(body.querySelector('strong').textContent, '司马懿')
    assert.equal(document.querySelector('[aria-label="加粗"]').getAttribute('aria-pressed'), 'true')
    await click('二级标题')
    assert.equal(body.querySelector('h2 strong').textContent, '司马懿')
    await click('复制正文')
    assert.ok(copied.includes('城中为何空无一人？'))
    assert.ok(!copied.includes('**'))
    await key('s', { ctrlKey: true })
    assert.ok(saved.text.includes('## **司马懿**'))
    assert.equal(saved.prompt, initial.prompt)
    assert.equal(saved.label, initial.label)
    const markdown = saved.text
    saved = undefined
    await render({ key: 'reopen', text: markdown })
    assert.equal(document.querySelector('h2 strong').textContent, '司马懿')
    await key('a', { ctrlKey: true })
    await click('正文')
    await key('Escape')
    assert.ok(saved.text.includes('**司马懿**'))
    assert.ok(!saved.text.includes('##'))
    saved = undefined
    await render({ key: 'readonly', writable: false, text: markdown })
    assert.equal(document.querySelector('[aria-label="文本正文"]').getAttribute('contenteditable'), 'false')
    assert.equal(document.querySelector('[aria-label="加粗"]').disabled, true)
    await key('s', { ctrlKey: true })
    await click('关闭文本编辑器')
    assert.equal(saved, undefined)
    // Existing tables, checklists, links and images survive an unrelated text edit.
    const complex = '# 剧本\n\n台词一\n台词二\n\n| 人物 | 台词 |\n| --- | --- |\n| 张飞 | 走！ |\n\n- [x] 完成\n\n[资料](https://example.com)\n\n![场景](https://example.com/scene.png)'
    await render({ key: 'gfm', text: complex })
    assert.equal(document.querySelectorAll('.tiptap table').length, 1)
    assert.equal(document.querySelectorAll('.tiptap img').length, 1)
    assert.equal(document.querySelectorAll('.tiptap input[type="checkbox"]:checked').length, 1)
    assert.ok(document.querySelector('.tiptap p br'), 'script line breaks stay visible')
    await click('三级标题')
    await click('关闭文本编辑器')
    assert.match(saved.text, /\|\s*张飞\s*\|\s*走！\s*\|/)
    assert.ok(saved.text.includes('- [x] 完成'))
    assert.ok(saved.text.includes('[资料](https://example.com)'))
    assert.ok(saved.text.includes('![场景](https://example.com/scene.png)'))
    const ref = { id: 'picture-1', source: 'node', label: '角色·刘备', mediaKind: 'image', url: '/reference.png' }
    const token = `@[${encodeURIComponent(ref.label)}](node:${ref.id})`
    await render({ key: 'refs', text: `中景，${token}站在门口。`, references: [ref] })
    assert.equal(document.querySelector('.tiptap [data-canvas-reference] img').getAttribute('src'), ref.url)
    assert.ok(document.querySelector('.tiptap').textContent.includes(ref.label))
    assert.ok(!document.querySelector('.tiptap').textContent.includes('%E'))
    await click('二级标题')
    await click('关闭文本编辑器')
    assert.ok(saved.text.includes(token), 'formatting keeps the stable image identity')
    assert.ok(!saved.text.includes(ref.url), 'thumbnail URLs are never serialized into prose')
    await render({ key: 'legacy-ref', text: `场景为 @[${encodeURIComponent(ref.label)}](node:${ref.id})`, references: [ref] })
    assert.equal(document.querySelectorAll('.tiptap [data-canvas-reference]').length, 1)
    const { MessageContent } = await server.ssrLoadModule('/src/features/printfilm-studio/agent/MessageContent.tsx')
    const { renderToStaticMarkup } = await import('react-dom/server')
    const html = renderToStaticMarkup(h(MessageContent, {text: token, references:[ref]}))
    assert.ok(html.includes('/reference.png') && html.includes(ref.label))
    assert.ok(!html.includes('href="node:'))
  } finally {
    if (root) { const { act } = await import('react'); await act(async () => root.unmount()) }
    await server?.close()
    await new Promise(resolve => setTimeout(resolve, 60))
    dom.window.close()
    for (const [name, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name] }
  }
})
