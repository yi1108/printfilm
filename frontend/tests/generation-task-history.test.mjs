import test from 'node:test'
import assert from 'node:assert/strict'
import { generationRecordKey, generationDetailPath, generationBillingState, generationTaskKinds, generationTaskKind, generationTaskListPath } from '../src/lib/generationTaskHistory.ts'
import { toolRunDetailAsset } from '../src/lib/toolRunDetails.ts'
import { assetDetailInfo } from '../src/lib/assetDetails.ts'
import { scopedRequestInit, setWorkspaceTeam } from '../src/features/teams/workspaceScope.ts'

const record = { id: 42, tool_id: 'image', kind: 'image', status: 'succeeded', prompt: 'A portrait', urls: [], created_at: '2026-10-26T10:00:00Z' }

test('我的任务只提供全部、视频、图片和音频筛选', () => {
  assert.deepEqual(generationTaskKinds, ['all', 'video', 'image', 'audio'])
  for (const kind of generationTaskKinds) assert.equal(generationTaskKind(kind), kind)
})

test('旧文字任务链接和未知类型回到全部媒体任务', () => {
  for (const kind of ['text', 'unknown', '', null, undefined]) assert.equal(generationTaskKind(kind), 'all')
})

test('旧文字筛选不再传给列表 API，并保留其他筛选和分页', () => {
  const path = generationTaskListPath(2, 16, { kind: 'text', status: 'succeeded', task_id: 'task-42', created_from: '2026-10-26T00:00:00Z' })
  const url = new URL(path, 'https://printfilm.example')
  assert.equal(url.pathname, '/api/tasks/generations')
  assert.equal(url.searchParams.has('kind'), false)
  assert.equal(url.searchParams.get('page'), '2')
  assert.equal(url.searchParams.get('page_size'), '16')
  assert.equal(url.searchParams.get('status'), 'succeeded')
  assert.equal(url.searchParams.get('task_id'), 'task-42')
  assert.equal(url.searchParams.get('created_from'), '2026-10-26T00:00:00Z')
  for (const kind of ['video', 'image', 'audio']) {
    assert.equal(new URL(generationTaskListPath(1, 8, { kind }), url).searchParams.get('kind'), kind)
  }
  assert.equal(new URL(generationTaskListPath(1, 8, { kind: 'all' }), url).searchParams.has('kind'), false)
})

test('同数字 ID 的任务和旧工具记录使用独立标识及详情地址', () => {
  const task = { ...record, source: 'task' }
  assert.equal(generationRecordKey(task), 'task:42')
  assert.equal(generationRecordKey(record), 'tool:42')
  assert.equal(generationDetailPath(task), '/api/tasks/generations/42')
  assert.equal(generationDetailPath(record), '/api/tools/runs/42')
})

test('文字生成详情保留完整脚本，且不能把结果地址当图片预览', () => {
  const content = '镜头一\n完整生成脚本'.repeat(100)
  const asset = toolRunDetailAsset({ ...record, kind: 'text', text_content: content, urls: ['/static/result.txt'] })
  assert.equal(asset.type, 'text')
  assert.equal(asset.url, null)
  assert.equal(asset.params.textContent, content)
})

test('尚未产出媒体的任务详情显示可读状态或错误', () => {
  const queued = toolRunDetailAsset({ ...record, kind: 'video', status: 'queued', preview_url: '/static/frame.png' })
  assert.equal(queued.type, 'text')
  assert.equal(queued.url, null)
  assert.match(queued.params.textContent, /排队/)
  const failed = toolRunDetailAsset({ ...record, kind: 'audio', status: 'failed', error: '模型暂不可用' })
  assert.equal(failed.params.textContent, '模型暂不可用')
})

test('版权审核失败详情显示中文建议并保留请求编号，不修改原始错误', () => {
  const requestId = '02179317708119300000000000000000000ffffac182c4fcb7e6'
  const error = `RuntimeError: The request failed because the outputvideo may be related to copyright restrictions. Request id: ${requestId}`
  const failedRecord = { ...record, kind: 'video', status: 'failed', error }
  const failed = toolRunDetailAsset(failedRecord)
  assert.match(failed.params.textContent, /版权/)
  assert.match(failed.params.textContent, /调整|更换|修改/)
  assert.ok(failed.params.textContent.includes(requestId))
  assert.doesNotMatch(failed.params.textContent, /RuntimeError|The request failed/)
  assert.equal(failedRecord.error, error)
})

test('成功媒体仍按所选结果预览，视频首帧不能作为成片地址', () => {
  const asset = toolRunDetailAsset({ ...record, kind: 'video', urls: ['/static/a.mp4', '/static/b.mp4'], preview_url: '/static/frame.png' }, 1)
  assert.equal(asset.type, 'video')
  assert.equal(asset.url, '/static/b.mp4')
  assert.equal(asset.cover, '/static/frame.png')
})

test('详情不把内部任务编号写入标题，未记录提示词保持为空', () => {
  const asset = toolRunDetailAsset({ ...record, kind: 'video', prompt: '', task_type: 'fragment_video', provider_task_id: 'private-provider-id' })
  assert.equal(asset.name, '视频生成')
  assert.equal(asset.params.media_metadata.prompt, '')
  assert.doesNotMatch(JSON.stringify(asset.params), /fragment_video|private-provider-id/)
})

test('提交参数保留数值和布尔值，请求时长与成片时长分开', () => {
  const asset = toolRunDetailAsset({ ...record, kind: 'video', urls: ['/static/movie.mp4'], params: {
    model_id: 'actual-model', model: 'old-model', ratio: '1:1', aspect_ratio: '9:16', resolution: '480p',
    duration: '12s', media_duration_sec: 8, video_mode: 'first_last_frame', seed: 0,
    generate_audio: false, watermark: false, count: 1, references: [{ secret: 'not-for-display' }],
  } })
  const info = assetDetailInfo(asset)
  assert.equal(info.model, 'actual-model')
  assert.equal(info.mediaDuration, '8 秒')
  const values = Object.fromEntries(info.parameters.map((item) => [item.label, item.value]))
  assert.equal(values['设定时长'], '12 秒')
  assert.equal(values['设定画幅'], '9:16')
  assert.equal(values['设定分辨率'], '480p')
  assert.equal(values['生成方式'], '首尾帧')
  assert.equal(values['生成声音'], '否')
  assert.equal(values['水印'], '否')
  assert.equal(values['随机种子'], '0')
  assert.equal(values['生成数量'], '1')
  assert.doesNotMatch(JSON.stringify(asset.params), /references|not-for-display/)
})

test('未记录的媒体时长不能用任务执行耗时推算', () => {
  const asset = toolRunDetailAsset({ ...record, kind: 'video', started_at: '2026-10-26T10:00:00Z', finished_at: '2026-10-26T10:00:12Z', params: {} })
  const info = assetDetailInfo(asset)
  assert.equal(info.mediaDuration, '')
  assert.equal(info.parameters.some((item) => item.label.includes('时长')), false)
})

test('结算状态不根据完成时间推断，隐藏费用不能显示成免费', () => {
  assert.equal(generationBillingState({ ...record, billing_status: 'pending', finished_at: record.created_at }), 'pending')
  assert.equal(generationBillingState({ ...record, billing_charged_fen: null }), 'hidden')
  assert.equal(generationBillingState({ ...record, status: 'failed', billing_charged_fen: 0 }), 'not_charged')
  assert.equal(generationBillingState({ ...record, billing_charged_fen: 500 }), 'settled')
})

test('统一任务列表和详情继承当前团队范围，切回个人时清除', () => {
  try {
    setWorkspaceTeam(12)
    assert.equal(new Headers(scopedRequestInit('/api/tasks/generations?page=1').headers).get('X-Team-Id'), '12')
    assert.equal(new Headers(scopedRequestInit(generationDetailPath({ ...record, source: 'task' })).headers).get('X-Team-Id'), '12')
    setWorkspaceTeam(null)
    assert.equal(new Headers(scopedRequestInit('/api/tasks/generations').headers).get('X-Team-Id'), null)
  } finally { setWorkspaceTeam(null) }
})
