import type { Edge, Node } from '@xyflow/react'

export type StudioNodeRecord = Node<Record<string, unknown>>

export type StudioClipboard = { nodes: StudioNodeRecord[]; edges: Edge[] }

/** A clipboard owns its snapshot. Copying a frame includes all descendants. */
export function captureStudioSelection(nodes: StudioNodeRecord[], edges: Edge[], ids: Set<string>): StudioClipboard {
  const selected = new Set(ids)
  for (let pass = 0; pass < nodes.length; pass++) {
    const size = selected.size
    nodes.forEach((node) => { if (node.parentId && selected.has(node.parentId)) selected.add(node.id) })
    if (selected.size === size) break
  }
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const copies = nodes.filter((node) => selected.has(node.id)).map((node) => {
    const copy = structuredClone(node)
    // A standalone child must not retain a foreign parent or relative position.
    if (node.parentId && !selected.has(node.parentId)) {
      let parent = byId.get(node.parentId)
      const visited = new Set([node.id])
      while (parent && !visited.has(parent.id)) {
        visited.add(parent.id)
        copy.position.x += parent.position.x; copy.position.y += parent.position.y
        parent = parent.parentId ? byId.get(parent.parentId) : undefined
      }
      delete copy.parentId; delete copy.extent
    }
    return copy
  })
  return { nodes: copies, edges: structuredClone(edges.filter((edge) => selected.has(edge.target))) }
}

/** Paste internal links plus incoming references that still exist in this canvas. */
export function pasteStudioSelection(nodes: StudioNodeRecord[], edges: Edge[], clipboard: StudioClipboard) {
  const result = duplicateStudioNodes(clipboard.nodes, clipboard.edges, new Set(clipboard.nodes.map((node) => node.id)), 48)
  const copiedIds = new Set(result.ids)
  const availableIds = new Set([...nodes.map((node) => node.id), ...result.ids])
  return {
    nodes: [...nodes.map((node) => ({ ...node, selected: false })), ...result.nodes.filter((node) => copiedIds.has(node.id))],
    edges: [...edges.map((edge) => ({ ...edge, selected: false })), ...result.edges.filter((edge) => copiedIds.has(edge.target) && availableIds.has(edge.source)).map((edge) => ({ ...edge, selected: false }))],
    ids: result.ids,
  }
}

export type StudioDragCopy = StudioClipboard & {
  copies: Map<string, string>
  starts: Map<string, { x: number; y: number }>
}

/** Alt-drag copies content; Ctrl/Meta+Alt-drag also copies incoming references. */
export function createStudioDragCopy(nodes: StudioNodeRecord[], edges: Edge[], ids: Set<string>, withEdges: boolean): StudioDragCopy {
  const selected = captureStudioSelection(nodes, edges, ids).nodes.map((node) => node.id)
  const result = duplicateStudioNodes(nodes, withEdges ? edges : [], new Set(selected), 0)
  const copies = new Map(selected.map((id, index) => [id, result.ids[index]]))
  return { nodes: result.nodes, edges: withEdges ? result.edges : edges, copies, starts: new Map(nodes.filter((node) => copies.has(node.id)).map((node) => [node.id, { ...node.position }])) }
}

/** React Flow drags original IDs; restore those positions and forward motion to copies. */
export function moveStudioDragCopy(nodes: StudioNodeRecord[], drag: StudioDragCopy, changes: { id: string; position?: { x: number; y: number } }[]): StudioNodeRecord[] {
  const positions = new Map(changes.filter((change) => change.position && drag.copies.has(change.id)).map((change) => [drag.copies.get(change.id)!, change.position!]))
  return nodes.map((node) => drag.starts.has(node.id) ? { ...node, position: drag.starts.get(node.id)!, dragging: false, selected: false } : positions.has(node.id) ? { ...node, position: positions.get(node.id)!, dragging: true, selected: true } : node)
}

/** Replace selected top-level groups by one frame, preserving world positions. */
export function mergeStudioGroups(nodes: StudioNodeRecord[], edges: Edge[], selectedIds: Set<string>): (StudioClipboard & { id: string }) | undefined {
  const roots = nodes.filter((node) => selectedIds.has(node.id) && !node.parentId)
  if (roots.length < 2 || !roots.some((node) => node.type === 'group')) return
  const descendants = new Set(captureStudioSelection(nodes, edges, new Set(roots.map((node) => node.id))).nodes.map((node) => node.id))
  const groups = new Set(nodes.filter((node) => descendants.has(node.id) && node.type === 'group').map((node) => node.id))
  const flattened = ungroupStudioNodes(nodes, groups)
  const group = createStudioGroup(flattened, descendants)
  if (!group) return
  return { nodes: groupStudioNodes(flattened, group), edges: edges.filter((edge) => !groups.has(edge.source) && !groups.has(edge.target)), id: group.id }
}

/** Returns the media kind used by node previews and the inspector. */
export function nodeMediaKind(node?: Pick<StudioNodeRecord, 'type' | 'data'> | null): 'image' | 'video' | 'audio' | 'text' {
  const explicit = String(node?.data?.mediaType || '').toLowerCase()
  if (explicit === 'image' || explicit === 'video' || explicit === 'audio') return explicit
  const type = String(node?.type || '').toLowerCase()
  if (['imagegeneration', 'scene', 'character', 'prop', 'material'].includes(type)) return 'image'
  if (type === 'videogeneration' || type === 'shot' || type === 'frameanalysis') return 'video'
  if (type === 'audiogeneration' || type === 'voice') return 'audio'
  if (type === 'video' || type === 'audio' || type === 'compose' || type === 'motion' || type === 'storyboard' || type === 'interpolate' || type === 'control_video' || type === 'fill_frames' || type === 'task') return type === 'audio' ? 'audio' : 'video'
  if (type === 'image' || type === 'asset' || type === 'inpaint' || type === 'outpaint' || type === 'upscale') return 'image'
  return 'text'
}

/** Connection validation shared by the pointer connector and keyboard/tool actions. */
export function validateStudioConnection(connection: { source?: string | null; target?: string | null }, nodes: StudioNodeRecord[], edges: Edge[]): string | undefined {
  const source = String(connection.source || '')
  const target = String(connection.target || '')
  if (!source || !target) return '连接缺少节点'
  if (source === target) return '不能连接到节点自身'
  if (!nodes.some((node) => node.id === source) || !nodes.some((node) => node.id === target)) return '连接的节点不存在'
  if (edges.some((edge) => edge.source === source && edge.target === target)) return '这两个节点已经连接'
  const from = nodes.find((node) => node.id === source), to = nodes.find((node) => node.id === target)
  if (from?.type === 'group' || to?.type === 'group') return '分类框不参与生成连线，请连接框内的节点'
  if (to?.type === 'compose' && nodeMediaKind(from)!=='video') return '编排导出节点只接受视频片段'
  if (to?.type === 'compose' && edges.filter(edge=>edge.target===target).length>=8) return '每个编排节点最多连接 8 个视频片段'
  if (nodeMediaKind(to) === 'image' && ['video', 'audio'].includes(nodeMediaKind(from))) return '图片节点只接受图片或文本参考，不能连接音视频'
  if (nodeMediaKind(to) === 'audio' && nodeMediaKind(from) !== 'text') return '配音节点只接受文本参考'
  if (to?.data.editor === 'compose' && nodeMediaKind(from) !== 'video') return '剪辑合成只接受视频片段'
  if (nodeMediaKind(to) === 'video' && to?.data.editor !== 'compose' && nodeMediaKind(from) !== 'text') {
    const mode = to?.data.videoMode
    if (mode === 'text_to_video') return '文生视频不接受媒体连线，请先切换生成方式'
    if (mode === 'image_to_video' || mode === 'first_last_frame') {
      if (nodeMediaKind(from) !== 'image') return '当前生成方式只接受图片'
      const count = edges.filter((edge) => edge.target === target && nodeMediaKind(nodes.find((node) => node.id === edge.source)) !== 'text').length
      if (count >= (mode === 'image_to_video' ? 1 : 2)) return mode === 'image_to_video' ? '图生视频只能连接一张图片' : '首尾帧只能连接两张图片'
    }
  }
  if (from?.type === 'frameAnalysis') return '逐帧拉片节点不提供输出端口'
  if (to?.type === 'frameAnalysis' && nodeMediaKind(from) !== 'video') return '逐帧拉片只能接入视频'
  if (to?.type === 'frameAnalysis' && edges.some((edge) => edge.target === target)) return '逐帧拉片只能接入一个视频，请先移除已有连线'
  return undefined
}

/** Preserve incoming references when duplicating, without connecting copies to old downstream nodes. */
export function duplicateStudioNodes(nodes: StudioNodeRecord[], edges: Edge[], selectedIds: Set<string>, offset = 36): { nodes: StudioNodeRecord[]; edges: Edge[]; ids: string[] } {
  // A selected group includes its descendants even when only its frame is selected.
  selectedIds = new Set(selectedIds)
  for (let pass = 0; pass < nodes.length; pass++) {
    let changed = false
    nodes.forEach((node) => { if (node.parentId && selectedIds.has(node.parentId) && !selectedIds.has(node.id)) { selectedIds.add(node.id); changed = true } })
    if (!changed) break
  }
  const selected = nodes.filter((node) => selectedIds.has(node.id))
  if (!selected.length) return { nodes, edges, ids: [] }
  const idMap = new Map<string, string>()
  const copies = selected.map((node) => {
    const id = `node-${crypto.randomUUID()}`
    idMap.set(node.id, id)
    return {
      ...node,
      id,
      position: { x: node.position.x + offset, y: node.position.y + offset },
      data: structuredClone(node.data || {}),
      selected: true,
    }
  })
  copies.forEach((copy) => {
    const original = nodes.find((node) => idMap.get(node.id) === copy.id)!
    if (original.parentId && idMap.has(original.parentId)) {
      copy.parentId = idMap.get(original.parentId)
      copy.position = { ...original.position }
    }
    if (Array.isArray(copy.data.children)) copy.data.children = copy.data.children.filter((id) => idMap.has(String(id))).map((id) => idMap.get(String(id))!)
  })
  const copiedEdges = edges
    .filter((edge) => idMap.has(edge.target))
    .map((edge) => ({ ...edge, id: `edge-${crypto.randomUUID()}`, source: idMap.get(edge.source) || edge.source, target: idMap.get(edge.target)! }))
  return { nodes: [...nodes.map((node) => ({ ...node, selected: false })), ...copies], edges: [...edges, ...copiedEdges], ids: copies.map((node) => node.id) }
}

/** Drop selected nodes and any edges that touch them. Group membership lists are updated in place. */
export function removeStudioNodes(nodes: StudioNodeRecord[], edges: Edge[], selectedIds: Set<string>): { nodes: StudioNodeRecord[]; edges: Edge[] } {
  selectedIds = new Set(selectedIds)
  for (let pass = 0; pass < nodes.length; pass++) {
    const size = selectedIds.size
    nodes.forEach((node) => { if (node.parentId && selectedIds.has(node.parentId)) selectedIds.add(node.id) })
    if (selectedIds.size === size) break
  }
  return {
    nodes: nodes.filter((node) => !selectedIds.has(node.id)).map((node) => {
      const children = Array.isArray(node.data.children) ? node.data.children.map(String).filter((id) => !selectedIds.has(id)) : node.data.children
      return children === node.data.children ? node : { ...node, data: { ...node.data, children } }
    }),
    edges: edges.filter((edge) => !selectedIds.has(edge.source) && !selectedIds.has(edge.target)),
  }
}

/** Remove group markers without deleting the nodes they contain. */
export function ungroupStudioNodes(nodes: StudioNodeRecord[], selectedIds: Set<string>): StudioNodeRecord[] {
  const removed = new Map(nodes.filter((node) => node.type === 'group' && selectedIds.has(node.id)).map((node) => [node.id, node]))
  return nodes.filter((node) => !removed.has(node.id)).map((node) => {
    if (!node.parentId || !removed.has(node.parentId)) return node
    let position = { ...node.position }
    let parentId: string | undefined = node.parentId
    while (parentId && removed.has(parentId)) {
      const parent: StudioNodeRecord = removed.get(parentId)!
      position = { x: position.x + parent.position.x, y: position.y + parent.position.y }
      parentId = parent.parentId
    }
    return { ...node, position, parentId, extent: parentId ? 'parent' : undefined }
  })
}

/** Rewrite one node's data. Unknown fields on the node stay intact. */
export function updateStudioNode(nodes: StudioNodeRecord[], id: string, changes: Record<string, unknown>): StudioNodeRecord[] {
  return nodes.map((node) => node.id === id ? { ...node, data: { ...node.data, ...changes } } : node)
}

/** 按连线从左到右整理整张画布：上游在左，下游在右，同层纵向排开。 */
export function tidyStudioNodes(nodes: StudioNodeRecord[], edges: Edge[]): StudioNodeRecord[] {
  const movable = nodes.filter((node) => !node.parentId)
  if (movable.length < 2) return nodes
  const ids = new Set(movable.map((node) => node.id))
  const depth = new Map<string, number>()
  const visiting = new Set<string>()
  const layer = (id: string): number => {
    const known = depth.get(id)
    if (known !== undefined) return known
    if (visiting.has(id)) return 0
    visiting.add(id)
    const parents = edges.filter((edge) => edge.target === id && ids.has(edge.source) && edge.source !== id).map((edge) => layer(edge.source))
    const value = parents.length ? Math.max(...parents) + 1 : 0
    depth.set(id, value)
    visiting.delete(id)
    return value
  }
  movable.forEach((node) => layer(node.id))
  const columns = new Map<number, string[]>()
  ;[...movable].sort((left, right) => left.position.y - right.position.y || left.position.x - right.position.x).forEach((node) => {
    const column = depth.get(node.id) || 0
    columns.set(column, [...(columns.get(column) || []), node.id])
  })
  const positions = new Map<string, { x: number; y: number }>()
  ;[...columns.keys()].sort((left, right) => left - right).forEach((column, columnIndex) => {
    columns.get(column)?.forEach((id, row) => positions.set(id, { x: 80 + columnIndex * 380, y: 80 + row * 280 }))
  })
  return nodes.map((node) => positions.has(node.id) ? { ...node, position: positions.get(node.id)! } : node)
}

/** Place a multi-selection in a row, a column, or a square grid from its current top-left. */
export function arrangeStudioNodes(nodes: StudioNodeRecord[], selectedIds: Set<string>, mode: 'horizontal' | 'vertical' | 'grid'): StudioNodeRecord[] {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const selected = nodes.filter((node) => {
    if (!selectedIds.has(node.id)) return false
    let parentId = node.parentId
    const seen = new Set<string>()
    while (parentId && !seen.has(parentId)) {
      if (selectedIds.has(parentId)) return false
      seen.add(parentId); parentId = byId.get(parentId)?.parentId
    }
    return true
  }).sort((left, right) => left.position.y - right.position.y || left.position.x - right.position.x)
  // Different parent groups have independent coordinate systems and constraints.
  const siblings = new Map<string, StudioNodeRecord[]>()
  selected.forEach((node) => siblings.set(node.parentId || '', [...(siblings.get(node.parentId || '') || []), node]))
  const positions = new Map<string, { x: number; y: number }>()
  const size = (node: StudioNodeRecord, axis: 'width' | 'height') => node.measured?.[axis] || node[axis] || Number(node.style?.[axis]) || (axis === 'width' ? 280 : 200)
  for (const items of siblings.values()) {
    if (items.length < 2) continue
    const originX = Math.min(...items.map((node) => node.position.x)), originY = Math.min(...items.map((node) => node.position.y))
    const columns = mode === 'horizontal' ? items.length : mode === 'vertical' ? 1 : Math.ceil(Math.sqrt(items.length))
    const widths = Array.from({ length: columns }, (_, column) => Math.max(...items.filter((_, index) => index % columns === column).map((node) => size(node, 'width'))))
    const heights = Array.from({ length: Math.ceil(items.length / columns) }, (_, row) => Math.max(...items.slice(row * columns, (row + 1) * columns).map((node) => size(node, 'height'))))
    items.forEach((node, index) => positions.set(node.id, {
      x: originX + widths.slice(0, index % columns).reduce((sum, width) => sum + width + 32, 0),
      y: originY + heights.slice(0, Math.floor(index / columns)).reduce((sum, height) => sum + height + 32, 0),
    }))
  }
  const arranged = nodes.map((node) => positions.has(node.id) ? { ...node, position: positions.get(node.id)! } : node)
  return arranged.map((node) => {
    if (node.type !== 'group' || !siblings.has(node.id) || !siblings.get(node.id)?.some((child) => positions.has(child.id))) return node
    const children = arranged.filter((child) => child.parentId === node.id)
    const width = Math.max(size(node, 'width'), ...children.map((child) => child.position.x + size(child, 'width') + 28))
    const height = Math.max(size(node, 'height'), ...children.map((child) => child.position.y + size(child, 'height') + 28))
    return { ...node, width, height, style: { ...node.style, width, height } }
  })
}

/** Build a persistent group marker for a multi-selection. Child nodes remain editable. */
export function createStudioGroup(nodes: StudioNodeRecord[], selectedIds: Set<string>, label = '新分组'): StudioNodeRecord | undefined {
  const selected = nodes.filter((node) => selectedIds.has(node.id) && !node.parentId)
  if (selected.length < 2) return undefined
  const left = Math.min(...selected.map((node) => node.position.x)) - 28
  const top = Math.min(...selected.map((node) => node.position.y)) - 56
  return {
    id: `group-${crypto.randomUUID()}`,
    type: 'group',
    position: { x: left, y: top },
    style: {
      width: Math.max(...selected.map((node) => node.position.x + (node.measured?.width || Number(node.style?.width) || 280))) - left + 28,
      height: Math.max(...selected.map((node) => node.position.y + (node.measured?.height || Number(node.style?.height) || 200))) - top + 28,
    },
    data: { label, children: selected.map((node) => node.id), text: `${selected.length} 个节点` },
    selected: true,
  }
}

export function groupStudioNodes(nodes: StudioNodeRecord[], group: StudioNodeRecord): StudioNodeRecord[] {
  const members = new Set(Array.isArray(group.data.children) ? group.data.children.map(String) : [])
  return [group, ...nodes.map((node) => members.has(node.id) ? {
    ...node, parentId: group.id, extent: 'parent' as const, selected: false,
    position: { x: node.position.x - group.position.x, y: node.position.y - group.position.y },
  } : { ...node, selected: false })]
}
