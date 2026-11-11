import type { Node } from '@xyflow/react'
import { nodeMediaKind } from '../canvas/nodeOperations'
import { clampMediaIndex, collectMediaUrls } from '../canvas/imageVariants'

export type StoryNode = Node<Record<string, unknown>>
export type StoryKind = 'audio' | 'text' | 'image' | 'video'
export const storyKinds: StoryKind[] = ['audio', 'text', 'image', 'video']
export const storyLabels = { audio: '音频', text: '文本', image: '图片', video: '视频' }
export const storyTitle = (node: StoryNode) => String(node.data.label || node.data.name || storyLabels[nodeMediaKind(node)] || '素材')
export function storyMedia(node: StoryNode) {
  const urls = collectMediaUrls(node.data)
  return urls[clampMediaIndex(node.data.mediaIndex, urls.length)] || ''
}
export function storyStatus(node: StoryNode, submitting = false) {
  if (submitting) return '提交中…'
  const status = String(node.data.status || '')
  if (['queued', 'pending'].includes(status)) return '排队中…'
  if (['running', 'processing', 'awaiting_poll', 'awaiting_composite'].includes(status)) return '生成中…'
  if (status === 'failed') return '生成失败'
  if (status === 'cancelled') return '已取消'
  return storyMedia(node) ? '就绪' : nodeMediaKind(node) === 'text' ? '文本' : '待生成'
}
export function storySequence(nodes: StoryNode[]) {
  return nodes.filter(node => ['image','video'].includes(nodeMediaKind(node)) && typeof node.data.storyboardOrder === 'number' && node.data.storyboardOrder >= 0)
    .sort((a,b) => Number(a.data.storyboardOrder) - Number(b.data.storyboardOrder))
}
/** Ordering lives on nodes so save, undo, copy and canvas reload share one state. */
export function setStorySequence(nodes: StoryNode[], ids: string[]) {
  const available = new Set(nodes.filter(node => ['image','video'].includes(nodeMediaKind(node))).map(node => node.id))
  const ordered = [...new Set(ids)].filter(id => available.has(id))
  return nodes.map(node => ordered.includes(node.id) || node.data.storyboardOrder != null
    ? { ...node, data: { ...node.data, storyboardOrder: ordered.includes(node.id) ? ordered.indexOf(node.id) : null } } : node)
}
export function storyDuration(node: StoryNode) {
  const seconds = Number(node.data.storyboardDuration || node.data.duration || node.data.mediaDuration || (nodeMediaKind(node) === 'image' ? 3 : 0))
  return Number.isFinite(seconds) && seconds > 0 ? seconds : 0
}
