/** 分集分镜 → 共享资产节点连线到各分镜视频节点 */
import type { Edge, Node } from '@xyflow/react'
import {
  resolveDramaMediaUrl,
  type DramaAsset,
  type DramaFragment,
} from '../../../api/drama'
import {
  collectFragmentAssetIds,
  formatFragLabel,
  normalizeAssetTab,
} from '../dramaEpisodeEditUtils'

export type EpisodeFragmentNodeData = {
  fragmentId: number
  sortOrder: number
  label: string
  content: string
  videoUrl: string
  coverUrl: string
  durationSec: number
  linkedCount: number
  [key: string]: unknown
}

export type EpisodeAssetLinkRef = {
  fragmentId: number
  label: string
}

export type EpisodeAssetNodeData = {
  assetId: number
  linkedFragments: EpisodeAssetLinkRef[]
  name: string
  typeLabel: string
  previewUrl: string
  [key: string]: unknown
}

export type EpisodeFlowNodeData = EpisodeFragmentNodeData | EpisodeAssetNodeData

export const EPISODE_FRAGMENT_NODE_WIDTH = 220
export const EPISODE_ASSET_NODE_WIDTH = 148
export const EPISODE_FRAGMENT_COL_GAP = 36
export const EPISODE_FRAGMENT_ROW_GAP = 36
/** 分镜节点预估高度（网格排布间距） */
export const EPISODE_FRAGMENT_NODE_EST_HEIGHT = 400
export const EPISODE_ASSET_NODE_EST_HEIGHT = 196
export const EPISODE_ASSET_ROW_GAP = 14
export const EPISODE_ASSET_POOL_GAP = 40
export const EPISODE_GRID_START_Y = 32

// 分镜视频节点 id
export function episodeFragmentNodeId(fragmentId: number): string {
  return `frag-${fragmentId}`
}

// 出境资产节点 id（全局按 assetId 唯一，跨分镜复用）
export function episodeAssetNodeId(assetId: number): string {
  return `asset-${assetId}`
}

// 按分镜数量计算网格列数（左→右、上→下，避免单列过长）
export function episodeGridColumns(count: number): number {
  if (count <= 3) return Math.max(1, count)
  if (count <= 8) return 3
  return 4
}

// 分镜在网格中的坐标
export function episodeFragmentGridPosition(
  index: number,
  cols: number,
  startX: number,
): { x: number; y: number } {
  const col = index % cols
  const row = Math.floor(index / cols)
  return {
    x: startX + col * (EPISODE_FRAGMENT_NODE_WIDTH + EPISODE_FRAGMENT_COL_GAP),
    y: EPISODE_GRID_START_Y + row * (EPISODE_FRAGMENT_NODE_EST_HEIGHT + EPISODE_FRAGMENT_ROW_GAP),
  }
}

// 分镜顺序连线：同行向右，换行向下
export function episodeSequenceHandles(fromIndex: number, toIndex: number, cols: number) {
  const fromCol = fromIndex % cols
  const toCol = toIndex % cols
  const fromRow = Math.floor(fromIndex / cols)
  const toRow = Math.floor(toIndex / cols)
  if (toRow === fromRow && toCol === fromCol + 1) {
    return { sourceHandle: 'seq-out-r', targetHandle: 'seq-in-l' }
  }
  return { sourceHandle: 'seq-out-b', targetHandle: 'seq-in-t' }
}

// 构建：左侧共享资产池 → 曲线连到右侧分镜网格
export function buildEpisodeFragmentFlow(
  fragments: DramaFragment[],
  assets: DramaAsset[] = [],
): {
  nodes: Node<EpisodeFlowNodeData>[]
  edges: Edge[]
} {
  const ordered = [...fragments].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  const byId = new Map(assets.map((a) => [a.id, a]))
  const nodes: Node<EpisodeFlowNodeData>[] = []
  const edges: Edge[] = []
  const gridCols = episodeGridColumns(ordered.length)
  const fragGridStartX = EPISODE_ASSET_NODE_WIDTH + EPISODE_ASSET_POOL_GAP

  const fragLabels = new Map<number, string>()
  const fragIndexById = new Map<number, number>()
  ordered.forEach((frag, index) => {
    fragLabels.set(frag.id, formatFragLabel(index, frag.duration_sec))
    fragIndexById.set(frag.id, index)
  })

  // assetId → 关联分镜 id 列表（保序）
  const assetToFragments = new Map<number, number[]>()
  ordered.forEach((frag) => {
    for (const assetId of collectFragmentAssetIds(frag)) {
      const list = assetToFragments.get(assetId) ?? []
      if (!list.includes(frag.id)) list.push(frag.id)
      assetToFragments.set(assetId, list)
    }
  })

  const uniqueAssetIds = [...assetToFragments.keys()].sort((a, b) => {
    const fragA = assetToFragments.get(a)?.[0]
    const fragB = assetToFragments.get(b)?.[0]
    const indexA = fragA != null ? fragIndexById.get(fragA) ?? 999 : 999
    const indexB = fragB != null ? fragIndexById.get(fragB) ?? 999 : 999
    return indexA - indexB
  })

  let lastAssetY = EPISODE_GRID_START_Y
  uniqueAssetIds.forEach((assetId) => {
    const asset = byId.get(assetId)
    const fragmentIds = assetToFragments.get(assetId) ?? []
    const tab = normalizeAssetTab(asset?.type || '')
    const linkedIndices = fragmentIds
      .map((fid) => fragIndexById.get(fid))
      .filter((idx): idx is number => idx != null)
    const anchorY =
      linkedIndices.length > 0
        ? linkedIndices.reduce(
            (sum, idx) => sum + episodeFragmentGridPosition(idx, gridCols, fragGridStartX).y,
            0,
          ) / linkedIndices.length
        : lastAssetY
    const y = Math.max(anchorY - EPISODE_ASSET_NODE_EST_HEIGHT / 2, lastAssetY)
    lastAssetY = y + EPISODE_ASSET_NODE_EST_HEIGHT + EPISODE_ASSET_ROW_GAP

    nodes.push({
      id: episodeAssetNodeId(assetId),
      type: 'episodeAsset',
      position: { x: 0, y },
      data: {
        assetId,
        linkedFragments: fragmentIds.map((fragmentId) => ({
          fragmentId,
          label: fragLabels.get(fragmentId) || `镜 ${fragmentId}`,
        })),
        name: asset?.name || `资产 ${assetId}`,
        typeLabel: tab || asset?.type || '资产',
        previewUrl: resolveDramaMediaUrl(asset?.cover || asset?.url) || '',
      },
      draggable: true,
    })

    for (const fragmentId of fragmentIds) {
      edges.push({
        id: `ea-${fragmentId}-${assetId}`,
        source: episodeAssetNodeId(assetId),
        target: episodeFragmentNodeId(fragmentId),
        targetHandle: 'assets',
        type: 'default',
        animated: false,
      })
    }
  })

  ordered.forEach((frag, index) => {
    const fragNodeId = episodeFragmentNodeId(frag.id)
    const linkedIds = collectFragmentAssetIds(frag)
    const { x, y } = episodeFragmentGridPosition(index, gridCols, fragGridStartX)

    nodes.push({
      id: fragNodeId,
      type: 'episodeFragment',
      position: { x, y },
      data: {
        fragmentId: frag.id,
        sortOrder: frag.sort_order ?? index,
        label: formatFragLabel(index, frag.duration_sec),
        content: frag.content || '',
        videoUrl: resolveDramaMediaUrl(frag.video) || '',
        coverUrl: resolveDramaMediaUrl(frag.cover) || '',
        durationSec: frag.duration_sec && frag.duration_sec > 0 ? frag.duration_sec : 8,
        linkedCount: linkedIds.length,
      },
      draggable: true,
    })

    if (index > 0) {
      const prev = ordered[index - 1]
      const handles = episodeSequenceHandles(index - 1, index, gridCols)
      edges.push({
        id: `ef-${prev.id}-${frag.id}`,
        source: episodeFragmentNodeId(prev.id),
        sourceHandle: handles.sourceHandle,
        target: fragNodeId,
        targetHandle: handles.targetHandle,
        type: 'default',
        animated: false,
        style: { strokeDasharray: '6 4', stroke: '#cbd5e1' },
      })
    }
  })

  return { nodes, edges }
}
