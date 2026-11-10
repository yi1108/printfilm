import test from 'node:test'
import assert from 'node:assert/strict'
import { operationInteger, displayMetricsInput } from '../src/features/marketplace/operationInputs.ts'

test('运营数量与置顶权重只接受范围内整数，不静默舍入', () => {
  assert.equal(operationInteger('100'), 100)
  assert.equal(operationInteger('0'), 0)
  assert.equal(operationInteger('9999', 9999), 9999)
  for (const value of ['', '1e3', '1.2', '-1', 'NaN', '9007199254740992']) assert.throws(() => operationInteger(value))
  assert.throws(() => operationInteger('10000', 9999))
  assert.throws(() => operationInteger('1000000001'))
})

test('调整展示数量保持原始整数，不允许低于真实互动', () => {
  const real = { like_count: 20, favorite_count: 10, share_count: 3 }
  assert.deepEqual(displayMetricsInput({ like_count: '2500', favorite_count: '2200', share_count: '1000' }, real), { like_count: 2500, favorite_count: 2200, share_count: 1000 })
  assert.deepEqual(displayMetricsInput(real, real), real)
  assert.throws(() => displayMetricsInput({ ...real, like_count: '19' }, real), /不能小于真实数量/)
  assert.throws(() => displayMetricsInput({ ...real, share_count: '2e3' }, real))
})
