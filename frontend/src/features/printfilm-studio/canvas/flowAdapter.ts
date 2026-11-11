import { decodeCanvasDocument, encodeCanvasDocument, type CanvasDocument } from './canvasCodec.ts'

export const STUDIO_ADDABLE_TYPES = ['text', 'image', 'video', 'audio', 'script'] as const
export type StudioAddableType = (typeof STUDIO_ADDABLE_TYPES)[number]

export const STUDIO_NODE_LABELS: Record<string, string> = {
  text: '文本',
  image: '图片',
  video: '视频',
  audio: '音频',
  script: '剧本',
  asset: '资产',
  task: '任务',
  group: '分组',
}

type FlowNode = { id: string; type?: string | null; position: { x: number; y: number }; data?: Record<string, unknown> }
type FlowEdge = { id: string; source: string; target: string }

/** 把持久化画布转成 React Flow 可渲染的节点、连线和视口。 */
export function flowFromDocument(raw: unknown): { nodes: FlowNode[]; edges: FlowEdge[]; viewport: CanvasDocument['viewport'] } {
  const document = decodeCanvasDocument(raw)
  return {
    nodes: document.nodes.map((node) => ({ ...node })),
    edges: document.edges.map((edge) => ({ ...edge })),
    viewport: document.viewport,
  }
}

/** 只保留可持久化字段，避免把选中态和测量结果写回服务端。 */
export function documentFromFlow(nodes: FlowNode[], edges: FlowEdge[], viewport: CanvasDocument['viewport']): CanvasDocument {
  return encodeCanvasDocument({
    toonflowCanvas: true,
    version: 1,
    nodes: nodes.map((node) => ({
      ...Object.fromEntries(Object.entries(node).filter(([key]) => !['selected', 'measured', 'dragging', 'resizing'].includes(key))),
      id: node.id,
      type: node.type || 'text',
      position: node.position,
      data: node.data && typeof node.data === 'object' ? node.data : {},
    })),
    edges: edges.map((edge) => ({ ...Object.fromEntries(Object.entries(edge).filter(([key]) => key !== 'selected')), id: edge.id, source: edge.source, target: edge.target })),
    viewport,
  })
}
