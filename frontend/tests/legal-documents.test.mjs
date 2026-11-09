import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const root = new URL('../', import.meta.url)

async function text(path) {
  return readFile(new URL(path, root), 'utf8')
}

for (const [name, sha256] of [
  ['terms', '5d9054a6159496cb5eaddcf2b1ff19e72c8d9f9615b0e863b45f996f56e2ab98'],
  ['privacy', 'b340e998c4e355ec55406ad5853754b0b24cf764a34702a7d4233833fedccad8'],
]) {
  test(`/${name} 发布原始完整 HTML，文件名与字节均不改变`, async () => {
    const bytes = await readFile(new URL(`public/${name}.html`, root))
    assert.equal(createHash('sha256').update(bytes).digest('hex'), sha256)
    const html = bytes.toString('utf8')
    assert.match(html, /^<!DOCTYPE html>/i)
    assert.match(html, /<meta[^>]+charset=["']?utf-8/i)
    assert.doesNotMatch(html, /id=["']root["']/i)
  })

  test(`nginx 的 /${name} 精确映射到独立 HTML，而非 SPA 回退`, async () => {
    const nginx = await text('nginx.conf')
    const route = nginx.match(new RegExp(`location = /${name} \\{(?<body>[\\s\\S]*?)\\}`))
    assert.ok(route, `缺少 location = /${name}`)
    assert.match(route.groups.body, new RegExp(`alias\\s+/usr/share/nginx/html/${name}\\.html;`))
    assert.match(route.groups.body, /default_type\s+text\/html;/)
    assert.match(route.groups.body, /charset\s+utf-8;/)
    assert.doesNotMatch(route.groups.body, /proxy_pass|index\.html|try_files/)
  })

  test(`Vite 开发服务直接返回 /${name} 静态文件`, async () => {
    const vite = await text('vite.config.ts')
    assert.match(vite, /configureServer/)
    assert.match(vite, new RegExp(`['"\`]/${name}['"\`]`))
    assert.match(vite, new RegExp(`${name}\\.html`))
    assert.match(vite, /text\/html;\s*charset=utf-8/)
  })
}

test('Vite 实际响应无需登录、无重定向且逐字节匹配原 Legal 文件', async (t) => {
  const server = await createServer({
    root: fileURLToPath(root),
    configFile: fileURLToPath(new URL('vite.config.ts', root)),
    logLevel: 'error',
    server: { host: '127.0.0.1', port: 0, strictPort: true },
  })
  t.after(async () => { await server.close() })
  await server.listen()
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')

  for (const [name, sha256] of [
    ['terms', '5d9054a6159496cb5eaddcf2b1ff19e72c8d9f9615b0e863b45f996f56e2ab98'],
    ['privacy', 'b340e998c4e355ec55406ad5853754b0b24cf764a34702a7d4233833fedccad8'],
  ]) {
    const response = await fetch(`http://127.0.0.1:${address.port}/${name}`, { redirect: 'manual' })
    assert.equal(response.status, 200)
    assert.equal(response.headers.get('content-type'), 'text/html; charset=utf-8')
    const bytes = Buffer.from(await response.arrayBuffer())
    assert.equal(createHash('sha256').update(bytes).digest('hex'), sha256)
  }
})

test('Git 在任何平台检出 Legal 文件时都禁用换行符转换', async () => {
  const attributes = await text('.gitattributes')
  for (const name of ['terms', 'privacy']) {
    assert.match(attributes, new RegExp(`public/${name}\\.html\\s+-text(?:\\s|$)`))
  }
})

test('React 不再接管两个独立 Legal 路由，站内链接执行文档导航', async () => {
  const app = await text('src/App.tsx')
  assert.doesNotMatch(app, /path=["']\/terms["']/)
  assert.doesNotMatch(app, /path=["']\/privacy["']/)
  assert.doesNotMatch(app, /LegalDocPage/)
  const sources = await Promise.all([
    text('src/components/layout/AppShell.tsx'),
    text('src/pages/ContactPage.tsx'),
    text('src/pages/HomePage.tsx'),
    text('src/pages/HelpPage.tsx'),
    text('src/pages/PricingPage.tsx'),
  ])
  for (const source of sources) {
    assert.doesNotMatch(source, /<Link[^>]+to=["']\/(?:terms|privacy)["']/)
  }
})
