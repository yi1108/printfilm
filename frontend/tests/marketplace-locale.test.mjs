import test from 'node:test'
import assert from 'node:assert/strict'
import { applyLocale } from '../src/i18n/detect.ts'
import { marketText, marketFeedback } from '../src/features/marketplace/translate.ts'
import { explainMarketplaceError } from '../src/features/marketplace/messages.ts'
import { readFileSync } from 'node:fs'

test('language switches retranslate stored feedback while retaining parameters', () => {
  applyLocale('en', false)
  assert.equal(marketText('发布作品'), 'Publish work')
  assert.equal(marketFeedback('第12集版权授权已过期'), 'Rights authorization for episode 12 has expired.')
  assert.match(marketText('请确认更新「{0}」的新版本', ['中文用户标题']), /中文用户标题/)
  applyLocale('zh', false)
  assert.equal(marketFeedback('Rights authorization for episode 12 has expired.'), '第12集版权授权已过期')
})

test('English business errors are readable but internal exceptions are not', () => {
  applyLocale('en', false)
  assert.equal(explainMarketplaceError({code:'MARKETPLACE_CONTENT_CHANGED', message:'The unlock price has changed. Refresh and confirm the new price.'}, 409), 'The unlock price has changed. Refresh and confirm the new price.')
  assert.doesNotMatch(explainMarketplaceError('Internal Server Error', 500), /Internal Server Error|[\u3400-\u9fff]/)
  assert.doesNotMatch(explainMarketplaceError([{type:'string_too_long', loc:['body','title'], msg:'String should have at most 200 characters', ctx:{max_length:200}}], 422), /[\u3400-\u9fff]/)
  applyLocale('zh', false)
})

test('server feedback catalog stays synchronized', () => {
  assert.deepEqual(JSON.parse(readFileSync(new URL('../src/features/marketplace/locale-server.json', import.meta.url))), JSON.parse(readFileSync(new URL('../../backend/app/marketplace/locale_messages.json', import.meta.url))))
})
