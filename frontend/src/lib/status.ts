import { getActiveLocale } from '../i18n/detect'
import { messages } from '../i18n/messages'

export const RUNNING = new Set([
  'SCRIPTING',
  'IMAGING',
  'VIDEOING',
  'AUDIOING',
  'COMPOSING',
  'AUDITING',
  'PARALLEL_ASSETS',
])

// 按当前界面语言取状态文案（兼容旧的 STATUS_CN[code] 写法）
export const STATUS_CN: Record<string, string> = new Proxy(
  {},
  {
    get(_target, prop: string) {
      const map = messages[getActiveLocale()].status as Record<string, string>
      return map[prop] || prop
    },
  },
)

export function isRunning(status: string) {
  return RUNNING.has(status)
}

export function hasActiveTasks(project: {
  active_tasks?: Array<{ status: string; cancel_requested?: boolean | null }> | null
}) {
  const activeStatuses = ['pending', 'leased', 'running', 'awaiting_poll', 'awaiting_review']
  return Boolean(
    project.active_tasks?.some(
      (task) => !task.cancel_requested && activeStatuses.includes(task.status),
    ),
  )
}

/**
 * Prefer stage inferred from shot assets when status is still SCRIPTING
 * (e.g. continue-generate briefly labeled wrong, or worker lag).
 */
export function effectiveStatus(project: {
  status: string
  pipeline_mode?: string | null
  shots?: Array<{ image_url?: string | null; audio_url?: string | null; video_url?: string | null }>
}): string {
  const status = project.status
  const shots = project.shots || []
  if (status !== 'SCRIPTING' || shots.length === 0) return status

  const full = project.pipeline_mode !== 'image_text'
  const imgs = shots.filter((s) => s.image_url).length
  const auds = shots.filter((s) => s.audio_url).length
  const vids = shots.filter((s) => s.video_url).length
  const n = shots.length
  // full 管线配音由视频模型完成，不要求 TTS audio_url
  const assetsOk = full ? imgs === n : imgs === n && auds === n

  if (assetsOk) {
    if (full && vids < n) return 'VIDEOING'
    if (full && vids === n) return 'COMPOSING'
    if (!full) return 'COMPOSING'
  }
  if (imgs > 0 || auds > 0) return 'IMAGING'
  return status
}

export function statusLabel(projectOrStatus: string | Parameters<typeof effectiveStatus>[0]) {
  const status = typeof projectOrStatus === 'string' ? projectOrStatus : effectiveStatus(projectOrStatus)
  return STATUS_CN[status] || status
}

export function statusTone(status: string): 'ok' | 'bad' | 'run' | 'idle' {
  if (status === 'DONE') return 'ok'
  if (status === 'FAILED' || status === 'REJECTED' || status === 'CANCELLED') return 'bad'
  if (isRunning(status)) return 'run'
  return 'idle'
}

/** Per-shot statuses from pipeline */
export const SHOT_STATUS_CN: Record<string, string> = new Proxy(
  {},
  {
    get(_target, prop: string) {
      const map = messages[getActiveLocale()].shotStatus as Record<string, string>
      return map[prop] || STATUS_CN[prop] || prop
    },
  },
)

export function shotStatusLabel(status: string) {
  return SHOT_STATUS_CN[status] || STATUS_CN[status] || status
}

export function shotIsDone(status: string) {
  return ['AUDIO_READY', 'VIDEO_READY', 'DONE', 'IMAGE_READY'].includes(status)
}

export function formatMmSs(seconds: number) {
  const s = Math.max(0, Math.round(seconds || 0))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
}

export const CREATE_STEPS = [
  { key: 'template', label: '选择模板' },
  { key: 'content', label: '输入内容' },
  { key: 'style', label: '风格配置' },
  { key: 'generate', label: '开始生成' },
]

export const BOARD_STEPS = [
  { key: 'theme', label: '输入主题' },
  { key: 'smart', label: '智能生成' },
  { key: 'preset', label: '精细画面' },
  { key: 'board', label: '生成分镜' },
  { key: 'compose', label: '成片预览' },
]
