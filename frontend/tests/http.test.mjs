import assert from 'node:assert/strict'
import { test } from 'node:test'
import { apiErrorMessage, createHttpTransport, resolveApiBase } from '../src/api/http.ts'
import { getMediaPriceVersion, setMediaPriceVersion } from '../src/lib/mediaPriceVersion.ts'

/** 创建带可观察 token 的客户端；错误策略不依赖浏览器弹窗。 */
function testTransport(getToken = () => 'first-token') {
  return createHttpTransport({
    baseUrl: 'http://api.test',
    getToken,
    onError: (response, detail) => {
      throw new Error(apiErrorMessage(detail, response.statusText || '请求失败'))
    },
  })
}

test('API 地址保留显式同源、配置值和 LAN 开发默认值', () => {
  const location = { protocol: 'https:', hostname: 'studio.test' }
  assert.equal(resolveApiBase('', location), '')
  assert.equal(resolveApiBase('https://backend.test', location), 'https://backend.test')
  assert.equal(resolveApiBase(undefined, location), 'https://studio.test:8000')
  assert.equal(resolveApiBase(null), 'http://127.0.0.1:8000')
})

test('JSON 请求保留方法和正文，并在登录变化后重新读取 token', async (t) => {
  const calls = []
  let token = 'first-token'
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ url, init })
    return Response.json({ ok: true })
  })
  const client = testTransport(() => token)
  assert.deepEqual(await client.json('/api/projects', { method: 'POST', body: '{"title":"测试"}' }), { ok: true })
  token = null
  await client.json('/api/auth/me')
  assert.equal(calls[0].url, 'http://api.test/api/projects')
  assert.equal(calls[0].init.method, 'POST')
  assert.equal(calls[0].init.body, '{"title":"测试"}')
  assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer first-token')
  assert.equal(calls[0].init.headers.get('Content-Type'), 'application/json')
  assert.equal(calls[1].init.headers.has('Authorization'), false)
})

test('调用方的 Headers 和键值数组均可覆盖默认请求头', async (t) => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    calls.push(init.headers)
    return Response.json({})
  })
  const client = testTransport()
  await client.json('/headers', { headers: new Headers({ authorization: 'Custom token', 'X-Trace': 'trace' }) })
  await client.json('/tuples', { headers: [['Content-Type', 'application/custom']] })
  assert.equal(calls[0].get('Authorization'), 'Custom token')
  assert.equal(calls[0].get('X-Trace'), 'trace')
  assert.equal(calls[1].get('Content-Type'), 'application/custom')
})

test('上传保留 FormData 并由平台生成 multipart boundary', async (t) => {
  const body = new FormData()
  body.append('file', new Blob(['test']), 'asset.txt')
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(init.body, body)
    assert.equal(init.headers.has('Content-Type'), false)
    const actualRequest = new Request(url, init)
    assert.match(actualRequest.headers.get('Content-Type'), /^multipart\/form-data; boundary=/)
    assert.equal(actualRequest.headers.get('Authorization'), 'Bearer first-token')
    return Response.json({ uploaded: true })
  })
  assert.deepEqual(await testTransport().json('/upload', { method: 'POST', body }), { uploaded: true })
})

test('非 JSON 下载返回可读取的原始响应', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('zip-bytes', {
    headers: { 'Content-Disposition': 'attachment; filename="project.zip"' },
  }))
  const response = await testTransport().response('/download')
  assert.equal(response.headers.get('Content-Disposition'), 'attachment; filename="project.zip"')
  assert.equal(await response.text(), 'zip-bytes')
})

test('FastAPI 校验数组及空错误详情生成可读回退文案', () => {
  assert.equal(apiErrorMessage([{ msg: '字段缺失' }, { msg: '格式错误' }], '请求失败'), '字段缺失; 格式错误')
  assert.equal(apiErrorMessage([null, { type: 'unknown' }], '请求失败'), 'null; {"type":"unknown"}')
  for (const detail of ['', [], null, undefined, {}]) {
    assert.equal(apiErrorMessage(detail, '请求失败'), '请求失败')
  }
})

test('请求失败交给业务错误策略，并保留状态和 detail', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: '余额不足' }, { status: 402 }))
  await assert.rejects(testTransport().json('/generate', undefined, (response, detail) => {
    assert.equal(response.status, 402)
    assert.equal(detail, '余额不足')
    throw new Error('业务计费处理')
  }), /业务计费处理/)
})

test('网关返回非 JSON、null 或空 detail 时错误处理仍可运行', async (t) => {
  for (const body of ['upstream failed', 'null', '{}']) {
    t.mock.method(globalThis, 'fetch', async () => new Response(body, { status: 502, statusText: 'Bad Gateway' }))
    await assert.rejects(testTransport().json('/failed'), /Bad Gateway/)
    t.mock.restoreAll()
  }
})
test('目录中的价格版本随生成请求提交', async (t) => {
  const originalVersion = getMediaPriceVersion()
  t.after(() => setMediaPriceVersion(originalVersion))
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ url, init })
    return Response.json(url.endsWith('/api/media-models') ? { price_version: 7 } : { ok: true })
  })
  const transport = testTransport()
  await transport.json('/api/media-models')
  await transport.json('/api/generate', { method: 'POST', body: '{}' })
  assert.equal(calls[1].init.headers.get('X-Media-Price-Version'), '7')
})

test('价格冲突通知目录刷新，但不自动重发生成请求', async (t) => {
  const previous = globalThis.window
  const window = new EventTarget()
  globalThis.window = window
  t.after(() => { if (previous === undefined) delete globalThis.window; else globalThis.window = previous })
  let refreshes = 0
  let requests = 0
  window.addEventListener('media-prices-changed', () => { refreshes += 1 })
  t.mock.method(globalThis, 'fetch', async () => {
    requests += 1
    return Response.json({ detail: '价格已更新' }, { status: 409 })
  })
  await assert.rejects(() => testTransport().json('/api/generate', { method: 'POST', body: '{}' }), /价格已更新/)
  assert.equal(refreshes, 1)
  assert.equal(requests, 1)
})

test('画布和工作流冲突保留错误，但不触发价格刷新或重复请求', async (t) => {
  const previous = globalThis.window
  const window = new EventTarget()
  globalThis.window = window
  t.after(() => { if (previous === undefined) delete globalThis.window; else globalThis.window = previous })
  let refreshes = 0
  let requests = 0
  window.addEventListener('media-prices-changed', () => { refreshes += 1 })
  t.mock.method(globalThis, 'fetch', async () => {
    requests += 1
    return Response.json({ detail: { message: '画布版本已变化，请刷新后重试' } }, { status: 409 })
  })
  await assert.rejects(() => testTransport().json('/api/printfilm-studio/projects/431/workflow'), /画布版本已变化/)
  assert.equal(refreshes, 0)
  assert.equal(requests, 1)
})
