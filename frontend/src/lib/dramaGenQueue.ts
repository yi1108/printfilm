/** 漫剧全局生成队列：图片 / 视频等任务统一展示与恢复 */
import { useSyncExternalStore } from 'react'
import type { DramaTaskBrief } from '../api/drama'

export type DramaGenJobKind = 'image' | 'video'

export type DramaGenJobStatus = 'queued' | 'running' | 'done' | 'failed'

export type DramaGenJob = {
  id: string
  kind: DramaGenJobKind
  projectId: number
  /** 资产 id 或分镜 id */
  targetId: number
  episodeId?: number
  /** 统一任务平台 task_runs.id，用于打开详情 */
  taskId?: number
  title: string
  /** 子类型文案：角色 / 场景 / 分镜视频 等 */
  subtype: string
  status: DramaGenJobStatus
  message?: string
  error?: string
  createdAt: number
  finishedAt?: number
}

type Listener = () => void

const DONE_RETENTION_MS = 10 * 60 * 1000
const EMPTY: DramaGenJob[] = []

/*
 * jobs 统一任务列表
 * cachedSnapshot 对外快照
 * listeners 订阅
 */
let jobs: DramaGenJob[] = []
let cachedSnapshot: DramaGenJob[] = EMPTY
const listeners = new Set<Listener>()
// 用户手动清空后，不再被轮询/状态同步写回队列
const dismissedJobIds = new Set<string>()

// 重新入队时取消「已清空」标记
function undismissJob(jobId: string): void {
  dismissedJobIds.delete(jobId)
}

// 是否跳过把已完成项写回（未跟踪或用户已清空）
function shouldSkipFinishedResync(
  jobId: string,
  rawStatus: string,
  existing: DramaGenJob | undefined,
  hasActiveTask: boolean,
): boolean {
  if (dismissedJobIds.has(jobId) && !['queued', 'running', 'generating'].includes(rawStatus)) {
    return true
  }
  if (existing || hasActiveTask) return false
  return ['done', 'failed', 'cancelled', 'idle'].includes(rawStatus)
}

// 快照是否等价
function snapshotsEqual(a: DramaGenJob[], b: DramaGenJob[]): boolean {
  if (a === b) return true
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i += 1) {
    const x = a[i]
    const y = b[i]
    if (
      x.id !== y.id ||
      x.status !== y.status ||
      x.message !== y.message ||
      x.error !== y.error ||
      x.finishedAt !== y.finishedAt ||
      x.title !== y.title ||
      x.taskId !== y.taskId
    ) {
      return false
    }
  }
  return true
}

// 清理过期完成/失败项（进行中永不清）
function pruneFinished() {
  const now = Date.now()
  jobs = jobs.filter((job) => {
    if (job.status === 'queued' || job.status === 'running') return true
    if (!job.finishedAt) return true
    return now - job.finishedAt < DONE_RETENTION_MS
  })
}

// 刷新快照并通知
function emit() {
  pruneFinished()
  const next = jobs.length === 0 ? EMPTY : [...jobs]
  if (snapshotsEqual(cachedSnapshot, next)) return
  cachedSnapshot = next
  listeners.forEach((fn) => fn())
}

// 读取快照
export function getDramaGenQueue(): DramaGenJob[] {
  pruneFinished()
  if (jobs.length === 0) {
    cachedSnapshot = EMPTY
    return EMPTY
  }
  if (!snapshotsEqual(cachedSnapshot, jobs)) {
    cachedSnapshot = [...jobs]
  }
  return cachedSnapshot
}

// 订阅
export function subscribeDramaGenQueue(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

// Hook
export function useDramaGenQueue(): DramaGenJob[] {
  return useSyncExternalStore(subscribeDramaGenQueue, getDramaGenQueue, getDramaGenQueue)
}

// 活跃任务数（角标）
export function getDramaGenActiveCount(): number {
  return jobs.filter((j) => j.status === 'queued' || j.status === 'running').length
}

// 两条任务的展示字段是否相同
function jobDisplayEqual(a: DramaGenJob, b: DramaGenJob): boolean {
  return (
    a.id === b.id &&
    a.kind === b.kind &&
    a.projectId === b.projectId &&
    a.targetId === b.targetId &&
    a.episodeId === b.episodeId &&
    a.title === b.title &&
    a.subtype === b.subtype &&
    a.status === b.status &&
    a.message === b.message &&
    a.error === b.error &&
    a.finishedAt === b.finishedAt &&
    a.taskId === b.taskId
  )
}

// 写入或更新一条任务；silent 时只改内存，由调用方统一 emit
export function upsertDramaGenJob(
  patch: Omit<DramaGenJob, 'createdAt' | 'finishedAt'> & {
    createdAt?: number
    finishedAt?: number
  },
  options?: { silent?: boolean },
): void {
  if (dismissedJobIds.has(patch.id)) {
    if (patch.status === 'queued' || patch.status === 'running') {
      undismissJob(patch.id)
    } else {
      return
    }
  }
  const idx = jobs.findIndex((j) => j.id === patch.id)
  const prev = idx >= 0 ? jobs[idx] : null
  const status = patch.status
  const finishedAt =
    status === 'done' || status === 'failed'
      ? patch.finishedAt ?? prev?.finishedAt ?? Date.now()
      : undefined
  const next: DramaGenJob = {
    id: patch.id,
    kind: patch.kind,
    projectId: patch.projectId,
    targetId: patch.targetId,
    episodeId: patch.episodeId,
    taskId: patch.taskId ?? prev?.taskId,
    title: patch.title,
    subtype: patch.subtype,
    status,
    message: patch.message,
    error: patch.error,
    createdAt: patch.createdAt ?? prev?.createdAt ?? Date.now(),
    finishedAt,
  }
  if (prev && jobDisplayEqual(prev, next)) return
  if (idx >= 0) {
    jobs = jobs.map((j, i) => (i === idx ? next : j))
  } else {
    jobs = [...jobs, next]
  }
  if (!options?.silent) emit()
}

// 图片任务 id
export function imageJobId(assetId: number): string {
  return `image:${assetId}`
}

// 视频分镜任务 id
export function videoJobId(fragmentId: number): string {
  return `video:${fragmentId}`
}

// 同步资产生图任务到统一队列（由 dramaImageGenQueue 回调）
export function syncImageJobToUnified(input: {
  assetId: number
  projectId: number
  assetName: string
  assetType: string
  status: DramaGenJobStatus
  taskId?: number
  error?: string
}): void {
  upsertDramaGenJob({
    id: imageJobId(input.assetId),
    kind: 'image',
    projectId: input.projectId,
    targetId: input.assetId,
    title: input.assetName || `资产 ${input.assetId}`,
    subtype: input.assetType || 'image',
    status: input.status,
    taskId: input.taskId,
    error: input.error,
    message:
      input.status === 'running'
        ? '生图中'
        : input.status === 'queued'
          ? '排队中'
          : undefined,
  })
}

// 画布视频资产任务 id（与分镜 video:{fragmentId} 区分）
export function assetVideoJobId(assetId: number): string {
  return `video-asset:${assetId}`
}

// 同步画布资产生视频到统一队列
export function syncAssetVideoJobToUnified(input: {
  assetId: number
  projectId: number
  assetName: string
  status: DramaGenJobStatus
  error?: string
}): void {
  upsertDramaGenJob({
    id: assetVideoJobId(input.assetId),
    kind: 'video',
    projectId: input.projectId,
    targetId: input.assetId,
    title: input.assetName || `视频 ${input.assetId}`,
    subtype: '画布视频',
    status: input.status,
    error: input.error,
    message:
      input.status === 'running'
        ? '生视频中'
        : input.status === 'queued'
          ? '排队中'
          : undefined,
  })
}

type FragmentStatusItem = {
  fragment_id: number
  status: string
  message?: string
  phase?: string
  error?: string
  video?: string
  cover?: string
}

// 根据分镜列表解析展示序号；无法可靠判断时返回 null，避免轮询把标题改成「片段 01」
function resolveFragmentLabel(
  fragId: number,
  fragments: Array<{ id: number; sort_order?: number }>,
): string | null {
  const frag = fragments.find((f) => f.id === fragId)
  if (frag && typeof frag.sort_order === 'number' && frag.sort_order >= 0) {
    return `片段 ${String(frag.sort_order + 1).padStart(2, '0')}`
  }
  // 仅当列表里已有可靠 sort_order 时，才允许用下标兜底（完整有序列表）
  const hasAnySortOrder = fragments.some((f) => typeof f.sort_order === 'number' && f.sort_order >= 0)
  if (!hasAnySortOrder) return null
  const idx = fragments.findIndex((f) => f.id === fragId)
  if (idx < 0) return null
  return `片段 ${String(idx + 1).padStart(2, '0')}`
}

// 组装队列标题：有可靠镜序时写入/纠正；否则保留已有标题
function resolveVideoJobTitle(
  existing: DramaGenJob | undefined,
  episodeName: string | undefined,
  fragmentLabel: string | null,
): string {
  if (fragmentLabel) {
    const prefix = (episodeName || '').trim()
    if (prefix) return `${prefix} · ${fragmentLabel}`
    if (existing?.title) {
      const sep = existing.title.indexOf(' · ')
      if (sep >= 0) return `${existing.title.slice(0, sep)} · ${fragmentLabel}`
    }
    return fragmentLabel
  }
  if (existing?.title) return existing.title
  const prefix = (episodeName || '').trim()
  return prefix ? `${prefix} · 分镜视频` : '分镜视频'
}

type FragmentTaskItem = DramaTaskBrief

export type EpisodeGenerateStatusPayload = {
  episode_id: number
  done: number
  failed: number
  running: number
  total: number
  tasks: DramaTaskBrief[]
  fragments: FragmentStatusItem[]
}
export function syncEpisodeVideoJobs(input: {
  projectId: number
  episodeId: number
  episodeName?: string
  fragments: Array<{ id: number; sort_order?: number; content?: string }>
  statusItems: FragmentStatusItem[]
  taskItems?: FragmentTaskItem[]
}): void {
  const fragLabel = (fragId: number) => resolveFragmentLabel(fragId, input.fragments)

  const activeTaskByFragmentId = new Map<number, FragmentTaskItem>()
  // 每个分镜取最新一条平台任务（含失败），供队列绑定 taskId / 错误文案
  const latestTaskByFragmentId = new Map<number, FragmentTaskItem>()
  for (const task of input.taskItems || []) {
    if (task.task_type !== 'fragment_video') continue
    if (typeof task.fragment_id !== 'number') continue
    const prev = latestTaskByFragmentId.get(task.fragment_id)
    if (!prev || (task.id || 0) > (prev.id || 0)) {
      latestTaskByFragmentId.set(task.fragment_id, task)
    }
    if (task.cancel_requested) continue
    if (!['pending', 'leased', 'running', 'awaiting_poll', 'awaiting_review'].includes(task.status))
      continue
    activeTaskByFragmentId.set(task.fragment_id, task)
  }

  for (const item of input.statusItems) {
    const raw = String(item.status || 'idle')
    const jobId = videoJobId(item.fragment_id)
    const existing = jobs.find((j) => j.id === jobId)
    const activeTask = activeTaskByFragmentId.get(item.fragment_id)
    const latestTask = latestTaskByFragmentId.get(item.fragment_id)
    const boundTaskId = activeTask?.id ?? latestTask?.id ?? existing?.taskId
    if (shouldSkipFinishedResync(jobId, raw, existing, Boolean(activeTask))) {
      continue
    }
    // idle：服务端无任务。乐观入队后若已中断，从「生成中」清掉
    if (raw === 'idle') {
      if (activeTask) {
        upsertDramaGenJob(
          {
            id: videoJobId(item.fragment_id),
            kind: 'video',
            projectId: input.projectId,
            targetId: item.fragment_id,
            episodeId: input.episodeId,
            taskId: activeTask.id,
            title: resolveVideoJobTitle(existing, input.episodeName, fragLabel(item.fragment_id)),
            subtype: '分镜视频',
            status: activeTask.status === 'pending' || activeTask.status === 'leased' ? 'queued' : 'running',
            message:
              activeTask.current_step_key === 'assets'
                ? '生成参考图…'
                : activeTask.status === 'pending' || activeTask.status === 'leased'
                  ? '排队中'
                  : '生成中',
          },
          { silent: true },
        )
        continue
      }
      if (existing && (existing.status === 'queued' || existing.status === 'running')) {
        upsertDramaGenJob(
          {
            id: existing.id,
            kind: existing.kind,
            projectId: existing.projectId,
            targetId: existing.targetId,
            episodeId: existing.episodeId,
            taskId: boundTaskId,
            title: existing.title,
            subtype: existing.subtype,
            status: 'failed',
            error: latestTask?.error_message || '任务已中断，请重新生成',
          },
          { silent: true },
        )
      }
      continue
    }
    let status: DramaGenJobStatus = 'running'
    if (raw === 'done') status = 'done'
    else if (raw === 'failed' || raw === 'cancelled') status = 'failed'
    else if (raw === 'queued') status = 'queued'
    else status = 'running'

    const errText =
      item.error ||
      (raw === 'cancelled' || status === 'failed'
        ? latestTask?.error_message || undefined
        : undefined) ||
      (raw === 'cancelled' ? '已取消' : undefined)

    upsertDramaGenJob(
      {
        id: videoJobId(item.fragment_id),
        kind: 'video',
        projectId: input.projectId,
        targetId: item.fragment_id,
        episodeId: input.episodeId,
        taskId: boundTaskId,
        title: resolveVideoJobTitle(existing, input.episodeName, fragLabel(item.fragment_id)),
        subtype: '分镜视频',
        status,
        message: item.message || (item.phase === 'assets' ? '生成参考图…' : undefined),
        error: errText,
      },
      { silent: true },
    )
  }
  emit()
  ensureEpisodeVideoStatusPoll()
}

// 入队时立刻写入队列（乐观展示，不依赖首轮轮询）
export function enqueueEpisodeVideoJobs(input: {
  projectId: number
  episodeId: number
  episodeName?: string
  fragments: Array<{ id: number; sort_order?: number }>
  fragmentIds: number[]
}): void {
  for (const fid of input.fragmentIds) {
    undismissJob(videoJobId(fid))
  }
  const idSet = new Set(input.fragmentIds)
  const items = input.fragments
    .filter((f) => idSet.has(f.id))
    .map((f) => ({
      fragment_id: f.id,
      status: 'queued',
      message: '已入队',
    }))
  syncEpisodeVideoJobs({
    projectId: input.projectId,
    episodeId: input.episodeId,
    episodeName: input.episodeName,
    fragments: input.fragments,
    statusItems: items,
  })
  requestOpenDramaGenQueue()
  ensureEpisodeVideoStatusPoll()
}

/** 分集 generate_status 轮询间隔（全局唯一，避免编辑页重复请求） */
export const GENERATE_STATUS_POLL_MS = 8000

type GenerateStatusSubscriber = (episodeId: number, status: EpisodeGenerateStatusPayload) => void

/*
 * videoPollTimer 离开分集页后仍轮询 generate_status
 * videoPollInFlight 避免重叠请求
 * generateStatusSubscribers 编辑页等订阅方同步 UI
 */
let videoPollTimer = 0
let videoPollInFlight = false
const generateStatusSubscribers = new Set<GenerateStatusSubscriber>()

// 订阅分集 generate_status 轮询结果（与 ensureEpisodeVideoStatusPoll 共用同一请求）
export function subscribeEpisodeGenerateStatus(listener: GenerateStatusSubscriber): () => void {
  generateStatusSubscribers.add(listener)
  return () => generateStatusSubscribers.delete(listener)
}

// 后台轮询进行中的分镜视频（不阻塞编辑页）
export function ensureEpisodeVideoStatusPoll(): void {
  if (typeof window === 'undefined') return
  if (videoPollTimer) return
  videoPollTimer = window.setInterval(() => {
    void pollActiveEpisodeVideoJobs()
  }, GENERATE_STATUS_POLL_MS)
  void pollActiveEpisodeVideoJobs()
}

// 按分集拉取状态并写回队列
async function pollActiveEpisodeVideoJobs(): Promise<void> {
  if (videoPollInFlight) return
  const active = jobs.filter(
    (job) =>
      job.kind === 'video' &&
      job.subtype === '分镜视频' &&
      (job.status === 'queued' || job.status === 'running') &&
      typeof job.episodeId === 'number',
  )
  if (active.length === 0) {
    if (videoPollTimer) {
      window.clearInterval(videoPollTimer)
      videoPollTimer = 0
    }
    return
  }
  videoPollInFlight = true
  try {
    const { dramaApi } = await import('../api/drama')
    const episodeIds = [...new Set(active.map((job) => job.episodeId as number))]
    await Promise.all(
      episodeIds.map(async (episodeId) => {
        const epJobs = active.filter((job) => job.episodeId === episodeId)
        const st = await dramaApi.generateStatus(episodeId)
        // 本集已在队列中的分镜（含已完成），用于保留镜序、避免轮询只带进行中子集
        const tracked = jobs.filter(
          (job) =>
            job.kind === 'video' &&
            job.subtype === '分镜视频' &&
            job.episodeId === episodeId,
        )
        const trackedIds = new Set(tracked.map((job) => job.targetId))
        const named = tracked.find((job) => job.title.includes(' · '))
        const episodeName = named?.title.split(' · ')[0]
        syncEpisodeVideoJobs({
          projectId: epJobs[0].projectId,
          episodeId,
          episodeName,
          // 不传 sort_order：轮询无法可靠得知镜序，避免标题被刷成全是「片段 01」
          fragments: tracked.map((job) => ({ id: job.targetId })),
          // 只同步本集已入队分镜，避免 generate_status 全集把无关镜刷进队列并改名
          statusItems: st.fragments.filter((row) => trackedIds.has(row.fragment_id)),
          taskItems: st.tasks,
        })
        generateStatusSubscribers.forEach((fn) => {
          try {
            fn(episodeId, st)
          } catch {
            /* 订阅方异常不影响轮询 */
          }
        })
      }),
    )
  } catch {
    /* 轮询失败下一轮再试 */
  } finally {
    videoPollInFlight = false
  }
}

// 请求打开右下角队列面板
let openRequestSeq = 0
const openListeners = new Set<() => void>()

export function requestOpenDramaGenQueue(): void {
  openRequestSeq += 1
  openListeners.forEach((fn) => fn())
}

export function subscribeDramaGenQueueOpen(listener: () => void): () => void {
  openListeners.add(listener)
  return () => openListeners.delete(listener)
}

export function getDramaGenQueueOpenRequestSeq(): number {
  return openRequestSeq
}

// 清空已结束（完成+失败），并记住 id 防止轮询再次写入
export function clearFinishedDramaGenJobs(): void {
  for (const job of jobs) {
    if (job.status === 'done' || job.status === 'failed') {
      dismissedJobIds.add(job.id)
    }
  }
  jobs = jobs.filter((j) => j.status === 'queued' || j.status === 'running')
  emit()
}

// 将进行中/排队中的视频任务标记为已取消（本地队列同步）
export function markVideoJobsCancelled(fragmentIds?: number[]): void {
  const idSet = fragmentIds ? new Set(fragmentIds.map((id) => videoJobId(id))) : null
  jobs = jobs.map((job) => {
    if (job.kind !== 'video') return job
    if (idSet && !idSet.has(job.id)) return job
    if (job.status !== 'queued' && job.status !== 'running') return job
    return {
      ...job,
      status: 'failed' as const,
      error: '已取消',
      finishedAt: Date.now(),
    }
  })
  emit()
}
