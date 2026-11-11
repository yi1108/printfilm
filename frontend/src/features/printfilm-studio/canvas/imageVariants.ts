/** 从节点 data / 任务结果中收集多图 URL，供切换、对比、拆开使用。 */
export function collectMediaUrls(data: Record<string, unknown> | null | undefined): string[] {
  if (!data) return []
  const fromList = Array.isArray(data.mediaUrls)
    ? data.mediaUrls.map((item) => String(item || '').trim()).filter(Boolean)
    : []
  if (fromList.length) return Array.from(new Set(fromList))
  const single = String(data.mediaUrl || data.url || data.cover || '').trim()
  return single ? [single] : []
}

/** 从任务结果 payload 提取全部媒体地址。 */
export function mediaUrlsFromPayload(result: Record<string, unknown> | null | undefined): string[] {
  if (!result) return []
  const list: string[] = []
  if (Array.isArray(result.urls)) {
    for (const item of result.urls) {
      const url = String(item || '').trim()
      if (url) list.push(url)
    }
  }
  for (const key of ['url', 'video_url', 'audio_url', 'image_url', 'cover'] as const) {
    const url = String(result[key] || '').trim()
    if (url) list.push(url)
  }
  return Array.from(new Set(list))
}

/** 钳制当前索引，保证落在合法范围内。 */
export function clampMediaIndex(index: unknown, total: number): number {
  if (total <= 0) return 0
  const value = Number(index)
  if (!Number.isFinite(value)) return 0
  return Math.min(Math.max(0, Math.floor(value)), total - 1)
}
