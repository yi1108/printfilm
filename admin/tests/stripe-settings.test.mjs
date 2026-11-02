import test from 'node:test'
import assert from 'node:assert/strict'
import { stripeRateInputError, stripeSettingsPatch, stripeSettingsReady } from '../src/lib/stripeSettings.ts'

const configured = { stripe_enabled: true, stripe_frontend_url: 'https://app.example.com', has_stripe_secret_key: true, has_stripe_webhook_secret: true, stripe_usd_cny_rate: '7.2' }
const blank = { secretKey: '', webhookSecret: '', clearSecretKey: false, clearWebhookSecret: false }

test('Saving unrelated payment changes omits existing Stripe secrets from JSON', () => {
  const patch = JSON.parse(JSON.stringify(stripeSettingsPatch(configured, blank)))
  assert.equal(patch.stripe_enabled, true)
  assert.equal(patch.stripe_frontend_url, 'https://app.example.com')
  assert.equal(Object.hasOwn(patch, 'stripe_secret_key'), false)
  assert.equal(Object.hasOwn(patch, 'stripe_webhook_secret'), false)
  assert.equal(patch.clear_stripe_secret_key, false)
  assert.equal(patch.clear_stripe_webhook_secret, false)
  assert.equal(stripeSettingsReady(configured, blank), true)
})

test('Replacing Stripe credentials submits only new trimmed drafts', () => {
  const patch = stripeSettingsPatch({ ...configured, stripe_frontend_url: ' https://new.example.com ' }, { ...blank, secretKey: ' sk_test_new ', webhookSecret: ' whsec_new ' })
  assert.equal(patch.stripe_secret_key, 'sk_test_new')
  assert.equal(patch.stripe_webhook_secret, 'whsec_new')
  assert.equal(patch.stripe_frontend_url, 'https://new.example.com')
})

test('Explicit clear takes precedence over stale draft and marks Stripe unready', () => {
  const draft = { ...blank, secretKey: 'sk_test_stale', webhookSecret: 'whsec_stale', clearSecretKey: true, clearWebhookSecret: true }
  const patch = JSON.parse(JSON.stringify(stripeSettingsPatch({ ...configured, stripe_enabled: false }, draft)))
  assert.equal(patch.stripe_enabled, false)
  assert.equal(patch.clear_stripe_secret_key, true)
  assert.equal(patch.clear_stripe_webhook_secret, true)
  assert.equal(Object.hasOwn(patch, 'stripe_secret_key'), false)
  assert.equal(Object.hasOwn(patch, 'stripe_webhook_secret'), false)
  assert.equal(stripeSettingsReady(configured, draft), false)
})

test('Readiness requires enablement, both credentials and a frontend address', () => {
  assert.equal(stripeSettingsReady({ ...configured, stripe_enabled: false }, blank), false)
  assert.equal(stripeSettingsReady({ ...configured, stripe_frontend_url: '' }, blank), false)
  assert.equal(stripeSettingsReady({ ...configured, has_stripe_secret_key: false }, blank), false)
  assert.equal(stripeSettingsReady({ ...configured, has_stripe_webhook_secret: false }, blank), false)
  assert.equal(stripeSettingsReady({ ...configured, has_stripe_secret_key: false, has_stripe_webhook_secret: false }, { ...blank, secretKey: 'sk_test_new', webhookSecret: 'whsec_new' }), true)
  assert.equal(stripeSettingsReady({ ...configured, has_stripe_secret_key: false }, { ...blank, secretKey: '   ' }), false)
})

test('An empty Stripe return site uses the configured public site without persisting a duplicate value', () => {
  const fallback = { ...configured, stripe_frontend_url: '', public_base_url: 'https://app.example.com' }
  assert.equal(stripeSettingsReady(fallback, blank), true)
  assert.equal(stripeSettingsPatch(fallback, blank).stripe_frontend_url, '')
  assert.equal(stripeSettingsReady({ ...fallback, public_base_url: '   ' }, blank), false)
})

test('Saving legacy currency settings always uses the website language rule', () => {
  for (const currency of ['cny', 'usd', 'hkd', 'auto']) {
    const patch = stripeSettingsPatch({ ...configured, stripe_currency: currency, stripe_hkd_cny_rate: '0.92' }, blank)
    assert.equal(patch.stripe_currency, 'auto')
    assert.equal(Object.hasOwn(patch, 'stripe_hkd_cny_rate'), false)
    assert.equal(stripeSettingsReady({ ...configured, stripe_currency: currency, stripe_usd_cny_rate: '' }, blank), false)
    assert.equal(stripeSettingsReady({ ...configured, stripe_currency: currency }, blank), true)
  }
})

test('Rate drafts preserve exact decimal strings and keep blank rates savable', () => {
  const patch = stripeSettingsPatch({ ...configured, stripe_currency: 'usd', stripe_usd_cny_rate: ' 7.123456 ', stripe_hkd_cny_rate: '' }, blank)
  assert.equal(patch.stripe_currency, 'auto')
  assert.equal(patch.stripe_usd_cny_rate, '7.123456')
  assert.equal(Object.hasOwn(patch, 'stripe_hkd_cny_rate'), false)
  assert.equal(stripeRateInputError(''), undefined)
  assert.equal(stripeRateInputError('0.000001'), undefined)
  assert.equal(stripeRateInputError('1000000.000000'), undefined)
})

test('Malformed, nonpositive, excessive or imprecise rate drafts cannot mark Stripe ready', () => {
  for (const value of ['NaN', 'Infinity', '-7.2', '0', '1000000.000001', '7.1234567', '7.', '1e3', '7,2']) {
    assert.ok(stripeRateInputError(value), value)
    assert.equal(stripeSettingsReady({ ...configured, stripe_currency: 'usd', stripe_usd_cny_rate: value }, blank), false)
  }
})

test('Language mode only needs a USD rate and preserves it in the admin patch', () => {
  assert.equal(stripeSettingsReady({ ...configured, stripe_currency: 'auto', stripe_usd_cny_rate: '' }, blank), false)
  assert.equal(stripeSettingsReady({ ...configured, stripe_currency: 'auto', stripe_usd_cny_rate: '7.2' }, blank), true)
  const patch = stripeSettingsPatch({ ...configured, stripe_currency: 'auto', stripe_usd_cny_rate: ' 7.123456 ' }, blank)
  assert.equal(patch.stripe_currency, 'auto')
  assert.equal(patch.stripe_usd_cny_rate, '7.123456')
})
