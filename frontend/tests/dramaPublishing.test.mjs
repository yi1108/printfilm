import assert from 'node:assert/strict'
import test from 'node:test'
import { latestEpisodeHandoffs, mergeSyncedCover, mergeSyncedEpisodes, publishSelection, sourceRelation } from '../src/features/marketplace/dramaPublishing.ts'

const episode = (id, episode_number, source_version = 'v1') => ({ id, name: `第${episode_number}集`, episode_number, source_version, ready: true, fragment_count: 3, completed_count: 3 })

test('按原集数发布，不能将不完整分集混入批次', () => {
  const context = { episodes: [episode(8, 2), episode(4, 1)] }
  assert.deepEqual(publishSelection(context, [8, 4], []), [
    { episode_id: 4, source_version: 'v1', update: false },
    { episode_id: 8, source_version: 'v1', update: false },
  ])
  context.episodes[0] = { ...context.episodes[0], ready: false, reason: '第3镜未生成' }
  assert.throws(() => publishSelection(context, [8, 4], []), /第3镜未生成/)
})

test('同一目标的同版本直接复用，新源版本必须明确确认', () => {
  const target = { imports: [{ source_episode_id: 4, episode_id: 10, source_version: 'v1' }] }
  const context = { episodes: [episode(4, 1)] }
  assert.equal(sourceRelation(context.episodes[0], target).changed, false)
  assert.equal(publishSelection(context, [4], [], target)[0].update, false)
  context.episodes[0].source_version = 'v2'
  assert.throws(() => publishSelection(context, [4], [], target), /请确认更新/)
  assert.deepEqual(publishSelection(context, [4], [4], target), [{ episode_id: 4, source_version: 'v2', update: true }])
  // 原片没变但目标已修改/遗留导入时，同样要求重新确认，不能返回失效任务。
  target.imports[0].source_version = 'v2'
  target.imports[0].requires_update = true
  assert.throws(() => publishSelection(context, [4], [], target), /请确认更新/)
  assert.equal(publishSelection(context, [4], [4], target)[0].update, true)
})

test('每集只采用最新同步任务，旧版成功不能盖掉新版失败或运行状态', () => {
  const items = [
    { id: 5, episode_id: 1, status: 'ready' },
    { id: 9, episode_id: 1, status: 'failed' },
    { id: 8, episode_id: 2, status: 'running' },
    { id: 6, episode_id: 2, status: 'ready' },
    { id: 10, episode_id: null, status: 'ready' },
  ]
  assert.deepEqual(latestEpisodeHandoffs(items).map(item => [item.id, item.status]), [[9, 'failed'], [8, 'running']])
})

test('同步完成回填视频及最新版本，保留本地标题、价格和新选封面', () => {
  const previous = [{ id: 1, version: 1, title: '导入标题', asset_id: null, cover_asset_id: null, source: 'printfilm', unlock_price_fen: 0 }]
  const current = [{ ...previous[0], title: '编辑中的标题', cover_asset_id: 20, unlock_price_fen: 1800 }]
  const remote = [{ ...previous[0], version: 3, asset_id: 30, cover_asset_id: 31, unlock_price_fen: 0 }]
  const merged = mergeSyncedEpisodes(current, remote, previous)
  assert.deepEqual(merged, [{ ...current[0], version: 3, asset_id: 30 }])
})

test('后台第二次回填仍保留用户选择的封面和手动视频，新添分集不会被轮询删掉', () => {
  const previous = [{ id: 1, version: 3, asset_id: 30, cover_asset_id: 31, source: 'printfilm' }]
  const current = [{ ...previous[0], asset_id: 41, cover_asset_id: 42 }, { asset_id: null, cover_asset_id: null, title: '新添分集' }]
  const remote = [{ ...previous[0], version: 4, asset_id: 50, cover_asset_id: 51 }]
  assert.deepEqual(mergeSyncedEpisodes(current, remote, previous), [{ ...current[0], version: 4 }, current[1]])
})

test('后台补齐系列封面后，当前表单接纳封面并持续跟随未编辑的远端值', () => {
  const first = mergeSyncedCover(null, 31, null)
  assert.equal(first, 31)
  assert.equal(mergeSyncedCover(first, 32, 31), 32)
  assert.equal(mergeSyncedCover(32, 32, 32), 32)
})

test('系列封面同步保留本地新选、主动清空和选择后清空的意图', () => {
  assert.equal(mergeSyncedCover(42, 31, null, true), 42)
  assert.equal(mergeSyncedCover(null, 32, 31, true), null)
  // 初始封面为空，用户选择后再清空；即使值与旧基线相同也不能被轮询覆盖。
  assert.equal(mergeSyncedCover(null, 31, null, true), null)
  assert.equal(mergeSyncedCover(42, 31, null), 42)
})
