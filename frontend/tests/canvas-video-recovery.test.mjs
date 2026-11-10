import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { setImmediate as nextTurn } from 'node:timers/promises'
import vm from 'node:vm'
import ts from 'typescript'

/** Execute the queue with its real polling logic and controlled HTTP dependencies. */
async function loadQueue(api, timers = {}) {
  const source = await readFile(new URL('../src/lib/dramaVideoGenQueue.ts', import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023 } }).outputText
  const sandbox = {
    exports: {}, Date, Math, setTimeout, queueMicrotask, ...timers,
    require(name) {
      if (name === '../api/drama') return { dramaApi: api }
      if (name === './dramaGenQueue') return { syncAssetVideoJobToUnified() {} }
      throw new Error(`Unexpected dependency: ${name}`)
    },
  }
  vm.runInNewContext(compiled, sandbox)
  return sandbox.exports
}

const running = { id: 11559, project_id: 1039, type: 'video', asset_type: 'video', url: '/old.mp4', params: { generation: { status: 'generating' } } }
const completed = { ...running, url: '/new.mp4', cover: '/new.jpg', params: { generation: { status: 'done' } } }

test('刷新后恢复视频轮询，将新成片交给画布并且不重复提交生成', async () => {
  let submissions = 0
  const updates = []
  const queue = await loadQueue({ listAssets: async () => [completed], generateVideo: async () => { submissions++ } })
  queue.resumeDramaVideoGensFromAssets(1039, [running], asset => updates.push(asset))
  await nextTurn()
  assert.equal(submissions, 0)
  assert.equal(updates.length, 1)
  assert.equal(updates[0].url, '/new.mp4')
})

test('重新进入画布可接上同一个在途轮询，完成时更新当前页面', async () => {
  let finish
  let requests = 0
  const queue = await loadQueue({ listAssets: () => { requests++; return new Promise(resolve => { finish = resolve }) } })
  const first = queue.enqueueDramaVideoGen({ projectId: 1039, assetId: 11559, prompt: '', resumeOnly: true })
  await nextTurn()
  const updates = []
  queue.resumeDramaVideoGensFromAssets(1039, [running], asset => updates.push(asset))
  finish([completed])
  await first
  await nextTurn()
  assert.equal(requests, 1)
  assert.equal(updates.length, 1)
  assert.equal(updates[0], completed)
})

test('后台仍在排队的视频也能恢复，其他项目和非视频资产不启动轮询', async () => {
  let requests = 0
  const updates = []
  const queue = await loadQueue({ listAssets: async () => { requests++; return [completed] } })
  queue.resumeDramaVideoGensFromAssets(1039, [
    { ...running, params: { generation: { status: 'queued' } } },
    { ...running, id: 2, project_id: 2000 },
    { ...running, id: 3, type: 'image' },
  ], asset => updates.push(asset))
  await nextTurn()
  assert.equal(requests, 1)
  assert.equal(updates.length, 1)
})

test('排队中的资产即便保留上一次 MP4，也必须等新任务完成', async () => {
  let requests = 0
  const updates = []
  const queued = { ...running, params: { generation: { status: 'queued' } } }
  const queue = await loadQueue({ listAssets: async () => [++requests === 1 ? queued : completed] }, { setTimeout: callback => setImmediate(callback) })
  queue.resumeDramaVideoGensFromAssets(1039, [queued], asset => updates.push(asset))
  await nextTurn()
  await nextTurn()
  assert.equal(requests, 2)
  assert.equal(updates.length, 1)
  assert.equal(updates[0].url, '/new.mp4')
})

test('恢复轮询失败不向画布回写旧成片', async () => {
  const updates = []
  const queue = await loadQueue({ listAssets: async () => [{ ...running, params: { generation: { status: 'failed', error: '模型暂不可用' } } }] })
  queue.resumeDramaVideoGensFromAssets(1039, [running], asset => updates.push(asset))
  await nextTurn()
  assert.equal(updates.length, 0)
  assert.equal(queue.isDramaAssetVideoBusy(11559), false)
})

test('旧轮询回调排队期间若已开始下一次生成，不能把旧成片推回画布', async () => {
  let finishFirst
  let finishSecond
  let requests = 0
  const queue = await loadQueue({ listAssets: () => new Promise(resolve => {
    requests++
    if (requests === 1) finishFirst = resolve
    else finishSecond = resolve
  }) })
  const first = queue.enqueueDramaVideoGen({ projectId: 1039, assetId: 11559, prompt: '', resumeOnly: true })
  let second
  void first.then(() => { second = queue.enqueueDramaVideoGen({ projectId: 1039, assetId: 11559, prompt: '', resumeOnly: true }) })
  const updates = []
  queue.resumeDramaVideoGensFromAssets(1039, [running], asset => updates.push(asset))
  await nextTurn()
  finishFirst([completed])
  await nextTurn()
  assert.equal(updates.length, 0)
  finishSecond([{ ...completed, url: '/newest.mp4' }])
  await second
})
