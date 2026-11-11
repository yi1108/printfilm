import { nodeMediaKind } from './nodeOperations.ts'

export function nodeDraft(node: { type?: string; data: Record<string, unknown> }) {
  const data = node.data
  if (nodeMediaKind(node) === 'text') return String(data.text || data.prompt || data.hint || '')
  return typeof data.prompt === 'string' ? data.prompt : String(data.text || data.hint || '')
}

export function normalizeImageDraft<T extends { type?: string; data: Record<string, unknown>; height?: unknown; style?: unknown; measured?: unknown }>(node: T): T {
  const data = node.data
  if (nodeMediaKind(node) !== 'image' || data.userResized || data.mediaUrl || data.url || data.cover || Array.isArray(data.mediaUrls) && data.mediaUrls.length) return node
  return { ...node, height: 280, style: { ...(node.style as object || {}), height: 280 }, measured: undefined }
}
