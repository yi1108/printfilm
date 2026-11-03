import test from 'node:test'
import assert from 'node:assert/strict'
import { appAmountFen, appMoney, appRecordFields, appRecordIds } from '../src/features/marketplace/appPresentation.ts'

test('App运营只显示业务白名单，Apple签名和密钥不会被任意序列化', () => {
  const fields = appRecordFields({ product_id: 'video.coins.600', amount_fen: 600, environment: 'Sandbox', raw_payload: { signedPayload: 'private' }, signed_transaction_info: 'private', app_account_token: 'private', private_key: 'private', nested: { amount_fen: 999 } })
  assert.deepEqual(fields, [['苹果商品编号', 'video.coins.600'], ['金额', '¥6.00'], ['交易环境', '沙箱']])
  assert.ok(!JSON.stringify(fields).includes('private'))
})

test('人工财务输入按整数分精确解析，拒绝误差和非法金额', () => {
  assert.equal(appAmountFen('0.29'), 29)
  assert.equal(appAmountFen('100.01'), 10001)
  assert.equal(appAmountFen('0'), 0)
  for (const invalid of ['', '-1', '1.001', '1e3', 'Infinity', '9007199254740991']) assert.throws(() => appAmountFen(invalid))
  assert.throws(() => appAmountFen('0', false))
  assert.equal(appAmountFen('-0.29', true, true), -29)
  assert.equal(appAmountFen('-100.01', true, true), -10001)
  for (const invalid of ['-1.001', '-1e3', '--1', '-9007199254740991']) assert.throws(() => appAmountFen(invalid, true, true))
})

test('关联财务明细使用唯一正整数编号，不接受空值或重复编号', () => {
  assert.deepEqual(appRecordIds('1，2, 3\n4'), [1, 2, 3, 4])
  for (const invalid of ['', '1,1', '0', '-2', '1.2', 'abc', '9007199254740992']) assert.throws(() => appRecordIds(invalid))
})

test('平台实际净收益可为负，不将渠道成本亏损误报为零', () => {
  assert.equal(appMoney(-120), '¥-1.20')
  assert.equal(appMoney(undefined), '—')
  assert.equal(appMoney(Number.NaN), '—')
})

test('支付、解锁、打款和媒体状态按业务语义展示，不混淆财务状态', () => {
  assert.deepEqual(appRecordFields({ status: 'paid', settlement_status: 'pending' }, 'transactions'), [['状态', '已付款'], ['对账状态', '待对账']])
  assert.deepEqual(appRecordFields({ status: 'paid' }, 'unlock-orders'), [['状态', '已解锁']])
  assert.deepEqual(appRecordFields({ status: 'revoked' }, 'unlock-orders'), [['状态', '已撤销']])
  assert.deepEqual(appRecordFields({ status: 'paid' }, 'payouts'), [['状态', '已打款']])
  assert.deepEqual(appRecordFields({ status: 'offset_only' }, 'payouts'), [['状态', '已全额抵扣']])
  assert.deepEqual(appRecordFields({ status: 'done' }, 'media'), [['状态', '已就绪']])
})
