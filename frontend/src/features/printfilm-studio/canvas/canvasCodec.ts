import { normalizeImageDraft } from './nodeDraft.ts'
export type CanvasNode = { id: string; type: string; position: { x: number; y: number }; data: Record<string, unknown>; [key: string]: unknown }
export type CanvasEdge = { id: string; source: string; target: string; [key: string]: unknown }
export type CanvasDocument = { toonflowCanvas: true; version: 1; nodes: CanvasNode[]; edges: CanvasEdge[]; viewport: { x: number; y: number; zoom: number }; [key: string]: unknown }

/** Printfilm Studio 的持久化边界：保留历史 Toonflow 字段和未知扩展字段。 */
export function decodeCanvasDocument(raw: unknown): CanvasDocument {
  const input = raw && typeof raw === 'object' ? { ...(raw as Record<string, unknown>) } : {}
  if (input.version !== undefined && input.version !== 1) throw new Error('不支持的画布版本')
  if (input.toonflowCanvas !== undefined && input.toonflowCanvas !== true) throw new Error('画布兼容标记无效')
  const nodes = Array.isArray(input.nodes) ? input.nodes : []
  const ids = new Set<string>()
  const normalizedNodes = nodes.map((rawNode) => {
    const node = rawNode && typeof rawNode === 'object' ? { ...(rawNode as Record<string, unknown>) } : {}
    const id = String(node.id || '').trim()
    if (!id || ids.has(id)) throw new Error('节点 id 必须唯一')
    ids.add(id)
    const position = node.position && typeof node.position === 'object' ? node.position as Record<string, unknown> : {}
    return { ...node, id, type: String(node.type || 'text'), position: { x: Number(position.x || 0), y: Number(position.y || 0) }, data: node.data && typeof node.data === 'object' ? node.data as Record<string, unknown> : {} } as CanvasNode
  })
  const normalizedEdges = (Array.isArray(input.edges) ? input.edges : []).map((rawEdge) => {
    const edge = rawEdge && typeof rawEdge === 'object' ? { ...(rawEdge as Record<string, unknown>) } : {}
    const source = String(edge.source || ''), target = String(edge.target || '')
    if (!source || !target || !ids.has(source) || !ids.has(target)) throw new Error('连线引用了不存在的节点')
    return { ...edge, id: String(edge.id || `${source}->${target}`), source, target } as CanvasEdge
  })
  const viewport = input.viewport && typeof input.viewport === 'object' ? input.viewport as Record<string, unknown> : {}
  return { ...input, toonflowCanvas: true, version: 1, nodes: normalizedNodes.map(normalizeImageDraft), edges: normalizedEdges, viewport: { x: Number(viewport.x || 0), y: Number(viewport.y || 0), zoom: Math.max(0.05, Math.min(4, Number(viewport.zoom || 1))) } }
}

export function encodeCanvasDocument(document: CanvasDocument): CanvasDocument { return decodeCanvasDocument(document) }

export function parseNdjson(text: string): Record<string, unknown>[] {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => JSON.parse(line) as Record<string, unknown>)
}
