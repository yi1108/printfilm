import test from 'node:test'
import assert from 'node:assert/strict'
import { formatCopyrightError, formatGenerationErrorMessage } from '../src/lib/generationError.ts'

const requestId = '02179317708119300000000000000000000ffffac182c4fcb7e6'
const raw = `RuntimeError: The request failed because the output video may be related to copyright restrictions. Request id: ${requestId}`

test('版权审核失败显示中文原因和处理建议，并保留完整请求编号', () => {
  const view = formatCopyrightError(raw)
  assert.equal(view.title, '视频未通过版权审核')
  assert.match(view.message, /可能涉及版权限制/)
  assert.equal(view.requestId, requestId)
  assert.ok(view.message.includes(requestId))
  assert.match(view.suggestion, /提示词|参考素材/)
  assert.match(view.suggestion, /客服/)
  assert.doesNotMatch(formatGenerationErrorMessage(raw), /RuntimeError|The request failed|Request id:/)
  assert.doesNotMatch(formatGenerationErrorMessage(raw), /已退款|不扣费|确认侵权|参考图疑似真人/)
})

test('识别复制时丢空格、换行和紧贴冒号的上游文案', () => {
  const pasted = `RuntimeError: The request failed because the outputvideo may be related to copyright restrictions. Request\nid:\n${requestId}`
  assert.equal(formatCopyrightError(pasted).requestId, requestId)
  assert.equal(formatCopyrightError(pasted).title, '视频未通过版权审核')
})

test('上游版权错误码优先于泛化的敏感内容或网络描述', () => {
  const view = formatCopyrightError(`TokenFree https://www.tokenfree.com/v1/videos: OutputVideoSensitiveContentDetected.PolicyViolation RequestID:${requestId}`)
  assert.equal(view.title, '视频未通过版权审核')
  assert.equal(view.requestId, requestId)
})

test('兼容已翻译的版权文案和结构化请求编号', () => {
  assert.equal(formatCopyrightError(`请求失败，因为输出视频可能涉及版权限制。请求编号：${requestId}`).requestId, requestId)
  assert.equal(formatCopyrightError(JSON.stringify({ code: 'OutputVideoSensitiveContentDetected.PolicyViolation', request_id: requestId })).requestId, requestId)
})

test('未记录请求编号时仍提供完整建议，不生成占位编号', () => {
  const view = formatCopyrightError('OutputVideoSensitiveContentDetected.PolicyViolation')
  assert.equal(view.requestId, undefined)
  assert.doesNotMatch(view.message, /undefined|null|请求编号/)
  assert.match(formatGenerationErrorMessage('OutputVideoSensitiveContentDetected.PolicyViolation'), /联系客服/)
})

test('非版权审核、网络、计费与普通错误继续使用原文', () => {
  for (const message of ['OutputVideoSensitiveContentDetected', 'InputImageSensitiveContentDetected.PrivacyInformation', 'ConnectTimeout', '余额不足，请先充值', '  模型暂不可用  ', 'copyright notice']) {
    assert.equal(formatCopyrightError(message), null)
    assert.equal(formatGenerationErrorMessage(message), message)
  }
  assert.equal(formatGenerationErrorMessage(null), '')
  assert.equal(formatGenerationErrorMessage(undefined), '')
})
