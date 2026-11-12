import { decodeCanvasDocument, type CanvasDocument } from './canvasCodec.ts'

export class CanvasMergeConflict extends Error {
  constructor(path: string) {
    super(`同一内容被同时修改（${path}），已保留本地修改，请导出后核对服务端画布`)
    this.name = 'CanvasMergeConflict'
  }
}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
export function canvasValuesEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((value, i) => canvasValuesEqual(value, b[i]))
  if (!object(a) || !object(b)) return false
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  return [...keys].every(key => canvasValuesEqual(a[key], b[key]))
}

export function persistedCanvas(raw: unknown): CanvasDocument {
  const doc = decodeCanvasDocument(raw)
  return { ...doc,
    nodes: doc.nodes.map(node => Object.fromEntries(Object.entries(node).filter(([key]) => !['selected', 'measured', 'dragging', 'resizing'].includes(key))) as typeof node),
    edges: doc.edges.map(edge => Object.fromEntries(Object.entries(edge).filter(([key]) => key !== 'selected')) as typeof edge),
  }
}

function mergeValue(base: unknown, local: unknown, remote: unknown, path: string): unknown {
  if (canvasValuesEqual(local, base)) return remote
  if (canvasValuesEqual(remote, base) || canvasValuesEqual(local, remote)) return local
  if (object(base) && object(local) && object(remote)) {
    let localObject = local, remoteObject = remote
    // The task poller and workflow can observe the same task at different times.
    // Advancing that task is not a competing user edit; never regress its state.
    if (path.endsWith('.data') && local.taskId && local.taskId === remote.taskId) {
      const rank = (status: unknown) => ({ queued: 0, running: 1, completed: 2, succeeded: 2, failed: 2, cancelled: 2 }[String(status)])
      const localRank = rank(local.status), remoteRank = rank(remote.status)
      if (localRank !== undefined && remoteRank !== undefined && localRank !== remoteRank) {
        const advanced = localRank > remoteRank ? local : remote
        const progress = Object.fromEntries(['status', 'canCancel', 'generationStage', 'error'].map(key => [key, advanced[key]]))
        localObject = { ...local, ...progress }; remoteObject = { ...remote, ...progress }
      }
    }
    const merged: Record<string, unknown> = {}
    for (const key of new Set([...Object.keys(base), ...Object.keys(localObject), ...Object.keys(remoteObject)])) {
      const value = mergeValue(base[key], localObject[key], remoteObject[key], `${path}.${key}`)
      if (value !== undefined) merged[key] = value
    }
    return merged
  }
  throw new CanvasMergeConflict(path)
}

function mergeItems<T extends { id: string }>(base: T[], local: T[], remote: T[], path: string): T[] {
  const maps = [base, local, remote].map(items => new Map(items.map(item => [item.id, item])))
  const result: T[] = []
  for (const id of new Set([...remote.map(item => item.id), ...local.map(item => item.id)])) {
    const value = mergeValue(maps[0].get(id), maps[1].get(id), maps[2].get(id), `${path}.${id}`)
    if (value !== undefined) result.push(value as T)
  }
  return result
}

/** Merge against the document that supplied expected_version, never blindly overwrite a newer canvas. */
export function mergeCanvasDocuments(baseRaw: unknown, localRaw: unknown, remoteRaw: unknown): CanvasDocument {
  const base = persistedCanvas(baseRaw), local = persistedCanvas(localRaw), remote = persistedCanvas(remoteRaw)
  const extras = (doc: CanvasDocument) => { const { nodes, edges, viewport, ...rest } = doc; return rest }
  const nodes = mergeItems(base.nodes, local.nodes, remote.nodes, 'nodes')
  const edges = mergeItems(base.edges, local.edges, remote.edges, 'edges')
  const ids = new Set(nodes.map(node => node.id))
  if (nodes.some(node => node.parentId && !ids.has(String(node.parentId))) || edges.some(edge => !ids.has(edge.source) || !ids.has(edge.target))) throw new CanvasMergeConflict('节点与连线')
  // Keep parents ahead of children, including independently added groups.
  const ordered: typeof nodes = [], visited = new Set<string>(), visiting = new Set<string>()
  const byId = new Map(nodes.map(node => [node.id, node]))
  const visit = (node: typeof nodes[number]) => {
    if (visited.has(node.id)) return
    if (visiting.has(node.id)) throw new CanvasMergeConflict('分组关系')
    visiting.add(node.id)
    if (node.parentId) visit(byId.get(String(node.parentId))!)
    visiting.delete(node.id); visited.add(node.id); ordered.push(node)
  }
  nodes.forEach(visit)
  return decodeCanvasDocument({ ...(mergeValue(extras(base), extras(local), extras(remote), 'canvas') as object), nodes: ordered, edges, viewport: local.viewport })
}
