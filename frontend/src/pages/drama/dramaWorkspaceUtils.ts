/** Shared helpers for drama project workspace steps. */
import type { DramaEpisodeBody, DramaProject, DramaScript } from '../../api/drama'

// 解析 episode_content 为分集数组
export function parseEpisodeBodies(script: DramaScript | null | undefined): DramaEpisodeBody[] {
  const raw = script?.episode_content
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (Array.isArray(raw.episodes)) return raw.episodes
  return []
}

// 读取摘要状态
export function getSummaryStatus(script: DramaScript | null | undefined): string {
  return String((script?.params || {}).summary_status || (script?.summary ? 'completed' : 'pending'))
}

// 读取分集剧本状态
export function getEpisodeContentStatus(script: DramaScript | null | undefined): string {
  return String((script?.params || {}).episode_content_status || 'pending')
}

// 读取画面风格 ID
export function getImageStyleId(
  script: DramaScript | null | undefined,
  project: DramaProject | null,
): string {
  const fromScript = (script?.params || {}).image_style_id
  const fromProject = (project?.params || {}).image_style_id
  return String(fromScript || fromProject || '')
}

// 写回分集正文时保持与原结构一致（数组或 { episodes }）
export function buildEpisodeContentUpdate(
  script: DramaScript | null | undefined,
  bodies: DramaEpisodeBody[],
): DramaScript['episode_content'] {
  const raw = script?.episode_content
  if (Array.isArray(raw)) return bodies
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return { ...(raw as Record<string, unknown>), episodes: bodies }
  }
  return { episodes: bodies }
}
