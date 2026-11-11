import type { CanvasDocument, CanvasNode } from './canvasCodec'
export type Recipe = { id: string; name: string; document: CanvasDocument }

export function captureRecipe(document: CanvasDocument, selected: string[]): CanvasDocument {
  const ids = new Set(selected.length ? selected : document.nodes.map((node) => node.id))
  for (let pass = 0; pass < document.nodes.length; pass++) {
    const before = ids.size
    document.nodes.forEach((node) => { if (ids.has(String(node.parentId))) ids.add(node.id) })
    if (before === ids.size) break
  }
  const nodes = structuredClone(document.nodes.filter((node) => ids.has(node.id)))
  if (!nodes.length) throw new Error('请先添加或选择节点')
  for (const node of nodes) {
    if (node.parentId && !ids.has(String(node.parentId))) {
      let parent = document.nodes.find((entry) => entry.id === node.parentId)
      const visited = new Set<string>()
      while (parent && !visited.has(parent.id)) {
        visited.add(parent.id)
        node.position.x += parent.position.x; node.position.y += parent.position.y
        parent = document.nodes.find((entry) => entry.id === parent?.parentId)
      }
      delete node.parentId; delete node.extent
    }
  }
  const roots = nodes.filter((node) => !node.parentId)
  const x = Math.min(...roots.map((node) => node.position.x)), y = Math.min(...roots.map((node) => node.position.y))
  roots.forEach((node) => { node.position = { x: node.position.x - x, y: node.position.y - y } })
  return { toonflowCanvas: true, version: 1, nodes, edges: structuredClone(document.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target))), viewport: { x: 0, y: 0, zoom: 1 } }
}

export function instantiateRecipe(document: CanvasDocument, at: { x: number; y: number }) {
  const ids = new Map(document.nodes.map((node) => [node.id, `node-${crypto.randomUUID()}`]))
  const nodes = structuredClone(document.nodes).map((node): CanvasNode => {
    const parentId = ids.get(String(node.parentId))
    const data = { ...node.data }
    if (Array.isArray(data.children)) data.children = data.children.map((id) => ids.get(String(id))).filter(Boolean)
    return { ...node, id: ids.get(node.id)!, parentId, extent: parentId ? 'parent' : undefined, position: parentId ? node.position : { x: node.position.x + at.x, y: node.position.y + at.y }, data, selected: true }
  })
  // React Flow requires parents before children.
  const ordered: CanvasNode[] = []
  const added = new Set<string>()
  while (ordered.length < nodes.length) {
    const next = nodes.filter((node) => !added.has(node.id) && (!node.parentId || added.has(String(node.parentId))))
    if (!next.length) throw new Error('配方分组结构无效')
    next.forEach((node) => { ordered.push(node); added.add(node.id) })
  }
  return { nodes: ordered, edges: document.edges.map((edge) => ({ ...edge, id: `edge-${crypto.randomUUID()}`, source: ids.get(edge.source)!, target: ids.get(edge.target)! })) }
}
