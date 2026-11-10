import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  BRAND_NAME,
  COMPANY_NAME_EN,
  COMPANY_NAME_ZH,
  SUPPORT_EMAIL,
  SUPPORT_PHONE,
  WECHAT_ID,
} from '../src/lib/siteContact.ts'
import { getLegalDoc } from '../src/lib/legalDocuments.ts'
import { zhPages } from '../src/i18n/locales/zh/pages.ts'
import { enPages } from '../src/i18n/locales/en/pages.ts'

const messages = { zh: zhPages, en: enPages }

const SOURCE_ROOT = new URL('../src/', import.meta.url)

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = new URL(`${entry.name}/`, directory)
    if (entry.isDirectory()) files.push(...await sourceFiles(path))
    else if (/\.(?:ts|tsx|json)$/.test(entry.name)) files.push(new URL(entry.name, directory))
  }
  return files
}

test('全站主体、品牌与客服信息使用唯一正确配置', () => {
  assert.equal(BRAND_NAME, 'PRINTFILM')
  assert.equal(COMPANY_NAME_ZH, '深圳德沛开源数据科技有限公司')
  assert.equal(COMPANY_NAME_EN, 'Shenzhen Depei Open Source Data Technology Co., Ltd.')
  assert.equal(SUPPORT_EMAIL, 'kefu@gitcc.com')
  assert.equal(SUPPORT_PHONE, '0755-27337894')
  assert.equal(WECHAT_ID, 'gitcc188')
})

test('中英文法务使用正确公司、品牌、邮箱与联系电话', () => {
  for (const slug of ['terms', 'privacy']) {
    const zh = JSON.stringify(getLegalDoc(slug, 'zh'))
    const en = JSON.stringify(getLegalDoc(slug, 'en'))
    assert.match(zh, /深圳德沛开源数据科技有限公司/)
    assert.doesNotMatch(zh, /深圳市德配开源数据科技有限公司/)
    assert.match(zh, /kefu@gitcc\.com/)
    assert.match(zh, /0755-27337894/)
    assert.match(zh, /gitcc188/)
    assert.match(en, /Shenzhen Depei Open Source Data Technology Co\., Ltd\./)
    assert.match(en, /kefu@gitcc\.com/)
    assert.match(en, /0755-27337894/)
    assert.match(en, /gitcc188/)
    assert.doesNotMatch(en, /PrintFilm/)
  }
})

test('联系我们同时提供正确邮箱、电话和微信，表单发送到新邮箱', async () => {
  for (const locale of ['zh', 'en']) {
    const channels = messages[locale].contact.channels
    assert.ok(channels.some((channel) => channel.href === 'mailto:kefu@gitcc.com'))
    assert.ok(channels.some((channel) => channel.href === 'tel:+8675527337894'))
    assert.ok(channels.some((channel) => channel.copyText === 'gitcc188'))
  }
  const page = await readFile(new URL('pages/ContactPage.tsx', SOURCE_ROOT), 'utf8')
  assert.match(page, /mailto:\$\{SUPPORT_EMAIL\}/)
  assert.match(page, /SUPPORT_EMAIL/)
  assert.doesNotMatch(page, /support@printfilm\.com/)
})

test('全站页脚和微信复制入口引用统一客服配置', async () => {
  const footer = await readFile(new URL('components/layout/AppShell.tsx', SOURCE_ROOT), 'utf8')
  for (const key of ['COMPANY_NAME_ZH', 'BRAND_NAME', 'SUPPORT_EMAIL', 'SUPPORT_PHONE', 'WECHAT_ID']) {
    assert.match(footer, new RegExp(`\\{${key}\\}`))
  }
  const fab = await readFile(new URL('components/layout/WeChatGroupFab.tsx', SOURCE_ROOT), 'utf8')
  assert.match(fab, /import \{ WECHAT_ID \} from '\.\.\/\.\.\/lib\/siteContact'/)
  assert.match(fab, /clipboard\.writeText\(WECHAT_ID\)/)
})

test('前端源码不含旧公司名、旧客服信息或混合大小写品牌', async () => {
  const files = await sourceFiles(SOURCE_ROOT)
  assert.ok(files.length > 100)
  for (const file of files) {
    const source = await readFile(file, 'utf8')
    assert.doesNotMatch(source, /深圳市德配开源数据科技有限公司|support@printfilm\.com|gitpp88|PrintFilm/, file.pathname)
  }
})
