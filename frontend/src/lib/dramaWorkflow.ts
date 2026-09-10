import type { DramaProject, DramaProjectListItem } from '../api/drama'

export type DramaWorkflow = 'script' | 'canvas'

const CANVAS_SOURCE_MARKER = '自由画布创作项目'
const CANVAS_TITLE_MARKER = '自由画布'

type WorkflowSource = {
  workflow?: string | null
  title?: string | null
  params?: Record<string, unknown> | null
  script?: { source?: string | null } | null
}

/** 解析漫剧工作流：canvas=自由画布；script=大纲分集 */
export function resolveDramaWorkflow(item: WorkflowSource | null | undefined): DramaWorkflow {
  const raw = String(item?.workflow || item?.params?.workflow || '')
    .trim()
    .toLowerCase()
  if (raw === 'canvas' || raw === 'script') return raw

  const title = String(item?.title || '')
  if (title.includes(CANVAS_TITLE_MARKER)) return 'canvas'

  const source = String(item?.script?.source || '')
  if (source.includes(CANVAS_SOURCE_MARKER)) return 'canvas'

  return 'script'
}

/** 是否自由画布项目 */
export function isCanvasWorkflow(
  item: DramaProject | DramaProjectListItem | WorkflowSource | null | undefined,
): boolean {
  return resolveDramaWorkflow(item) === 'canvas'
}

/** 项目入口路径：画布仅进 canvas，普通进工作台 */
export function dramaProjectEntryPath(
  item: DramaProject | DramaProjectListItem | WorkflowSource,
): string {
  const id = Number((item as { id?: number }).id)
  if (!Number.isFinite(id) || id <= 0) return '/drama'
  if (isCanvasWorkflow(item)) return `/drama/projects/${id}/canvas`
  return `/drama/projects/${id}`
}

/** 列表卡片 meta 文案 */
export function formatDramaCardMeta(item: DramaProjectListItem): string {
  if (isCanvasWorkflow(item)) {
    return `自由画布 · ${item.asset_count || 0} 节点资产`
  }
  if (item.has_script) {
    return `已写剧本 · ${item.episode_count || 0} 集 · ${item.asset_count || 0} 资产`
  }
  return `草稿 · 待写剧本 · ${item.asset_count || 0} 资产`
}
