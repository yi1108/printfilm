import test from 'node:test'
import assert from 'node:assert/strict'
import { canEditStudioCanvas, loadStudioCanvas, reportStudioUnauthorized, studioLoginPath, workspaceIssue } from '../src/features/printfilm-studio/workspaceAccess.ts'

function deferred() {
  let resolve, reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

test('expired login displays reauthentication instead of leaving an editable empty canvas', async () => {
  let ready = false
  let issue
  await loadStudioCanvas({
    syncWorkspace: async () => { throw Object.assign(new Error('登录已失效'), { status: 401 }) },
    loadCanvas: async () => assert.fail('cannot read canvas before authentication succeeds'),
    isCurrent: () => true,
    onReady: () => { ready = true },
    onError: (next) => { issue = next },
  })
  assert.equal(issue.action, 'login')
  assert.equal(issue.title, '登录已失效')
  assert.equal(canEditStudioCanvas(true, ready, false, false), false)
})

test('canvas loading waits for project workspace and allows adding only after readiness and lock', async () => {
  const workspace = deferred()
  const document = { version: 7, document: { nodes: [] } }
  let loaded = false
  let received
  const pending = loadStudioCanvas({
    syncWorkspace: () => workspace.promise,
    loadCanvas: async () => { loaded = true; return document },
    isCurrent: () => true, onReady: (value) => { received = value }, onError: assert.fail,
  })
  assert.equal(loaded, false)
  assert.equal(canEditStudioCanvas(true, false, false, false), false)
  workspace.resolve()
  await pending
  assert.equal(received, document)
  assert.equal(canEditStudioCanvas(true, true, false, false), true)
  assert.equal(canEditStudioCanvas(true, true, true, false), false)
  assert.equal(canEditStudioCanvas(true, true, false, true), false)
  assert.equal(canEditStudioCanvas(false, true, false, false), false)
})

test('a network failure offers retry and the successful retry enables the canvas', async () => {
  let calls = 0
  let ready = false
  const issues = []
  const options = {
    syncWorkspace: async () => {}, isCurrent: () => true,
    loadCanvas: async () => { if (++calls === 1) throw new TypeError('Failed to fetch'); return { nodes: [{ id: 'existing' }] } },
    onReady: (document) => { ready = true; assert.equal(document.nodes[0].id, 'existing') },
    onError: (issue) => issues.push(issue),
  }
  await loadStudioCanvas(options)
  assert.equal(ready, false)
  assert.equal(issues[0].action, 'retry')
  await loadStudioCanvas(options)
  assert.equal(canEditStudioCanvas(true, ready, false, false), true)
})

test('late requests from a different project or workspace cannot populate the current canvas', async () => {
  for (const stage of ['workspace', 'canvas']) {
    const result = deferred()
    let current = true
    const pending = loadStudioCanvas({
      syncWorkspace: () => stage === 'workspace' ? result.promise : Promise.resolve(),
      loadCanvas: () => stage === 'canvas' ? result.promise : Promise.resolve({}),
      isCurrent: () => current, onReady: assert.fail, onError: assert.fail,
    })
    await Promise.resolve()
    current = false
    result.resolve({ nodes: [{ id: 'old-project' }] })
    await pending
  }
})

test('scope cancellations are not displayed as login failures', async () => {
  await loadStudioCanvas({
    syncWorkspace: async () => {},
    loadCanvas: async () => { throw new DOMException('workspace changed', 'AbortError') },
    isCurrent: () => true, onReady: assert.fail, onError: assert.fail,
  })
})

test('missing or forbidden project does not ask the user to log out', () => {
  for (const status of [403, 404]) assert.equal(workspaceIssue({ status }).action, 'back')
  assert.equal(workspaceIssue({ status: 503 }).action, 'retry')
  assert.equal(workspaceIssue(new Error('401 without HTTP status')).action, 'retry')
})

test('an invalid canvas document cannot mark the editor ready', async () => {
  let issue
  await loadStudioCanvas({
    syncWorkspace: async () => {}, loadCanvas: async () => ({}), isCurrent: () => true,
    onReady: () => { throw new Error('画布格式无效') }, onError: (value) => { issue = value },
  })
  assert.equal(issue.action, 'retry')
  assert.equal(issue.message, '画布格式无效')
})

test('only current-token 401 reports session expiry; old requests cannot invalidate new login', () => {
  let reports = 0
  const notify = () => { reports++ }
  reportStudioUnauthorized({ status: 401 }, 'old', () => 'new', notify)
  reportStudioUnauthorized({ status: 401 }, null, () => null, notify)
  for (const status of [403, 409, 423, 500]) reportStudioUnauthorized({ status }, 'new', () => 'new', notify)
  assert.equal(reports, 0)
  reportStudioUnauthorized({ status: 401 }, 'new', () => 'new', notify)
  assert.equal(reports, 1)
})

test('login return URL preserves the project path, search and hash', () => {
  const original = '/drama/projects/1/printfilm-studio?view=canvas#node-2'
  const login = new URL(studioLoginPath(original), 'http://localhost')
  assert.equal(login.pathname, '/auth')
  assert.equal(login.searchParams.get('next'), original)
})
