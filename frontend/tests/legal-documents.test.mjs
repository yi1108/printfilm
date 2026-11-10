import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

import { getLegalDoc, LEGAL_DOCS } from '../src/lib/legalDocuments.ts'

const root = new URL('../', import.meta.url)

async function text(path) {
  return readFile(new URL(path, root), 'utf8')
}

test('Terms 与 Privacy 作为公开 React 路由接入应用', async () => {
  const app = await text('src/App.tsx')
  assert.match(app, /import \{ PrivacyPage, TermsPage \} from '\.\/pages\/LegalDocPage'/)
  assert.match(app, /path=["']\/terms["'] element=\{<TermsPage \/>/)
  assert.match(app, /path=["']\/privacy["'] element=\{<PrivacyPage \/>/)
})

test('React 法务页使用 AppShell 和结构化正文，不嵌套独立 HTML', async () => {
  const page = await text('src/pages/LegalDocPage.tsx')
  assert.match(page, /AppShell/)
  assert.match(page, /pf-legal-page/)
  assert.match(page, /LEGAL_DOCS|getLegalDoc/)
  assert.match(page, /getLegalDoc\(slug, locale\)/)
  assert.doesNotMatch(page, /dangerouslySetInnerHTML|<iframe|srcDoc/)
})

test('参考文件的全部条款转换为结构化内容且保留关键规则', () => {
  assert.equal(LEGAL_DOCS.terms.title, 'Terms of Use')
  assert.equal(LEGAL_DOCS.privacy.title, 'Privacy Policy')
  assert.equal(LEGAL_DOCS.terms.updatedAt, 'November 9, 2026')
  assert.equal(LEGAL_DOCS.privacy.updatedAt, 'November 9, 2026')
  assert.equal(LEGAL_DOCS.terms.sections.length, 20)
  assert.equal(LEGAL_DOCS.privacy.sections.length, 13)

  const terms = JSON.stringify(LEGAL_DOCS.terms)
  const privacy = JSON.stringify(LEGAL_DOCS.privacy)
  assert.match(terms, /within 24 hours/)
  assert.match(terms, /Apple and Apple’s subsidiaries are third-party beneficiaries/)
  assert.match(privacy, /normally within 30 days/)
  assert.match(privacy, /typically for up to 7 years/)
  assert.match(privacy, /password and the confirmation word/)
  const firstSection = JSON.stringify(LEGAL_DOCS.terms.sections[0])
  const listIndex = firstSection.indexOf('A Watch feed')
  const followingIndex = firstSection.indexOf('Some features are available')
  assert.ok(listIndex > firstSection.indexOf('Depending on the feature'))
  assert.ok(followingIndex > listIndex, '列表后的段落必须保留在列表之后')
})

test('Terms 与 Privacy 跟随界面语言提供结构一致的中英文版本', () => {
  for (const slug of ['terms', 'privacy']) {
    const zh = getLegalDoc(slug, 'zh')
    const en = getLegalDoc(slug, 'en')
    assert.notEqual(zh.title, en.title)
    assert.equal(zh.sections.length, en.sections.length)
    zh.sections.forEach((section, index) => {
      assert.equal(section.blocks.length, en.sections[index].blocks.length)
      assert.deepEqual(
        section.blocks.map((block) => block.type),
        en.sections[index].blocks.map((block) => block.type),
      )
    })
  }
  const terms = getLegalDoc('terms', 'zh')
  const privacy = getLegalDoc('privacy', 'zh')
  assert.equal(terms.title, '用户协议')
  assert.equal(privacy.title, '隐私政策')
  assert.match(JSON.stringify(terms), /24 小时/)
  assert.match(JSON.stringify(terms), /Apple 及其子公司是本节条款的第三方受益人/)
  assert.match(JSON.stringify(privacy), /通常.*30 天/)
  assert.match(JSON.stringify(privacy), /通常.*7 年/)
  assert.match(JSON.stringify(privacy), /密码和页面显示的确认词/)
})

test('法务内容支持站内链接、邮箱和重点文本的安全渲染', async () => {
  const page = await text('src/pages/LegalDocPage.tsx')
  const content = await text('src/lib/legalDocuments.ts')
  assert.match(content, /\[Privacy Policy\]\(\/privacy\)/)
  assert.match(content, /\[kefu@gitcc\.com\]\(mailto:kefu@gitcc\.com\)/)
  assert.match(content, /0755-27337894/)
  assert.match(content, /gitcc188/)
  assert.match(content, /\*\*Account information\.\*\*/)
  assert.match(page, /function LegalInlineText/)
})

test('法务页面复用系统背景、文字、边框、卡片和阴影设计令牌', async () => {
  const styles = await text('src/styles/printfilm.css')
  const legal = styles.match(/\/\* Legal documents \*\/(?<body>[\s\S]*?)(?=\/\* Contact channels \*\/)/)
  assert.ok(legal, '缺少独立法务样式分区')
  assert.match(legal.groups.body, /var\(--pf-bg\)/)
  assert.match(legal.groups.body, /var\(--pf-ink\)/)
  assert.match(legal.groups.body, /var\(--pf-muted\)/)
  assert.match(legal.groups.body, /var\(--pf-line\)/)
  assert.match(legal.groups.body, /var\(--pf-shadow\)/)
  assert.match(legal.groups.body, /max-width: 820px/)
  assert.doesNotMatch(legal.groups.body, /#fbf7f8|#eadfe3|#c2410c/)
})

test('站内 Legal 入口使用 React 文档导航', async () => {
  const sources = await Promise.all([
    text('src/components/layout/AppShell.tsx'),
    text('src/pages/ContactPage.tsx'),
    text('src/pages/HomePage.tsx'),
    text('src/pages/HelpPage.tsx'),
    text('src/pages/PricingPage.tsx'),
  ])
  for (const source of sources) {
    assert.doesNotMatch(source, /<a[^>]+href=["']\/(?:terms|privacy)["']/)
  }
})

test('构建配置不再提供独立 Legal HTML', async () => {
  const [nginx, vite, dockerfile] = await Promise.all([
    text('nginx.conf'),
    text('vite.config.ts'),
    text('Dockerfile'),
  ])
  assert.doesNotMatch(nginx, /alias \/usr\/share\/nginx\/html\/(?:terms|privacy)\.html/)
  assert.doesNotMatch(vite, /serveLegalDocuments|legalDocuments/)
  assert.doesNotMatch(dockerfile, /chmod 0644 .*terms\.html/)
  await assert.rejects(readFile(new URL('public/terms.html', root)))
  await assert.rejects(readFile(new URL('public/privacy.html', root)))
})

test('Vite 对 Legal 路径返回 React 应用入口而不是独立文档', async (t) => {
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

  for (const name of ['terms', 'privacy']) {
    const response = await fetch(`http://127.0.0.1:${address.port}/${name}`, { redirect: 'manual' })
    assert.equal(response.status, 200)
    const html = await response.text()
    assert.match(html, /id=["']root["']/)
    assert.match(html, /\/src\/main\.tsx/)
  }
})
