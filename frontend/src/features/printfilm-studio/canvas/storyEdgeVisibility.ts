import type { Edge } from '@xyflow/react'

type StoryNode = { id: string; data: Record<string, unknown> }

/** Display filtering only: all reference edges stay in the persisted graph. */
export function visibleStoryEdges(nodes: StoryNode[], edges: Edge[], selectedIds: string[], focused: boolean): Edge[] {
  if (!focused) return edges
  const videos = new Set(nodes.filter(node => node.data.storyKind === 'shot_video').map(node => node.id))
  const writers = new Set(nodes.filter(node => node.data.storyKind === 'shot_prompt').map(node => node.id))
  const selected = new Set(selectedIds)
  const activeShots = new Set(selectedIds)
  const pairs = new Set<string>()
  for (const edge of edges) {
    if (!videos.has(edge.target) || !writers.has(edge.source)) continue
    pairs.add(edge.id)
    if (selected.has(edge.source) || selected.has(edge.target)) {
      activeShots.add(edge.source)
      activeShots.add(edge.target)
    }
  }
  return edges.filter(edge => edge.selected || pairs.has(edge.id)
    || (!videos.has(edge.target) && !writers.has(edge.target))
    || selected.has(edge.source) || activeShots.has(edge.target))
}
