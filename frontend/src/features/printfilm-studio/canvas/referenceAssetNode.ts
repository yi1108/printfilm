/** 素材库引用优先复用画布节点；同名素材不能当作同一张图片。 */
export function referenceAssetNode<T extends { id: string; data: { assetId?: unknown; mediaUrl?: unknown; url?: unknown; cover?: unknown } }>(
  nodes: T[], asset: { id: number; url?: string | null; cover?: string | null }, targetId: string,
  edges: { source: string; target: string }[],
): T | undefined {
  const url = asset.url || asset.cover || ''
  const matches = nodes.filter((node) => node.id !== targetId && (
    Number(node.data.assetId) === asset.id || !!url && String(node.data.mediaUrl || node.data.url || node.data.cover || '') === url
  ))
  return matches.find((node) => edges.some((edge) => edge.source === node.id && edge.target === targetId)) || matches[0]
}
