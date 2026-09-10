/** 将项目资产与已保存画布布局合并为 React Flow 节点/边 */
import type { Edge, Node } from '@xyflow/react'
import { resolveDramaMediaUrl, type DramaAsset } from '../../../api/drama'
import { readEditableVisualPrompt } from '../../../lib/dramaVisualPrompt'
import { readVideoGenerationOptions } from '../../../lib/dramaVideoGenerationOptions'
import { readAssetVoiceBinding } from '../CharacterVoiceBindModal'
import {
  CANVAS_NODE_DEFAULT_LABEL,
  CANVAS_NODE_SIZE,
  type CanvasAssetNodeData,
  type CanvasNodeKind,
} from './canvasTypes'
import { normalizeCanvasEdges, normalizeCanvasNodes } from './canvasNormalize'

/** Drama 资产 type → 画布节点 kind */
export function dramaAssetTypeToKind(type: string | null | undefined): CanvasNodeKind {
  const t = String(type || '').toLowerCase()
  if (t === 'character') return 'character'
  if (t === 'scene') return 'scene'
  if (t === 'video') return 'video'
  if (t === 'audio') return 'audio'
  if (t === 'text') return 'text'
  /* prop / material / none / 其他 → 图片卡片 */
  return 'image'
}

/** 根据资产 ID 生成稳定节点 ID */
export function getCanvasNodeId(assetId: number) {
  return `asset-${assetId}`
}

/** 从资产构建节点 data */
export function buildNodeDataFromAsset(asset: DramaAsset): CanvasAssetNodeData {
  const kind = dramaAssetTypeToKind(asset.type)
  const params = (asset.params || {}) as Record<string, unknown>
  const promptHint = readEditableVisualPrompt(asset)
  const videoOptions =
    kind === 'video' ? readVideoGenerationOptions(params.videoOptions || params) : undefined
  const label =
    (typeof asset.name === 'string' && asset.name.trim()) || CANVAS_NODE_DEFAULT_LABEL[kind]
  const voice = kind === 'character' ? readAssetVoiceBinding(asset) : null

  return {
    kind,
    label,
    assetId: asset.id,
    mediaUrl: resolveDramaMediaUrl(asset.url || asset.cover) || null,
    textContent: kind === 'text' ? String(params.textContent || '') : undefined,
    promptHint,
    videoOptions,
    characterName: kind === 'character' ? label : undefined,
    voiceLabel: voice?.label || null,
    voiceUrl: voice?.url || null,
  }
}

type SavedLayoutIndex = {
  byAssetId: Map<number, Node<CanvasAssetNodeData>>
  orphanNodes: Node<CanvasAssetNodeData>[]
  edges: Edge[]
}

/** 索引已保存画布节点（按 assetId） */
function indexSavedLayout(rawNodes: unknown, rawEdges: unknown): SavedLayoutIndex {
  const nodes = normalizeCanvasNodes(rawNodes)
  const edges = normalizeCanvasEdges(rawEdges)
  const byAssetId = new Map<number, Node<CanvasAssetNodeData>>()
  const orphanNodes: Node<CanvasAssetNodeData>[] = []

  for (const node of nodes) {
    const assetId = node.data.assetId
    if (typeof assetId === 'number' && assetId > 0) {
      byAssetId.set(assetId, node)
    } else {
      orphanNodes.push(node)
    }
  }

  return { byAssetId, orphanNodes, edges }
}

/**
 * 合并项目资产与已保存布局：
 * - 普通项目：资产列表决定节点；已保存布局提供位置与连线
 * - 自由画布：仅恢复「已保存在画布上」的资产节点，避免删除后刷新又冒出来
 */
export function mergeAssetsWithCanvasLayout(
  assets: DramaAsset[],
  savedNodes: unknown,
  savedEdges: unknown,
  options?: { freeCanvas?: boolean },
): { nodes: Node<CanvasAssetNodeData>[]; edges: Edge[] } {
  const freeCanvas = Boolean(options?.freeCanvas)
  const saved = indexSavedLayout(savedNodes, savedEdges)
  const nodes: Node<CanvasAssetNodeData>[] = []
  let maxRight = 0
  const assetById = new Map(assets.map((a) => [a.id, a]))

  if (freeCanvas) {
    /* 自由画布：只渲染布局里仍存在、且资产未删的节点（不按资产列表回补） */
    for (const [assetId, savedNode] of saved.byAssetId) {
      const asset = assetById.get(assetId)
      if (!asset) continue
      const data = buildNodeDataFromAsset(asset)
      const size = CANVAS_NODE_SIZE[data.kind]
      nodes.push({
        ...savedNode,
        id: getCanvasNodeId(asset.id),
        type: 'asset',
        data: {
          ...savedNode.data,
          ...data,
          label: (savedNode.data.label as string) || data.label,
          promptHint: data.promptHint || savedNode.data.promptHint || '',
          videoOptions: data.videoOptions || savedNode.data.videoOptions,
          textContent:
            data.kind === 'text'
              ? savedNode.data.textContent ?? data.textContent
              : data.textContent,
        },
      })
      maxRight = Math.max(maxRight, savedNode.position.x + size.width + 40)
    }
    /* 无 assetId 的孤儿节点仍保留 */
    for (const orphan of saved.orphanNodes) {
      nodes.push(orphan)
    }
  } else {
    for (const asset of assets) {
      const data = buildNodeDataFromAsset(asset)
      const kind = data.kind
      const size = CANVAS_NODE_SIZE[kind]
      const savedNode = saved.byAssetId.get(asset.id)

      if (savedNode) {
        nodes.push({
          ...savedNode,
          id: getCanvasNodeId(asset.id),
          type: 'asset',
          data: {
            ...savedNode.data,
            ...data,
            textContent:
              kind === 'text'
                ? savedNode.data.textContent ?? data.textContent
                : data.textContent,
          },
        })
        maxRight = Math.max(maxRight, savedNode.position.x + size.width + 40)
      } else {
        nodes.push({
          id: getCanvasNodeId(asset.id),
          type: 'asset',
          position: {
            x: maxRight,
            y: 80,
          },
          data,
        })
        maxRight += size.width + 40
      }
    }

    /* 无 assetId 的旧自由节点仍保留，排在资产行下方 */
    for (const orphan of saved.orphanNodes) {
      nodes.push({
        ...orphan,
        position: {
          x: orphan.position.x,
          y: Math.max(orphan.position.y, 420),
        },
      })
    }

    /* 首次进入（无任何已保存位置）时整行横向排布 */
    if (saved.byAssetId.size === 0 && assets.length > 0) {
      let i = 0
      for (const node of nodes) {
        if (typeof node.data.assetId !== 'number') continue
        const size = CANVAS_NODE_SIZE[node.data.kind]
        node.position = { x: i * (size.width + 40), y: 80 }
        i += 1
      }
    }
  }

  /* 过滤掉指向已删除资产的边 */
  const nodeIds = new Set(nodes.map((n) => n.id))
  const edges = saved.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))

  return { nodes, edges }
}
