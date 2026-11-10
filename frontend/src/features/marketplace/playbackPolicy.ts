import { marketText as mt } from './translate.ts'
/** 与后端播放策略保持一致；参考价为零不能替代明确的免费类型。 */
export function isFreeWork(item: { sale_type?: string }) {
  return item.sale_type === 'free'
}

export function isFreeEpisode(series: { sale_type?: string; free_episode_count?: number }, episodeNo: number) {
  return isFreeWork(series) || (episodeNo > 0 && episodeNo <= (series.free_episode_count || 0))
}

export function previewStatusLabel(status: string | undefined, free: boolean) {
  if (free) return mt("无需试看")
  const labels: Record<string, string> = {
    none: mt("未生成"), missing: mt("未生成"), pending: mt("排队中"), running: mt("正在生成短试看"),
    done: mt("短试看已就绪"), failed: mt("生成失败，可重试"), cancelled: mt("任务已取消"),
  }
  return labels[status || 'none'] || status
}
