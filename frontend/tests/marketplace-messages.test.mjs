import test from 'node:test'
import assert from 'node:assert/strict'
import { explainMarketplaceError, marketplaceErrorCode } from '../src/features/marketplace/messages.ts'

test('纯业务错误码转为用户可操作的提示，错误码仍可供排查', () => {
  const detail = 'MARKETPLACE_REVENUE_CONFIG_REQUIRED'
  assert.match(explainMarketplaceError(detail, 409), /平台投放收益暂未开放/)
  assert.equal(marketplaceErrorCode(detail), detail)
  assert.doesNotMatch(explainMarketplaceError('MARKETPLACE_FUTURE_ERROR', 503), /MARKETPLACE_/)
})

test('带具体原因的分集错误保留原因并移除编码前缀', () => {
  const detail = 'MARKETPLACE_SOURCE_NOT_READY:第3集仍有分镜未完成'
  assert.equal(explainMarketplaceError(detail, 409), '第3集仍有分镜未完成')
  assert.equal(marketplaceErrorCode(detail), 'MARKETPLACE_SOURCE_NOT_READY')
  assert.equal(explainMarketplaceError({ code: 'MARKETPLACE_SOURCE_CHANGED', message: '源分集已更新，请重新选择' }), '源分集已更新，请重新选择')
})

test('结构化存储错误、空详情和底层英文都有中文提示', () => {
  assert.match(explainMarketplaceError({ code: 'MARKETPLACE_STORAGE_UNAVAILABLE', message: '' }, 503), /文件服务/)
  assert.match(explainMarketplaceError(null, 401), /重新登录/)
  assert.match(explainMarketplaceError({}, 403), /权限/)
  assert.equal(explainMarketplaceError('Internal Server Error', 500), '暂时无法完成操作，请稍后重试。')
})

test('分集表单错误保留集号位置和实际字数限制', () => {
  assert.equal(explainMarketplaceError([
    { type: 'string_too_long', loc: ['body', 'episodes', 2, 'title'], msg: 'String should have at most 200 characters', ctx: { max_length: 200 } },
  ], 422), '分集的第 3 项的标题：不能超过 200 个字')
})

test('解锁价限制显示整数积分，版权参考价仍显示元', () => {
  assert.equal(explainMarketplaceError([{ type: 'less_than_equal', loc: ['body', 'copyright_price_fen'], ctx: { le: 100000000 } }], 422), '参考价：不能超过 ¥1000000.00')
  assert.equal(explainMarketplaceError([
    { type: 'less_than_equal', loc: ['body', 'unlock_price_fen'], msg: 'Input should be less than or equal to 100000000', ctx: { le: 100000000 } },
  ], 422), '观众解锁价：不能超过 100,000,000 积分')
})

test('中文业务校验保留原因为主，整数与确认选项分别提示', () => {
  assert.equal(explainMarketplaceError([
    { type: 'value_error', loc: ['body', 'tags'], msg: 'Value error, 标签应为1至30字' },
    { type: 'int_from_float', loc: ['body', 'episode_no'], msg: 'Input should be a valid integer' },
    { type: 'literal_error', loc: ['body', 'read_all'], msg: 'Input should be True', ctx: { expected: 'True' } },
  ], 422), '标签：标签应为1至30字；集号：请填写整数；阅读确认：请勾选确认')
})

test('无效校验结构不泄露字段键或造成二次异常', () => {
  assert.equal(explainMarketplaceError([null, 'invalid'], 422), '请检查表单内容和必填字段')
  assert.equal(explainMarketplaceError([{ loc: ['body', 'internal_flag'], msg: 'Invalid input' }], 422), '填写内容：请检查填写内容')
})
