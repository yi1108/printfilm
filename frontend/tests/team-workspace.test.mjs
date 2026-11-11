import test from 'node:test'
import assert from 'node:assert/strict'
import { workspaceScope, setWorkspaceTeam, scopedRequestInit } from '../src/features/teams/workspaceScope.ts'
import { apiErrorMessage, createHttpTransport, isRequestAborted } from '../src/api/http.ts'

test('retired team switching cannot change the request scope', () => {
  const initial=workspaceScope.signal
  setWorkspaceTeam(77)
  assert.equal(workspaceScope.teamId,null)
  assert.equal(initial.aborted,false)
})

test('主动取消不作为业务报错展示，真正的网络和权限错误仍保留', () => {
  assert.equal(isRequestAborted(new DOMException('创作空间或登录身份已切换', 'AbortError')), true)
  assert.equal(isRequestAborted({ name: 'AbortError', message: 'route changed' }), true)
  assert.equal(isRequestAborted(new TypeError('Failed to fetch')), false)
  assert.equal(isRequestAborted(new Error('管理员正在编辑此内容')), false)
  assert.equal(isRequestAborted(null), false)
})

test('浏览器将取消报告为Failed to fetch时保留空间切换的AbortError', async () => {
  const originalFetch = globalThis.fetch
  const controller = new AbortController()
  const reason = new DOMException('创作空间已切换', 'AbortError')
  globalThis.fetch = async () => { controller.abort(reason); throw new TypeError('Failed to fetch') }
  try {
    const client = createHttpTransport({ baseUrl: 'http://test.local', getToken: () => null, onError: () => { throw new Error('unexpected response') } })
    await assert.rejects(client.json('/api/drama/projects', { signal: controller.signal }), (cause) => cause === reason)
  } finally { globalThis.fetch = originalFetch }
})

test('真正网络故障保持失败，不被当成主动取消', async () => {
  const originalFetch = globalThis.fetch
  const failure = new TypeError('Failed to fetch')
  globalThis.fetch = async () => { throw failure }
  try {
    const client = createHttpTransport({ baseUrl: 'http://test.local', getToken: () => null, onError: () => { throw new Error('unexpected response') } })
    await assert.rejects(client.json('/api/drama/projects', { signal: new AbortController().signal }), (cause) => cause === failure)
  } finally { globalThis.fetch = originalFetch }
})

test('换登录账号即使仍在个人空间也取消旧身份请求', () => {
  setWorkspaceTeam(null)
  const previousAccount = workspaceScope.signal
  setWorkspaceTeam(null, true)
  assert.equal(previousAccount.aborted, true)
})

test('retired team scope is never sent to creative or billing APIs', () => {
  setWorkspaceTeam(12)
  for(const path of ['/api/drama/projects','/api/billing/wallet','/api/tasks']) {
    assert.equal(new Headers(scopedRequestInit(path).headers).get('X-Team-Id'),null)
  }
})

test('显式归属读取不继承团队空间，调用方头信息仍保留', () => {
  setWorkspaceTeam(5)
  const init = scopedRequestInit('/api/drama/projects/9', { headers: { 'X-Request-Id': 'abc' } })
  assert.equal(new Headers(init.headers).get('X-Team-Id'), null)
  assert.equal(new Headers(init.headers).get('X-Request-Id'), 'abc')
  setWorkspaceTeam(null)
})

test('后台写入按资源真实归属传递，不受当前导航空间影响', () => {
  setWorkspaceTeam(5)
  const own = scopedRequestInit('/api/drama/assets/4', { method: 'PATCH', headers: { 'X-Workspace-Personal': '1' } })
  assert.equal(new Headers(own.headers).get('X-Team-Id'), null)
  assert.equal(new Headers(own.headers).get('X-Workspace-Personal'), null)
  const actual = scopedRequestInit('/api/drama/assets/4', { method: 'PATCH', headers: { 'X-Team-Id': '9', 'X-Edit-Token': 'lease' } })
  assert.equal(new Headers(actual.headers).get('X-Team-Id'), null)
  assert.equal(new Headers(actual.headers).get('X-Edit-Token'), 'lease')
  setWorkspaceTeam(null)
})

test('编辑占用冲突返回可读信息，不丢失服务端提示', () => {
  assert.equal(apiErrorMessage({ message: '陈默正在编辑本集', owner_user_id: 22 }, '请求失败'), '陈默正在编辑本集')
  assert.equal(apiErrorMessage({ message: '编辑版本已变化，请刷新' }, '请求失败'), '编辑版本已变化，请刷新')
})
