/** 漫剧资产是否已有形象图（AI 生成或本地上传） */
import type { DramaAsset } from '../api/drama'

// 从 params 中读取可能存在的预览 URL（画布同步等）
function readParamsMediaUrl(asset: DramaAsset): string {
  const params = asset.params
  if (!params || typeof params !== 'object') return ''
  const record = params as Record<string, unknown>
  for (const key of ['mediaUrl', 'previewUrl', 'imageUrl']) {
    const value = String(record[key] || '').trim()
    if (value) return value
  }
  const gen = record.generation
  if (gen && typeof gen === 'object') {
    const g = gen as Record<string, unknown>
    for (const key of ['cover', 'url', 'imageUrl']) {
      const value = String(g[key] || '').trim()
      if (value) return value
    }
  }
  return ''
}

// 资产是否已有有效形象图
export function dramaAssetHasImage(asset: DramaAsset): boolean {
  if ((asset.cover || '').trim() || (asset.url || '').trim()) return true
  return Boolean(readParamsMediaUrl(asset))
}

// 是否仍需生图（无图且非纯音频类资产时可批量入队）
export function dramaAssetNeedsImageGeneration(asset: DramaAsset): boolean {
  const kind = (asset.type || '').toLowerCase()
  if (['voice', 'video', 'audio', 'text'].includes(kind)) return false
  return !dramaAssetHasImage(asset)
}

// 卡片/弹窗生图按钮文案（queueLabel 为排队态文案，有值时优先）
export function dramaAssetImageGenButtonLabel(
  asset: DramaAsset,
  queueLabel: string | null,
): string {
  if (queueLabel) return queueLabel
  return dramaAssetHasImage(asset) ? '重新生成形象' : '生成形象'
}
