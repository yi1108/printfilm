/** 画布节点媒体：识别可播放类型与下载文件名 */
import { fetchMediaBlob, triggerBlobDownload } from './clientDownload'

const VIDEO_EXT = /\.(mp4|webm|mov)(\?|#|$)/i
const AUDIO_EXT = /\.(mp3|wav|m4a|aac|ogg|flac)(\?|#|$)/i

/** 成片 URL 是否可按视频播放 */
export function isPlayableVideoUrl(url: string) {
  return VIDEO_EXT.test(url)
}

/** URL 是否为音频文件 */
export function isAudioUrl(url: string) {
  return AUDIO_EXT.test(url)
}

/** 从展示名生成安全文件名主干 */
export function sanitizeMediaBasename(label: string) {
  const cleaned = (label || '未命名')
    .replace(/[<>:"/\\|?*\x00-\x1f]+/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60)
  return cleaned || '未命名'
}

/** 从 URL 推断扩展名 */
export function extFromMediaUrl(url: string, fallback: string) {
  const path = url.split('?')[0]?.split('#')[0] || ''
  const match = path.match(/\.([a-z0-9]{2,5})$/i)
  return match ? match[1].toLowerCase() : fallback
}

/** 组合下载文件名 */
export function canvasMediaFilename(label: string, url: string, fallbackExt: string) {
  return `${sanitizeMediaBasename(label)}.${extFromMediaUrl(url, fallbackExt)}`
}

/** 拉取并触发浏览器下载；跨域失败时新开标签 */
export async function downloadCanvasMedia(url: string, filename: string) {
  try {
    const blob = await fetchMediaBlob(url)
    triggerBlobDownload(blob, filename)
  } catch {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.rel = 'noopener noreferrer'
    link.target = '_blank'
    document.body.appendChild(link)
    link.click()
    link.remove()
  }
}

/** 把文本存成文件下载 */
export function downloadCanvasText(text: string, label: string) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  triggerBlobDownload(blob, `${sanitizeMediaBasename(label)}.txt`)
}
