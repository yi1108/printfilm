import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

test('closing or switching writing composers retains jobs, progress, results and explicit stop', async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const previous = new Map()
  const install = (key, value) => { previous.set(key, Object.getOwnPropertyDescriptor(globalThis, key)); Object.defineProperty(globalThis, key, { configurable: true, writable: true, value }) }
  for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Node', 'Event', 'MouseEvent', 'localStorage']) install(key, dom.window[key])
  install('IS_REACT_ACT_ENVIRONMENT', true)
  install('fetch', async () => Response.json({ items: [] }))
  let server, root, api, originals, store
  const jobs = [], stopped = [], applied = [], busy = []
  let sequence = 0, resolveSession, delaySession = false, inputsChanged = false
  try {
    server = await createServer({ configFile: false, root: fileURLToPath(new URL('..', import.meta.url)), plugins: [react()], server: { middlewareMode: true, hmr: false, ws: false, watch: null }, logLevel: 'error' })
    const { InlineTextComposer } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/InlineTextComposer.tsx')
    const { WritingRunStore } = await server.ssrLoadModule('/src/features/printfilm-studio/canvas/WritingRunStore.ts')
    api = (await server.ssrLoadModule('/src/features/printfilm-studio/api.ts')).printfilmStudioApi
    originals = { ...api }
    Object.assign(api, {
      agentConfig: async () => ({ models: [{ id: 'writer', label: '测试模型' }] }),
      createSession: async () => {
        const id = `session-${++sequence}`
        if (delaySession) await new Promise(resolve => { resolveSession = resolve })
        return { id }
      },
      updateSession: async () => ({}),
      stopSession: async id => { stopped.push(id) },
      stream: (id, prompt, event, signal) => new Promise((resolve, reject) => {
        jobs.push({ id, prompt, event, signal, resolve, reject })
        signal.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')), { once: true })
      }),
    })
    store = new WritingRunStore(id => api.stopSession(id))
    const { createElement: h, act } = await import('react')
    const { createRoot } = await import('react-dom/client')
    root = createRoot(document.getElementById('root'))
    const mount = async id => {
      await act(async () => root.render(id ? h(InlineTextComposer, {
        key: id, projectId: 1, nodeId: id, title: id, text: '', settings: { writingPrompt: '写镜头提示词', writingModel: 'writer' },
        references: [], candidates: [], headers: {}, writable: true, runStore: store,
        onSetting: () => {}, onReference: () => {}, onBusy: value => busy.push([id, value]),
        onValidate: () => { if (inputsChanged) throw new Error('写作要求已变化，保留结果') },
        onApply: result => applied.push([id, result]),
      }) : h('div', null, '画布空白处')))
    }
    const click = async label => { const button = document.querySelector(`[aria-label="${label}"]`); assert.ok(button, label); await act(async () => button.dispatchEvent(new MouseEvent('click', { bubbles: true }))) }
    const finish = async (job, text) => { await act(async () => { job.event({ type: 'message_delta', content: text }); job.resolve() }) }

    // Dismiss while session creation is still pending; the eventual job must start.
    delaySession = true
    await mount('one'); await click('开始 AI 写作')
    const startedAt = store.snapshot('1:one').startedAt
    await mount(null)
    assert.deepEqual(busy, [['one', true]])
    await act(async () => resolveSession())
    delaySession = false
    assert.equal(jobs.length, 1)
    assert.equal(jobs[0].signal.aborted, false)
    assert.deepEqual(stopped, [])
    await act(async () => jobs[0].event({ type: 'message_delta', content: '第一段' }))
    await mount('one')
    assert.equal(document.querySelector('[aria-label="写作实时预览"]'), null)
    assert.ok(!document.body.textContent.includes('第一段'), 'partial text is buffered, never rendered')
    assert.match(document.querySelector('[role="status"]').textContent, /完成后写入节点/)
    assert.equal(store.snapshot('1:one').result, '')
    assert.ok(document.querySelector('[aria-label="停止写作"]'))
    assert.equal(document.querySelector('[aria-label="开始 AI 写作"]'), null)
    assert.equal(store.snapshot('1:one').startedAt, startedAt)
    assert.equal(store.begin('1:one'), null, 'reopening cannot charge for a duplicate job')

    // A different selected node gets its own job; the hidden node still receives its result.
    await mount('two'); await click('开始 AI 写作')
    assert.equal(jobs.length, 2)
    await finish(jobs[0], '，完成')
    assert.deepEqual(applied, [['one', '第一段，完成']])
    assert.equal(store.snapshot('1:one').busy, false)
    assert.equal(store.snapshot('1:two').busy, true)
    assert.deepEqual(busy.at(-1), ['one', false])
    assert.deepEqual(stopped, [])

    // A live conflict is checked even with no composer mounted; output remains recoverable.
    await mount(null); inputsChanged = true
    await finish(jobs[1], '发生冲突的正文')
    inputsChanged = false
    assert.equal(applied.length, 1)
    await mount('two')
    assert.match(document.querySelector('[role="alert"]').textContent, /写作要求已变化/)
    assert.equal(document.querySelector('[aria-label="保留的生成结果"]').value, '发生冲突的正文')

    // Reopening and explicitly pressing stop is the only composer action that cancels.
    await click('开始 AI 写作'); await mount(null); await mount('two')
    assert.equal(jobs.length, 3)
    await click('停止写作')
    assert.deepEqual(stopped, [jobs[2].id])
    assert.equal(jobs[2].signal.aborted, true)
    assert.equal(store.snapshot('1:two').busy, false)
    assert.equal(applied.length, 1)

    // Network/model failure while hidden is also retained on reopen.
    await click('开始 AI 写作'); await mount(null)
    await act(async () => { jobs[3].event({ type: 'message_delta', content: '部分正文' }); jobs[3].reject(new Error('模型暂时不可用')) })
    await mount('two')
    assert.match(document.querySelector('[role="alert"]').textContent, /模型暂时不可用/)
    assert.equal(document.querySelector('[aria-label="保留的生成结果"]').value, '部分正文')
    assert.equal(stopped.length, 1)
  } finally {
    store?.dispose()
    if (root) { const { act } = await import('react'); await act(async () => root.unmount()) }
    if (api && originals) Object.assign(api, originals)
    await server?.close(); dom.window.close()
    for (const [key, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key] }
  }
})
