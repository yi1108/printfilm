import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createAccountRequests } from '../src/api/account.ts'
import { createHttpTransport } from '../src/api/http.ts'

test('注销请求提交密码和页面显示的确认词', async () => {
  let captured
  const account = createAccountRequests(async (path, init) => {
    captured = { path, init }
    return { ok: true }
  })

  assert.deepEqual(await account.closeAccount({ password: 'secret', confirmation: 'DELETE' }), { ok: true })
  assert.equal(captured.path, '/api/auth/close-account')
  assert.equal(captured.init.method, 'POST')
  assert.deepEqual(JSON.parse(captured.init.body), { password: 'secret', confirmation: 'DELETE' })
})

test('真实鉴权传输层为注销请求附带 Bearer 和 JSON 请求头', async (t) => {
  let captured
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    captured = { url, init }
    return Response.json({ ok: true })
  })
  const transport = createHttpTransport({
    baseUrl: 'https://api.printfilm.test',
    getToken: () => 'existing-access-token',
    onError: (response, detail) => { throw new Error(String(detail || response.status)) },
  })
  const account = createAccountRequests(transport.json)

  await account.closeAccount({ password: 'secret', confirmation: 'DELETE' })

  assert.equal(captured.url, 'https://api.printfilm.test/api/auth/close-account')
  assert.equal(captured.init.method, 'POST')
  assert.equal(new Headers(captured.init.headers).get('Authorization'), 'Bearer existing-access-token')
  assert.equal(new Headers(captured.init.headers).get('Content-Type'), 'application/json')
  const apiSource = await readFile(new URL('../src/api.ts', import.meta.url), 'utf8')
  assert.match(apiSource, /createAccountRequests\(request\)/)
  assert.match(apiSource, /closeAccount:\s*accountRequests\.closeAccount/)
})

test('设置页提供明确的危险操作确认表单，而非 ComingSoon 占位按钮', async () => {
  const root = new URL('../', import.meta.url)
  const read = (path) => readFile(new URL(path, root), 'utf8')
  const [profile, closure, zh, en] = await Promise.all([
    read('src/pages/settings/AccountProfileCard.tsx'),
    read('src/pages/settings/CloseAccountCard.tsx'),
    read('src/i18n/locales/zh/shell.ts'),
    read('src/i18n/locales/en/shell.ts'),
  ])
  assert.match(profile, /<CloseAccountCard/)
  assert.doesNotMatch(profile, /ComingSoon/)
  assert.match(closure, /type=["']password["']/)
  assert.match(closure, /autoComplete=["']current-password["']/)
  assert.match(closure, /closeConfirmationWord/)
  assert.match(closure, /api\.closeAccount/)
  assert.match(closure, /localStorage\.removeItem\(["']token["']\)/)
  assert.match(closure, /USER_UPDATED_EVENT/)
  assert.match(zh, /closeConfirmationWord:\s*'DELETE'/)
  assert.match(en, /closeConfirmationWord:\s*'DELETE'/)
  assert.match(zh, /必要账单/)
  assert.match(en, /billing records/i)
})
