import test from 'node:test'
import assert from 'node:assert/strict'
import { orderPaymentLabel } from '../src/lib/orderPayment.ts'

test('Foreign payment labels use the saved currency amount rather than the CNY package amount', () => {
  assert.equal(orderPaymentLabel({ amount_fen: 99000, payment_currency: 'usd', payment_amount_minor: 13750 }), 'USD 137.50')
  assert.equal(orderPaymentLabel({ amount_fen: 99000, payment_currency: 'hkd', payment_amount_minor: 107609 }), 'HKD 1076.09')
  assert.equal(orderPaymentLabel({ amount_fen: 99000, payment_currency: 'cny', payment_amount_minor: 99000 }), 'CNY 990.00')
})

test('Legacy snapshots fall back to CNY; a missing foreign amount never relabels CNY as foreign currency', () => {
  assert.equal(orderPaymentLabel({ amount_fen: 49000 }), 'CNY 490.00')
  assert.equal(orderPaymentLabel({ amount_fen: 49000, payment_currency: null, payment_amount_minor: null }), 'CNY 490.00')
  assert.equal(orderPaymentLabel({ amount_fen: 49000, payment_currency: 'usd' }), 'USD —')
})
