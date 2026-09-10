/** 漫剧资产生图队列：入队即提交后端 Worker，刷新后可从资产状态恢复 */
import { dramaApi, type DramaAsset } from '../api/drama'
import type { ImageGenerationOptions } from './dramaGenerationOptions'
import { syncImageJobToUnified } from './dramaGenQueue'

export type DramaImageGenStatus = 'queued' | 'running' | 'done' | 'failed'

export type DramaImageGenJob = {
  id: string
  projectId: number
  assetId: number
  assetName: string
  assetType: string
  prompt: string
  options: Partial<ImageGenerationOptions>
  status: DramaImageGenStatus
  error?: string
  createdAt: number
  finishedAt?: number
}

type EnqueueInput = {
  projectId: number
  assetId: number
  assetName?: string
  assetType?: string
  prompt: string
  options?: Partial<ImageGenerationOptions>
  /** 仅恢复轮询（后端已在 generating，不再重复 POST） */
  resumeOnly?: boolean
}

type InternalJob = DramaImageGenJob & {
  resumeOnly: boolean
  taskId?: number
  resolve: (asset: DramaAsset) => void
  reject: (err: Error) => void
}

/* 前端同时提交/轮询几路；真正执行在任务平台 Worker */
const MAX_SUBMIT_CONCURRENT = 3
const MAX_POLL_CONCURRENT = 6
const DONE_RETENTION_MS = 45_000
const POLL_INTERVAL_MS = 2000
const POLL_TIMEOUT_MS = 10 * 60 * 1000

/** 对外暴露（文案用） */
export const DRAMA_IMAGE_GEN_MAX_CONCURRENT = MAX_POLL_CONCURRENT

/*
 * jobs 本地队列（UI + 轮询）
 * cachedSnapshot useSyncExternalStore 快照
 * listeners 订阅
 * pollingCount 正在 waitForAssetImage 的数量
 * pumping 是否已调度 poll pump
 */
let jobs: InternalJob[] = []
const EMPTY_SNAPSHOT: DramaImageGenJob[] = []
let cachedSnapshot: DramaImageGenJob[] = EMPTY_SNAPSHOT
const listeners = new Set<() => void>()
let pollingCount = 0
let pumping = false

// 将内部 job 转为对外结构
function toPublicJob(job: InternalJob): DramaImageGenJob {
  return {
    id: job.id,
    projectId: job.projectId,
    assetId: job.assetId,
    assetName: job.assetName,
    assetType: job.assetType,
    prompt: job.prompt,
    options: job.options,
    status: job.status,
    error: job.error,
    createdAt: job.createdAt,
    finishedAt: job.finishedAt,
  }
}

// 两个快照内容是否一致
function snapshotsEqual(a: DramaImageGenJob[], b: DramaImageGenJob[]): boolean {
  if (a === b) return true
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i += 1) {
    const left = a[i]
    const right = b[i]
    if (
      left.id !== right.id ||
      left.status !== right.status ||
      left.error !== right.error ||
      left.finishedAt !== right.finishedAt
    ) {
      return false
    }
  }
  return true
}

// 清理过期完成项
function pruneFinished() {
  const now = Date.now()
  jobs = jobs.filter((job) => {
    if (job.status === 'queued' || job.status === 'running') return true
    if (!job.finishedAt) return true
    return now - job.finishedAt < DONE_RETENTION_MS
  })
}

// 重建并缓存对外快照
function refreshSnapshot() {
  pruneFinished()
  const next = jobs.length === 0 ? EMPTY_SNAPSHOT : jobs.map((job) => toPublicJob(job))
  if (!snapshotsEqual(cachedSnapshot, next)) {
    cachedSnapshot = next
  }
}

// 通知订阅者，并同步到统一生成队列
function emit() {
  refreshSnapshot()
  listeners.forEach((listener) => listener())
  for (const job of jobs) {
    if (job.status === 'queued' || job.status === 'running' || job.finishedAt) {
      syncImageJobToUnified({
        assetId: job.assetId,
        projectId: job.projectId,
        assetName: job.assetName,
        assetType: job.assetType,
        status: job.status,
        taskId: job.taskId,
        error: job.error,
      })
    }
  }
}

// 读取队列快照
export function getDramaImageGenQueue(): DramaImageGenJob[] {
  refreshSnapshot()
  return cachedSnapshot
}

// 某资产是否忙
export function isDramaAssetImageBusy(assetId: number): boolean {
  return jobs.some(
    (job) =>
      job.assetId === assetId && (job.status === 'queued' || job.status === 'running'),
  )
}

// 当前排队 + 进行中数量
export function getDramaImageGenActiveCount(): number {
  return jobs.filter((job) => job.status === 'queued' || job.status === 'running').length
}

// 订阅队列变化
export function subscribeDramaImageGenQueue(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

// 生成本地任务 id
function makeJobId() {
  return `img-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

// 读取资产 generation 状态
function readGenerationStatus(asset: DramaAsset): string {
  const gen = (asset.params || {}).generation as { status?: string } | undefined
  return String(gen?.status || '')
}

// 轮询直到资产生图结束；generating 时回调以便 UI 切到「生成中」
// 必须先判 failed/cancelled：重试失败时旧 url/cover 仍在，不能当成功
async function waitForAssetImage(
  projectId: number,
  assetId: number,
  onRemoteStatus?: (status: string) => void,
): Promise<DramaAsset> {
  const started = Date.now()
  while (Date.now() - started < POLL_TIMEOUT_MS) {
    const list = await dramaApi.listAssets(projectId)
    const latest = list.find((a) => a.id === assetId)
    if (!latest) throw new Error('资产不存在')
    const status = readGenerationStatus(latest)
    onRemoteStatus?.(status)
    if (status === 'failed' || status === 'cancelled') {
      const gen = (latest.params || {}).generation as { error?: string } | undefined
      throw new Error(String(gen?.error || (status === 'cancelled' ? '生图已取消' : '生图失败')))
    }
    if (status === 'done' && (latest.url || latest.cover)) {
      return latest
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  throw new Error('生图超时，请刷新后重试')
}

/*
 * waitingSubmit 等待 POST 入队的任务
 * waitingPoll 已提交、等待轮询槽位的任务
 */
const waitingSubmit: InternalJob[] = []
let submittingCount = 0
const waitingPoll: InternalJob[] = []

// 有限并发轮询后端结果
async function pollJob(job: InternalJob) {
  pollingCount += 1
  try {
    const asset = await waitForAssetImage(job.projectId, job.assetId, (remoteStatus) => {
      if (remoteStatus === 'generating' && job.status !== 'running') {
        job.status = 'running'
        emit()
      }
    })
    job.status = 'done'
    job.finishedAt = Date.now()
    emit()
    job.resolve(asset)
  } catch (err) {
    const message = err instanceof Error ? err.message : '生图失败'
    job.status = 'failed'
    job.error = message
    job.finishedAt = Date.now()
    emit()
    job.reject(err instanceof Error ? err : new Error(message))
  } finally {
    pollingCount -= 1
    pumpPoll()
    emit()
  }
}

// 调度轮询槽位
function pumpPoll() {
  if (pumping) return
  pumping = true
  queueMicrotask(() => {
    pumping = false
    while (pollingCount < MAX_POLL_CONCURRENT && waitingPoll.length > 0) {
      const next = waitingPoll.shift()
      if (!next) break
      if (next.status === 'failed' || next.status === 'done') continue
      void pollJob(next)
    }
    emit()
  })
}

// 有限并发 POST 入队
async function submitJob(job: InternalJob) {
  submittingCount += 1
  try {
    if (!job.resumeOnly) {
      const resp = await dramaApi.generateImage({
        project_id: job.projectId,
        asset_id: job.assetId,
        prompt: job.prompt,
        name: job.assetName || undefined,
        asset_type_kind: job.assetType,
        image_style_id: job.options.image_style_id,
        model_id: job.options.model_id,
        aspect_ratio: job.options.aspect_ratio,
        resolution: job.options.resolution,
      })
      job.taskId = resp.task_id != null ? Number(resp.task_id) : undefined
    }
    waitingPoll.push(job)
    pumpPoll()
  } catch (err) {
    const message = err instanceof Error ? err.message : '生图失败'
    job.status = 'failed'
    job.error = message
    job.finishedAt = Date.now()
    emit()
    job.reject(err instanceof Error ? err : new Error(message))
  } finally {
    submittingCount -= 1
    pumpSubmit()
    emit()
  }
}

// 调度入队提交槽位
function pumpSubmit() {
  queueMicrotask(() => {
    while (submittingCount < MAX_SUBMIT_CONCURRENT && waitingSubmit.length > 0) {
      const next = waitingSubmit.shift()
      if (!next) break
      if (next.status === 'failed' || next.status === 'done') continue
      void submitJob(next)
    }
    emit()
  })
}

// 加入本地队列后等待提交/轮询
function startJob(job: InternalJob) {
  if (job.resumeOnly) {
    waitingPoll.push(job)
    pumpPoll()
    return
  }
  waitingSubmit.push(job)
  pumpSubmit()
}

/**
 * 将资产生图加入队列：立刻 POST 到后端 Worker，再本地轮询结果。
 * 同资产已在排队/生成中时复用同一 Promise。
 */
export function enqueueDramaImageGen(input: EnqueueInput): Promise<DramaAsset> {
  const existing = jobs.find(
    (job) =>
      job.assetId === input.assetId &&
      (job.status === 'queued' || job.status === 'running'),
  )
  if (existing) {
    return new Promise((resolve, reject) => {
      const prevResolve = existing.resolve
      const prevReject = existing.reject
      existing.resolve = (asset) => {
        prevResolve(asset)
        resolve(asset)
      }
      existing.reject = (err) => {
        prevReject(err)
        reject(err)
      }
    })
  }

  return new Promise<DramaAsset>((resolve, reject) => {
    const job: InternalJob = {
      id: makeJobId(),
      projectId: input.projectId,
      assetId: input.assetId,
      assetName: (input.assetName || '').trim() || `资产 ${input.assetId}`,
      assetType: input.assetType || 'character',
      prompt: input.prompt,
      options: input.options || {},
      status: 'queued',
      createdAt: Date.now(),
      resumeOnly: Boolean(input.resumeOnly),
      resolve,
      reject,
    }
    jobs = [...jobs, job]
    emit()
    startJob(job)
  })
}

/**
 * 从资产列表恢复「后端仍在 generating」的任务（刷新页面后调用）。
 * 不再重复 POST，只接上轮询与队列 UI。
 */
export function resumeDramaImageGensFromAssets(
  projectId: number,
  assets: DramaAsset[],
): void {
  for (const asset of assets) {
    if (asset.project_id !== projectId) continue
    /* 视频资产走 Seedance 队列，避免刷新后误 POST 生图 */
    if ((asset.type || '').toLowerCase() === 'video') continue
    const status = readGenerationStatus(asset)
    if (status !== 'generating' && status !== 'queued') continue
    if (isDramaAssetImageBusy(asset.id)) continue
    void enqueueDramaImageGen({
      projectId,
      assetId: asset.id,
      assetName: asset.name || undefined,
      assetType: asset.type,
      prompt: '',
      resumeOnly: true,
    }).catch(() => {
      /* 面板会显示失败；页面层可再 toast */
    })
  }
}

// 清空已结束项
export function clearFinishedDramaImageGenJobs() {
  jobs = jobs.filter((job) => job.status === 'queued' || job.status === 'running')
  emit()
}
