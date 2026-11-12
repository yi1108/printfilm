import type { Edge } from '@xyflow/react'
import { nodeMediaKind, type StudioNodeRecord } from './nodeOperations.ts'
import { episodeOf, layoutStoryPairs, sectionKind, storySection } from './storyOrganization.ts'
export { storySection } from './storyOrganization.ts'

type Point = { x: number; y: number }
export type OrganizeSection = { id: string; label: string; count: number }
export type CanvasOrganization = { nodes: StudioNodeRecord[]; order: string[]; sections: OrganizeSection[] }

export function nodeWorldPositions(nodes: StudioNodeRecord[]): Map<string, Point> {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  return new Map(nodes.map((node) => {
    const position = { ...node.position }, seen = new Set([node.id])
    let parent = node.parentId ? byId.get(node.parentId) : undefined
    while (parent && !seen.has(parent.id)) {
      seen.add(parent.id); position.x += parent.position.x; position.y += parent.position.y
      parent = parent.parentId ? byId.get(parent.parentId) : undefined
    }
    return [node.id, position]
  }))
}

export function organizationNodeSize(node: StudioNodeRecord) {
  const dimension = (axis: 'width' | 'height') => {
    const value = node.type === 'group' ? node[axis] || Number(node.style?.[axis]) : node.measured?.[axis] || node[axis] || Number(node.style?.[axis])
    return Number.isFinite(value) && Number(value) > 0 ? Number(value) : axis === 'width' ? 320 : 220
  }
  return { width: dimension('width'), height: dimension('height') }
}

/** Collapse links to siblings, retaining relationships across nested user groups. */
function siblingEdges(ids: string[], byId: Map<string, StudioNodeRecord>, edges: Edge[]) {
  const siblings = new Set(ids)
  const owner = (id: string) => {
    const seen = new Set<string>()
    while (!siblings.has(id) && !seen.has(id)) {
      seen.add(id)
      const parent = byId.get(id)?.parentId
      if (!parent) return undefined
      id = parent
    }
    return siblings.has(id) ? id : undefined
  }
  return edges.flatMap((edge) => {
    const source = owner(edge.source), target = owner(edge.target)
    return source && target && source !== target ? [{ source, target }] : []
  })
}

/** Size-aware layers. Cycles stay together rather than recursing forever. */
function layoutItems(ids: string[], byId: Map<string, StudioNodeRecord>, edges: Edge[]) {
  const links = siblingEdges(ids, byId, edges), depth = new Map(ids.map((id) => [id, 0]))
  const incoming = new Map(ids.map((id) => [id, links.filter((edge) => edge.target === id).length]))
  const queue = ids.filter((id) => incoming.get(id) === 0)
  for (let index = 0; index < queue.length; index++) {
    const id = queue[index]
    for (const edge of links.filter((link) => link.source === id)) {
      depth.set(edge.target, Math.max(depth.get(edge.target)!, depth.get(id)! + 1))
      incoming.set(edge.target, incoming.get(edge.target)! - 1)
      if (incoming.get(edge.target) === 0) queue.push(edge.target)
    }
  }
  // Unresolved strongly connected regions share one final layer; their links remain intact.
  const remaining = ids.filter((id) => !queue.includes(id))
  const cycleLayer = Math.max(0, ...remaining.map((id) => depth.get(id)!))
  remaining.forEach((id) => depth.set(id, cycleLayer))
  const positions = new Map<string, Point>(), order: string[] = []
  let x = 40, totalHeight = 0
  for (const layer of [...new Set(depth.values())].sort((a, b) => a - b)) {
    const items = ids.filter((id) => depth.get(id) === layer)
    const columns = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(items.length))))
    const sizes = items.map((id) => organizationNodeSize(byId.get(id)!))
    const widths = Array.from({ length: columns }, (_, col) => Math.max(...sizes.filter((_, index) => index % columns === col).map((size) => size.width)))
    const heights = Array.from({ length: Math.ceil(items.length / columns) }, (_, row) => Math.max(...sizes.slice(row * columns, (row + 1) * columns).map((size) => size.height)))
    items.forEach((id, index) => {
      positions.set(id, { x: x + widths.slice(0, index % columns).reduce((sum, width) => sum + width + 64, 0), y: 80 + heights.slice(0, Math.floor(index / columns)).reduce((sum, height) => sum + height + 76, 0) })
      order.push(id)
    })
    x += widths.reduce((sum, width) => sum + width + 64, 0) + 56
    totalHeight = Math.max(totalHeight, heights.reduce((sum, height) => sum + height + 76, 0))
  }
  return { positions, order, width: Math.max(360, x - 80), height: Math.max(240, totalHeight + 52) }
}

const category = (node: StudioNodeRecord) => node.type === 'director3d' ? '导演台' : node.type === 'frameAnalysis' ? '拉片分析' : ({ text: '文本与脚本', image: '图片创作', video: '视频创作', audio: '配音与音轨' }[nodeMediaKind(node)])
function groupKey(ids: string[]) {
  let hash = 2166136261
  for (const char of [...ids].sort().join('|')) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619)
  return `organized-${(hash >>> 0).toString(36)}`
}

/** Reversible organization: preserve all content, ports, user groups and edge IDs. */
export function organizeCanvas(nodes: StudioNodeRecord[], edges: Edge[]): CanvasOrganization {
  if (!nodes.length) return { nodes, order: [], sections: [] }
  const world = nodeWorldPositions(nodes)
  const originalById = new Map(nodes.map((node) => [node.id, node]))
  const episodes = new Map(nodes.map((node) => [node.id, episodeOf(node, originalById)]))
  const previousFrames = new Map(nodes.filter((node) => node.type === 'group' && (node.data.autoLayoutGroup === true || !!node.data.sourceScriptId && ['character_group', 'scene_group', 'shot_video_group'].includes(String(node.data.storyKind)))).map((node) => [node.id, node]))
  const working = nodes.filter((node) => !previousFrames.has(node.id)).map((node) => {
    if (!node.parentId || !previousFrames.has(node.parentId)) return { ...node, position: { ...node.position }, selected: false }
    return { ...node, position: world.get(node.id)!, parentId: undefined, extent: undefined, selected: false }
  })
  const byId = new Map(working.map((node) => [node.id, node]))
  const children = (id: string) => working.filter((node) => node.parentId === id).map((node) => node.id).sort()
  const visited = new Set<string>()
  const arrangeGroup = (id: string) => {
    const group = byId.get(id)!
    if (visited.has(id) || group.type !== 'group') return
    visited.add(id)
    const ids = children(id)
    ids.forEach(arrangeGroup)
    if (!ids.length) return
    const layout = layoutItems(ids, byId, edges)
    ids.forEach((child) => { byId.get(child)!.position = layout.positions.get(child)! })
    Object.assign(group, { width: layout.width, height: layout.height, style: { ...group.style, width: layout.width, height: layout.height } })
  }
  working.filter((node) => node.type === 'group').forEach((node) => arrangeGroup(node.id))
  const roots = working.filter((node) => !node.parentId || !byId.has(node.parentId)).map((node) => node.id).sort()
  const links = siblingEdges(roots, byId, edges), unseen = new Set(roots)
  const blocks: { ids: string[]; label: string; story?: boolean; owner?: string; episodeKey?: string; episodeLabel?: string; episodeNumber?: number; section?: string; sceneId?: string; sceneNumber?: number; frame?: StudioNodeRecord }[] = []
  const sceneNumbers = new Map<string, Map<string, number>>()
  const validNumber = (value: unknown) => Number.isInteger(Number(value)) && Number(value) > 0 ? Number(value) : undefined
  for (const node of [...working].sort((a, b) => Number(a.data.shotIndex || 0) - Number(b.data.shotIndex || 0))) {
    if (storySection(node) !== '分镜') continue
    const key = JSON.stringify([node.data.sourceScriptId || '', episodes.get(node.id)?.key || ''])
    if (!sceneNumbers.has(key)) sceneNumbers.set(key, new Map())
    const scene = String(node.data.sceneNodeId || ''), number = validNumber(node.data.sceneNumber)
    if (scene && number && !sceneNumbers.get(key)!.has(scene)) sceneNumbers.get(key)!.set(scene, number)
  }
  // Story categories and episodes define columns, never cross-reference edges.
  const buckets = new Map<string, typeof blocks[number]>()
  for (const id of [...roots].sort((a, b) => Number(byId.get(a)!.data.shotIndex || 0) - Number(byId.get(b)!.data.shotIndex || 0) || a.localeCompare(b))) {
    const node = byId.get(id)!, episode = episodes.get(id)!
    const section = storySection(node) || (node.type !== 'group' && (node.data.sourceScriptId || episode.key) ? category(node) : undefined)
    if (!section) continue
    const owner = String(node.data.sourceScriptId || (node.type === 'script' ? node.id : ''))
    const sceneId = section === '分镜' ? String(node.data.sceneNodeId || (node.data.referenceNodeIds as string[] | undefined)?.find(ref => originalById.get(ref)?.data.storyKind === 'scene') || '') : ''
    const sceneLabel = sceneId ? String(originalById.get(sceneId)?.data.label || '场景') : ''
    const scope = JSON.stringify([owner, episode.key])
    const numbers = sceneNumbers.get(scope) || new Map<string, number>()
    let sceneNumber = section === '分镜' ? validNumber(node.data.sceneNumber) : undefined
    if (sceneId && !sceneNumber) sceneNumber = numbers.get(sceneId) || Math.max(0, ...numbers.values()) + 1
    if (sceneId && sceneNumber) { if (!numbers.has(sceneId)) numbers.set(sceneId, sceneNumber); sceneNumbers.set(scope, numbers) }
    if (sceneId || sceneNumber) node.data = { ...node.data, ...(sceneId ? { sceneNodeId: sceneId } : {}), ...(sceneNumber ? { sceneNumber } : {}) }
    const key = JSON.stringify([owner, episode.key, section, sceneId, sceneNumber])
    const script = byId.get(owner), title = String(script?.data.label || '').trim()
    if (!buckets.has(key)) buckets.set(key, { ids: [], label: [episode.label, sceneNumber ? `场${sceneNumber}` : '', sceneLabel || section, title && (!episode.label || !title.includes(episode.label)) ? title : ''].filter(Boolean).join(' · '), story: true, owner, episodeKey: episode.key, episodeLabel: episode.label, episodeNumber: episode.number, section, sceneId, sceneNumber })
    buckets.get(key)!.ids.push(id); unseen.delete(id)
  }
  const sectionOrder = (label: string) => { const index = ['剧本', '人物', '场景', '分镜'].indexOf(label); return index < 0 ? 10 : index }
  blocks.push(...[...buckets.values()].sort((a, b) => (a.episodeNumber || 0) - (b.episodeNumber || 0) || String(a.episodeKey).localeCompare(String(b.episodeKey), undefined, { numeric: true }) || String(a.owner).localeCompare(String(b.owner)) || sectionOrder(a.section!) - sectionOrder(b.section!) || a.section!.localeCompare(b.section!) || (a.sceneNumber || 0) - (b.sceneNumber || 0)))
  const loose = new Map<string, string[]>()
  for (const start of roots) {
    if (!unseen.delete(start)) continue
    const ids = [start]
    for (let index = 0; index < ids.length; index++) {
      const id = ids[index]
      links.forEach((edge) => {
        const peer = edge.source === id ? edge.target : edge.target === id ? edge.source : undefined
        if (peer && unseen.delete(peer)) ids.push(peer)
      })
    }
    if (ids.length > 1) blocks.push({ ids, label: `关联流程 ${blocks.length + 1}` })
    else if (byId.get(start)!.type === 'group') blocks.push({ ids, label: String(byId.get(start)!.data.label || '已有分组'), frame: byId.get(start) })
    else { const key = category(byId.get(start)!); loose.set(key, [...(loose.get(key) || []), start]) }
  }
  loose.forEach((ids, label) => blocks.push({ ids, label }))
  const sections: OrganizeSection[] = [], order: string[] = [], frames: StudioNodeRecord[] = []
  const visitLeaves = (id: string) => {
    const node = byId.get(id)!
    if (node.type !== 'group') { order.push(id); return }
    children(id).sort((a, b) => byId.get(a)!.position.x - byId.get(b)!.position.x || byId.get(a)!.position.y - byId.get(b)!.position.y).forEach(visitLeaves)
  }
  for (const block of blocks) {
    if (block.sceneId || block.sceneNumber) {
      const videos = block.ids.map(id => byId.get(id)!).filter(node => node.data.storyKind === 'shot_video').sort((a, b) => Number(a.data.shotIndex || 0) - Number(b.data.shotIndex || 0) || a.id.localeCompare(b.id))
      videos.forEach((node, index) => {
        const label = `${block.sceneNumber ? `场${block.sceneNumber} · ` : ''}镜头${index + 1}`
        node.data = { ...node.data, label: `${label} · 视频`, sceneShotIndex: index + 1 }
        const writer = byId.get(String(node.data.promptNodeId))
        if (writer && block.ids.includes(writer.id)) writer.data = { ...writer.data, label: `${label} · 写作`, sceneShotIndex: index + 1 }
      })
    }
    const start = order.length
    if (!block.frame) {
      const layout = block.story ? layoutStoryPairs(block.ids, byId, edges, organizationNodeSize) : layoutItems(block.ids, byId, edges)
      const reusable = block.story ? [...previousFrames.values()].find((frame) => !frames.some(used => used.id === frame.id) && frame.data.sourceScriptId === block.owner && (sectionKind[block.section!] ? frame.data.storyKind === sectionKind[block.section!] : frame.data.storySection === block.section) && (episodes.get(frame.id)?.key || '') === block.episodeKey && String(frame.data.sceneNodeId || '') === (block.sceneId || '') && (!block.sceneNumber || !frame.data.sceneNumber || frame.data.sceneNumber === block.sceneNumber)) : undefined
      let id = reusable?.id || groupKey(block.ids)
      while (byId.has(id)) id += '-frame'
      const previous = previousFrames.get(id)
      block.frame = { ...previous, id, type: 'group', position: { x: 0, y: 0 }, width: layout.width, height: layout.height, style: { ...previous?.style, width: layout.width, height: layout.height }, data: { ...previous?.data, label: block.story ? block.label : previous?.data.label || block.label, autoLayoutGroup: true, ...(block.story ? { storySection: block.section, sceneNodeId: block.sceneId || undefined, sceneNumber: block.sceneNumber, sourceScriptId: block.owner, storyKind: sectionKind[block.section!], ...(block.episodeNumber ? { episodeNumber: block.episodeNumber } : {}), episodeKey: block.episodeKey, episodeLabel: block.episodeLabel } : {}), children: block.ids }, selected: false }
      frames.push(block.frame)
      block.ids.forEach((child) => { const node = byId.get(child)!; node.parentId = id; node.extent = 'parent'; node.position = layout.positions.get(child)! })
      layout.order.forEach(visitLeaves)
    } else visitLeaves(block.frame.id)
    sections.push({ id: block.frame.id, label: String(block.frame.data.label || block.label), count: order.length - start })
  }
  // Each episode/story is one horizontal band. Categories are side by side;
  // subsequent episodes start below the tallest category in the previous band.
  let x = 80, y = 100, rowHeight = 0, band = ''
  blocks.forEach((block) => {
    const nextBand = block.story ? `${block.episodeKey}|${block.owner}` : 'other'
    if (band && nextBand !== band) { x = 80; y += rowHeight + 160; rowHeight = 0 }
    band = nextBand
    const size = organizationNodeSize(block.frame!)
    if (!block.story && x > 80 && x + size.width > 2800) { x = 80; y += rowHeight + 160; rowHeight = 0 }
    block.frame!.position = { x, y }; x += size.width + 160; rowHeight = Math.max(rowHeight, size.height)
  })
  // React Flow requires parents before descendants, including nested user groups.
  const combined = [...frames, ...working], all = new Map(combined.map((node) => [node.id, node]))
  const rank = (node: StudioNodeRecord) => { let depth = 0, parent = node.parentId; const seen = new Set([node.id]); while (parent && all.has(parent) && !seen.has(parent)) { seen.add(parent); depth++; parent = all.get(parent)!.parentId } return depth }
  return { nodes: combined.sort((a, b) => rank(a) - rank(b) || a.id.localeCompare(b.id)), order, sections }
}
