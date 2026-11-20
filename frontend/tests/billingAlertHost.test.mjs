import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'

test('billing alerts stop polling a rejected token and resume with a new session', async () => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost' })
  const previous = new Map()
  const install = (name, value) => {
    previous.set(name, Object.getOwnPropertyDescriptor(globalThis, name))
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value })
  }
  for (const name of ['window', 'document', 'localStorage']) install(name, dom.window[name])
  install('IS_REACT_ACT_ENVIRONMENT', true)
  const requests = []
  install('fetch', async (url, init) => {
    assert.match(String(url), /\/api\/billing\/alerts\/pending$/)
    const token = new Headers(init.headers).get('Authorization')
    requests.push(token)
    return token === 'Bearer expired'
      ? Response.json({ detail: 'Unauthorized' }, { status: 401 })
      : Response.json({ items: [] })
  })
  let server
  let root
  try {
    server = await createServer({
      configFile: false,
      root: fileURLToPath(new URL('..', import.meta.url)),
      plugins: [react()],
      cacheDir: '.tmp/vite-billing-alert-tests',
      server: { middlewareMode: true, hmr: false, ws: false, watch: null },
    })
    const { default: Host } = await server.ssrLoadModule('/src/components/billing/BillingAlertHost.tsx')
    localStorage.setItem('token', 'expired')
    root = createRoot(document.querySelector('#root'))
    await act(async () => root.render(createElement(Host)))
    const focus = () => act(async () => window.dispatchEvent(new dom.window.Event('focus')))
    await focus()
    await focus()
    assert.deepEqual(requests, ['Bearer expired'])
    localStorage.setItem('token', 'new-session')
    await focus()
    assert.deepEqual(requests, ['Bearer expired', 'Bearer new-session'])
  } finally {
    if (root) await act(async () => root.unmount())
    await server?.close()
    dom.window.close()
    for (const [name, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor)
      else delete globalThis[name]
    }
  }
})
