/** 将后端/旧版画布数据规范化为 xyflow 节点与边 */
import type { Edge, Node } from '@xyflow/react'
import {
  CANVAS_NODE_DEFAULT_LABEL,
  type CanvasAssetNodeData,
  type CanvasNodeKind,
} from './canvasTypes'

const KIND_SET = new Set<CanvasNodeKind>([
  'character',
  'scene',
  'video',
  'image',
  'text',
  'audio',
])

/** 判断是否为合法节点类型 */
function isCanvasNodeKind(value: unknown): value is CanvasNodeKind {
  return typeof value === 'string' && KIND_SET.has(value as CanvasNodeKind)
}

/** 规范化单个节点（兼容旧 { id, label, x, y }） */
export function normalizeCanvasNode(raw: unknown, index: number): Node<CanvasAssetNodeData> | null {
  if (!raw || typeof raw !== 'object') return null
  const item = raw as Record<string, unknown>
  const id = String(item.id || `n-${index}`)

  /* 新版 xyflow：position + data */
  if (item.position && typeof item.position === 'object') {
    const pos = item.position as { x?: unknown; y?: unknown }
    const dataRaw = (item.data && typeof item.data === 'object' ? item.data : {}) as Record<
      string,
      unknown
    >
    const kind = isCanvasNodeKind(dataRaw.kind)
      ? dataRaw.kind
      : isCanvasNodeKind(item.type)
        ? item.type
        : 'image'
    const label =
      typeof dataRaw.label === 'string' && dataRaw.label
        ? dataRaw.label
        : CANVAS_NODE_DEFAULT_LABEL[kind]

    return {
      id,
      type: 'asset',
      position: {
        x: Number(pos.x) || 0,
        y: Number(pos.y) || 0,
      },
      data: {
        kind,
        label,
        assetId: typeof dataRaw.assetId === 'number' ? dataRaw.assetId : undefined,
        mediaUrl:
          typeof dataRaw.mediaUrl === 'string'
            ? dataRaw.mediaUrl
            : typeof dataRaw.url === 'string'
              ? dataRaw.url
              : null,
        textContent: typeof dataRaw.textContent === 'string' ? dataRaw.textContent : undefined,
      },
    }
  }

  /* 旧版绝对定位：x / y / label */
  if ('x' in item || 'y' in item || 'label' in item) {
    const label =
      typeof item.label === 'string' && item.label
        ? item.label
        : CANVAS_NODE_DEFAULT_LABEL.image
    return {
      id,
      type: 'asset',
      position: {
        x: Number(item.x) || 40 + (index % 5) * 180,
        y: Number(item.y) || 40 + Math.floor(index / 5) * 120,
      },
      data: {
        kind: 'image',
        label,
      },
    }
  }

  return null
}

/** 规范化边列表 */
export function normalizeCanvasEdges(raw: unknown): Edge[] {
  if (!Array.isArray(raw)) return []
  const edges: Edge[] = []
  for (let i = 0; i < raw.length; i++) {
    const item = raw[i]
    if (!item || typeof item !== 'object') continue
    const e = item as Record<string, unknown>
    const source = String(e.source || '')
    const target = String(e.target || '')
    if (!source || !target || source === target) continue
    edges.push({
      id: String(e.id || `e-${source}-${target}-${i}`),
      source,
      target,
    })
  }
  return edges
}

/** 规范化节点列表 */
export function normalizeCanvasNodes(raw: unknown): Node<CanvasAssetNodeData>[] {
  if (!Array.isArray(raw)) return []
  const nodes: Node<CanvasAssetNodeData>[] = []
  for (let i = 0; i < raw.length; i++) {
    const node = normalizeCanvasNode(raw[i], i)
    if (node) nodes.push(node)
  }
  return nodes
}

/** 计算新节点落在视口中心的坐标 */
export function getViewportCenterNodePosition(
  screenToFlowPosition: (p: { x: number; y: number }) => { x: number; y: number },
  size: { width: number; height: number },
) {
  const pane = document.querySelector('.react-flow')
  const bounds = pane?.getBoundingClientRect() ?? {
    left: 0,
    top: 0,
    width: window.innerWidth,
    height: window.innerHeight,
  }
  const center = screenToFlowPosition({
    x: bounds.left + bounds.width / 2,
    y: bounds.top + bounds.height / 2,
  })
  return {
    x: center.x - size.width / 2,
    y: center.y - size.height / 2,
  }
}
