import { marketText as mt } from './translate.ts'
import type { Handoff } from './api'

export type PublishEpisode = {
  id: number; name: string; episode_number: number; fragment_count: number; completed_count: number
  ready: boolean; reason?: string | null; reason_code?: string; reason_label?: string; source_version: string
}
export type ImportedEpisode = {
  source_episode_id: number; episode_id: number; source_version: string; status: string; handoff_id?: number | null; requires_update?: boolean
}
export type PublishSeries = {
  id: number; title: string; version: number; listed?: boolean; audit_status?: string; imports: ImportedEpisode[]
}
export type DramaPublishContext = {
  project: { id: number; title: string; description?: string }
  episodes: PublishEpisode[]; series: PublishSeries[]; authorization_ready: boolean; storage_configured: boolean
}
export type DramaPublishResult = { series_id: number; items: { id: number }[]; handoffs: Handoff[] }

export function sourceRelation(episode: PublishEpisode, target?: PublishSeries) {
  const existing = target?.imports.find(item => item.source_episode_id === episode.id)
  return { existing, changed: Boolean(existing && (existing.requires_update || existing.status === 'legacy' || existing.source_version !== episode.source_version)) }
}

export function publishSelection(context: DramaPublishContext, selected: number[], updates: number[], target?: PublishSeries) {
  return context.episodes.filter(item => selected.includes(item.id)).sort((a, b) => a.episode_number - b.episode_number).map(episode => {
    if (!episode.ready) throw new Error(`${episode.name}: ${episode.reason_label || episode.reason || mt("分集尚未全部生成完成")}`)
    const { changed } = sourceRelation(episode, target)
    if (changed && !updates.includes(episode.id)) throw new Error(mt("请确认更新「{0}」的新版本", [episode.name]))
    return { episode_id: episode.id, source_version: episode.source_version, update: changed }
  })
}

const phaseLabels: Record<string, string> = new Proxy<Record<string, string>>({
  queued: '排队中', pending: '排队中', syncing: '同步素材', downloading: '同步素材', copying: '同步素材',
  composing: '拼接整集', concatenating: '拼接整集', validating: '校验视频', ready: '已就绪', failed: '同步失败',
}, { get: (target, key: string) => target[key] ? mt(target[key]) : undefined })
export function handoffLabel(handoff: Handoff) {
  return phaseLabels[handoff.phase || ''] || handoff.label || phaseLabels[handoff.status] || mt("同步中")
}
export function isHandoffActive(handoff: Pick<Handoff, 'status'>) {
  return handoff.status === 'pending' || handoff.status === 'running'
}
// 一个分集可能保留多个历史任务；只展示最新任务，避免旧任务覆盖新状态。
export function latestEpisodeHandoffs(items: Handoff[]) {
  const latest = new Map<number, Handoff>()
  for (const item of items) {
    if (item.episode_id && (!latest.has(item.episode_id) || latest.get(item.episode_id)!.id < item.id)) latest.set(item.episode_id, item)
  }
  return [...latest.values()]
}

type SyncEpisode = { id?: number; version?: number; asset_id: number | null; cover_asset_id: number | null; source?: string }
// 接纳后台同步的系列封面；用户选过或主动清空后，后续轮询不能覆盖本地意图。
export function mergeSyncedCover(current: number | null, remote: number | null, previous: number | null, edited = false) {
  return !edited && current === previous ? remote : current
}
// 只回填同步产物和版本；封面被用户编辑过时保留本地选择，标题和价格始终保留。
export function mergeSyncedEpisodes<T extends SyncEpisode>(current: T[], remote: T[], previous: T[]) {
  return current.map(episode => {
    const fresh = remote.find(item => item.id === episode.id)
    if (!episode.id || !fresh) return episode
    const before = previous.find(item => item.id === episode.id)
    return {
      ...episode, version: fresh.version,
      asset_id: before && before.asset_id !== episode.asset_id ? episode.asset_id : fresh.asset_id,
      cover_asset_id: before && before.cover_asset_id !== episode.cover_asset_id ? episode.cover_asset_id : fresh.cover_asset_id,
      source: before && before.source !== episode.source ? episode.source : fresh.source,
    }
  })
}
