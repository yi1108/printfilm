/** 漫剧画面风格预览图 URL（public jpg/png → 后端 static → svg 占位） */
import type { ImageStyleId } from './dramaImageStyles'

// 返回前端 public 根路径
function publicBase(): string {
  return import.meta.env.BASE_URL.endsWith('/')
    ? import.meta.env.BASE_URL
    : `${import.meta.env.BASE_URL}/`
}

// 返回 API 根路径（用于 /static/… 预览图）
function apiBase(): string {
  const raw = import.meta.env.VITE_API_BASE
  if (typeof raw === 'string' && raw.trim()) {
    return raw.replace(/\/$/, '')
  }
  return ''
}

// 返回风格预览候选 URL 列表（按优先级）
export function getDramaImageStylePreviewCandidates(styleId: ImageStyleId): string[] {
  const pub = publicBase()
  const urls = [
    `${pub}image-styles/${styleId}.jpg`,
    `${pub}image-styles/${styleId}.png`,
  ]
  const api = apiBase()
  if (api) {
    urls.push(`${api}/static/drama/image-styles/${styleId}.png`)
    urls.push(`${api}/static/drama/image-styles/${styleId}.jpg`)
  }
  urls.push(`${pub}image-styles/${styleId}.svg`)
  return urls
}

// 返回风格预览图 URL（优先 jpg）
export function getDramaImageStylePreviewUrl(styleId: ImageStyleId): string {
  return getDramaImageStylePreviewCandidates(styleId)[0]
}

// 返回风格预览占位 SVG
export function getDramaImageStylePreviewFallbackUrl(styleId: ImageStyleId): string {
  const candidates = getDramaImageStylePreviewCandidates(styleId)
  return candidates[candidates.length - 1]
}
