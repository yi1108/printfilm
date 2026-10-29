import assert from 'node:assert/strict'
import test from 'node:test'
import {
  availableBillingPayTypes,
  billingPaymentReturn,
  billingReturnHint,
  stripeCheckoutUrl,
  stripeSkuQuote,
  billingOrderChargeLabel,
  paymentAmount,
} from '../src/lib/billingPayments.ts'

test('Stripe is offered only when the server enables it; unsupported providers stay unavailable', () => {
  assert.deepEqual(availableBillingPayTypes(['alipay', 'wxpay']), ['alipay', 'wxpay'])
  assert.deepEqual(availableBillingPayTypes(['stripe', 'stripe', 'unknown']), ['stripe'])
  assert.deepEqual(availableBillingPayTypes([]), [])
})

test('CNY, USD and HKD use the exact server quote without recalculating an exchange rate', () => {
  for (const [currency, amount, rate] of [['cny', 99000, '1'], ['usd', 13944, '7.1'], ['hkd', 108791, '0.91']]) {
    const quote = { payment_currency: currency, payment_amount_minor: amount, payment_exchange_rate: rate }
    assert.equal(stripeSkuQuote(quote), quote)
    assert.equal(paymentAmount(amount), `${Math.floor(amount / 100)}.${String(amount % 100).padStart(2, '0')}`)
  }
})

test('Missing or invalid quotes cannot make Stripe packages look free or use a CNY fallback', () => {
  for (const quote of [undefined, null, { payment_currency: 'usd', payment_amount_minor: 0 }, { payment_currency: 'usd', payment_amount_minor: -1 }, { payment_currency: 'usd', payment_amount_minor: 1.5 }, { payment_currency: 'usd', payment_amount_minor: NaN }, { payment_currency: 'eur', payment_amount_minor: 13944 }]) {
    assert.equal(stripeSkuQuote(quote), null)
  }
})

test('Order history shows its saved payment snapshot independently of CNY wallet amounts', () => {
  assert.equal(billingOrderChargeLabel({ amount_fen: 99000, payment_currency: 'usd', payment_amount_minor: 13944 }), 'USD 139.44')
  assert.equal(billingOrderChargeLabel({ amount_fen: 99000, payment_currency: 'hkd', payment_amount_minor: 108791 }), 'HKD 1087.91')
  assert.equal(billingOrderChargeLabel({ amount_fen: 99000, payment_currency: 'cny', payment_amount_minor: 99000 }), 'CNY 990.00')
  assert.equal(billingOrderChargeLabel({ amount_fen: 49000 }), 'CNY 490.00')
  assert.equal(billingOrderChargeLabel({ amount_fen: 49000, payment_currency: 'usd' }), '—')
  assert.equal(billingOrderChargeLabel({ amount_fen: 49000, payment_currency: 'eur', payment_amount_minor: 100 }), '—')
})

test('Checkout returns identify the order without claiming payment success', () => {
  const result = billingPaymentReturn(new URLSearchParams('payment=success&order=PF123&session_id=cs_test_123'))
  assert.deepEqual(result, { order: 'PF123', outcome: 'success' })
  assert.equal(billingReturnHint('pending', result.outcome), 'pricing.paymentPending')
  assert.equal(billingReturnHint('closed', result.outcome), 'pricing.paymentClosed')
  assert.equal(billingReturnHint('paid', result.outcome), 'pricing.paidOk')
  assert.equal(billingPaymentReturn(new URLSearchParams('payment=success')), null)
  assert.equal(billingPaymentReturn(new URLSearchParams('payment=paid&order=PF123')), null)
  for (const order of ['../wallet', 'PF123/close', 'PF123?x=1', 'PF123#fragment', '%2e%2e', 'x'.repeat(129)]) {
    assert.equal(billingPaymentReturn(new URLSearchParams({ payment: 'success', order })), null)
  }
})

test('A cancelled return still reports a payment confirmed by the server', () => {
  const result = billingPaymentReturn(new URLSearchParams('payment=cancelled&order=PF123'))
  assert.equal(billingReturnHint('pending', result.outcome), 'pricing.paymentCancelled')
  assert.equal(billingReturnHint('paid', result.outcome), 'pricing.paidOk')
})

test('Checkout navigation rejects script URLs, insecure URLs, credentials and misleading hosts', () => {
  assert.equal(stripeCheckoutUrl('https://checkout.stripe.com/c/pay/cs_test_123'), 'https://checkout.stripe.com/c/pay/cs_test_123')
  for (const value of [undefined, '', 'javascript:alert(1)', 'http://checkout.stripe.com/pay', 'https://checkout.stripe.com:8443/pay', 'https://checkout.stripe.com.evil.example/pay', 'https://checkout.stripe.com@evil.example/pay', 'https://user@checkout.stripe.com/pay']) {
    assert.equal(stripeCheckoutUrl(value), null)
  }
})
