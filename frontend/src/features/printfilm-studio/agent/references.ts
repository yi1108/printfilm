import { nodeMediaKind } from '../canvas/nodeOperations'
import { clampMediaIndex, collectMediaUrls } from '../canvas/imageVariants'
import type { ProjectAsset } from '../types'

export type AgentReference = {
  key: string; label: string; kind: 'image' | 'video' | 'audio' | 'text'
  nodeId?: string; assetId?: number; thumbnail: string; mediaUrl: string; text: string
}
type ReferenceNode = { id: string; type?: string; data: Record<string, unknown> }
const value = (...items: unknown[]) => items.find((item): item is string => typeof item === 'string' && !!item.trim()) || ''

export function assetReference(asset: ProjectAsset): AgentReference {
  const type = String(asset.asset_type || asset.type || '').toLowerCase()
  const kind = type === 'video' ? 'video' : ['audio', 'voice'].includes(type) ? 'audio' : 'image'
  return { key: `asset-${asset.id}`, assetId: asset.id, label: asset.name || `素材 ${asset.id}`, kind,
    thumbnail: value(asset.cover, kind === 'image' ? asset.url : ''), mediaUrl: value(asset.url), text: '' }
}

export function nodeReference(node: ReferenceNode, assets: ProjectAsset[] = []): AgentReference {
  const data = node.data
  const asset = assets.find((item) => item.id === Number(data.assetId || data.asset_id))
  const kind = nodeMediaKind(node)
  const variants = collectMediaUrls(data)
  const mediaUrl = value(variants[clampMediaIndex(data.mediaIndex, variants.length)], asset?.url)
  return { key: `node-${node.id}`, nodeId: node.id, label: value(data.label, data.name) || '未命名节点', kind,
    thumbnail: kind === 'image' ? value(mediaUrl, data.cover, asset?.cover) : value(data.cover, data.thumbnail, data.thumbnailUrl, data.poster, asset?.cover),
    mediaUrl, text: value(data.text, data.prompt).slice(0, 180) }
}
