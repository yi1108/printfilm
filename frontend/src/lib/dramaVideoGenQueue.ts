/** 漫剧画布资产生视频队列：入队即提交 Seedance Worker，刷新后可从资产状态恢复 */
import { dramaApi, type DramaAsset } from '../api/drama'
import type { VideoGenerationOptions } from './dramaVideoGenerationOptions'
import { syncAssetVideoJobToUnified } from './dramaGenQueue'

export type DramaVideoGenStatus = 'queued' | 'running' | 'done' | 'failed'

export type DramaVideoGenJob = {
  id: string
  projectId: number
  assetId: number
  assetName: string
  prompt: string
  options: Partial<VideoGenerationOptions>
  referenceAssetIds: number[]
  status: DramaVideoGenStatus
  error?: string
  createdAt: number
  finishedAt?: number
}

type EnqueueInput = {
  projectId: number
  assetId: number
  assetName?: string
  prompt: string
  options?: Partial<VideoGenerationOptions>
  referenceAssetIds?: number[]
  /** 仅恢复轮询（后端已在 generating，不再重复 POST） */
  resumeOnly?: boolean
}

type InternalJob = DramaVideoGenJob & {
  resumeOnly: boolean
  resolve: (asset: DramaAsset) => void
  reject: (err: Error) => void
}

/*
 * MAX_POLL_CONCURRENT 同时轮询路数
 * POLL_TIMEOUT_MS Seedance 等待上限
 */
const MAX_POLL_CONCURRENT = 4
const DONE_RETENTION_MS = 45_000
const POLL_INTERVAL_MS = 3000
const POLL_TIMEOUT_MS = 15 * 60 * 1000
const VIDEO_URL_RE = /\.(mp4|webm|mov)(\?|$)/i

let jobs: InternalJob[] = []
const EMPTY_SNAPSHOT: DramaVideoGenJob[] = []
let cachedSnapshot: DramaVideoGenJob[] = EMPTY_SNAPSHOT
const listeners = new Set<() => void>()
let pollingCount = 0
let pumping = false
const waitingPoll: InternalJob[] = []

// 将内部 job 转为对外结构
function toPublicJob(job: InternalJob): DramaVideoGenJob {
  return {
    id: job.id,
    projectId: job.projectId,
    assetId: job.assetId,
    assetName: job.assetName,
    prompt: job.prompt,
    options: job.options,
    referenceAssetIds: job.referenceAssetIds,
    status: job.status,
    error: job.error,
    createdAt: job.createdAt,
    finishedAt: job.finishedAt,
  }
}

// 两个快照内容是否一致
function snapshotsEqual(a: DramaVideoGenJob[], b: DramaVideoGenJob[]): boolean {
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
      syncAssetVideoJobToUnified({
        assetId: job.assetId,
        projectId: job.projectId,
        assetName: job.assetName,
        status: job.status,
        error: job.error,
      })
    }
  }
}

// 某资产是否正在生视频
export function isDramaAssetVideoBusy(assetId: number): boolean {
  return jobs.some(
    (job) =>
      job.assetId === assetId && (job.status === 'queued' || job.status === 'running'),
  )
}

// 读取资产 generation 状态
function readGenerationStatus(asset: DramaAsset): string {
  const gen = (asset.params || {}).generation as { status?: string } | undefined
  return String(gen?.status || '')
}

// 成片 URL 是否已是视频文件
function isVideoMediaUrl(url: string | null | undefined): boolean {
  return Boolean(url && VIDEO_URL_RE.test(url))
}

// 轮询直到资产生视频结束（必须等到 mp4，不能把旧封面图当完成）
async function waitForAssetVideo(projectId: number, assetId: number): Promise<DramaAsset> {
  const started = Date.now()
  while (Date.now() - started < POLL_TIMEOUT_MS) {
    const list = await dramaApi.listAssets(projectId)
    const latest = list.find((a) => a.id === assetId)
    if (!latest) throw new Error('资产不存在')
    const status = readGenerationStatus(latest)
    if (status === 'failed') {
      const gen = (latest.params || {}).generation as { error?: string } | undefined
      throw new Error(String(gen?.error || '生视频失败'))
    }
    if (status === 'done' && latest.url) {
      return latest
    }
    if (status !== 'generating' && isVideoMediaUrl(latest.url)) {
      return latest
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  throw new Error('生视频超时，请刷新后重试')
}

// 有限并发轮询后端结果
async function pollJob(job: InternalJob) {
  pollingCount += 1
  try {
    const asset = await waitForAssetVideo(job.projectId, job.assetId)
    job.status = 'done'
    job.finishedAt = Date.now()
    emit()
    job.resolve(asset)
  } catch (err) {
    const message = err instanceof Error ? err.message : '生视频失败'
    job.status = 'failed'
    job.error = message
    job.finishedAt = Date.now()
    emit()
    job.reject(err instanceof Error ? err : new Error(message))
  } finally {
    pollingCount -= 1
    pump()
    emit()
  }
}

// 调度轮询槽位
function pump() {
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

// 提交后端后进入轮询
function startJob(job: InternalJob) {
  void (async () => {
    try {
      if (!job.resumeOnly) {
        await dramaApi.generateVideo({
          project_id: job.projectId,
          asset_id: job.assetId,
          prompt: job.prompt,
          model_id: job.options.model_id,
          aspect_ratio: job.options.aspect_ratio,
          resolution: job.options.resolution,
          duration_sec: job.options.duration_sec,
          image_style_id: job.options.image_style_id,
          reference_asset_ids: job.referenceAssetIds,
        })
      }
      job.status = 'running'
      emit()
      waitingPoll.push(job)
      pump()
    } catch (err) {
      const message = err instanceof Error ? err.message : '生视频失败'
      job.status = 'failed'
      job.error = message
      job.finishedAt = Date.now()
      emit()
      job.reject(err instanceof Error ? err : new Error(message))
    }
  })()
}

// 生成本地任务 id
function makeJobId() {
  return `vid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * 将画布资产生视频加入队列：立刻 POST 到后端 Worker，再本地轮询结果。
 * 同资产已在排队/生成中时复用同一 Promise。
 */
export function enqueueDramaVideoGen(input: EnqueueInput): Promise<DramaAsset> {
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
      assetName: (input.assetName || '').trim() || `视频 ${input.assetId}`,
      prompt: input.prompt,
      options: input.options || {},
      referenceAssetIds: input.referenceAssetIds || [],
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
 * 从资产列表恢复「后端仍在 generating」的视频任务。
 */
export function resumeDramaVideoGensFromAssets(
  projectId: number,
  assets: DramaAsset[],
): void {
  for (const asset of assets) {
    if (asset.project_id !== projectId) continue
    if ((asset.type || '').toLowerCase() !== 'video') continue
    const status = readGenerationStatus(asset)
    if (status !== 'generating') continue
    if (isDramaAssetVideoBusy(asset.id)) continue
    void enqueueDramaVideoGen({
      projectId,
      assetId: asset.id,
      assetName: asset.name || undefined,
      prompt: '',
      resumeOnly: true,
    }).catch(() => {
      /* 面板会显示失败 */
    })
  }
}
