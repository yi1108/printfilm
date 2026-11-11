import { writingContext, writingParametersChanged } from '../canvas/writingContext.ts'
import { collectMediaUrls } from '../canvas/imageVariants.ts'
import { nodeMediaKind } from '../canvas/nodeOperations.ts'
import { batchInputs, type BatchInput, type BatchSettings } from './batchGeneration.ts'
import type { StoryNode, StoryEdge } from './storyWorkflow.ts'

export const writingNode = (node: StoryNode) => ['text', 'script'].includes(node.type || '')
/** Group frames select their contents; only supported executable node kinds run. */
export function selectedRunTargets(ids: string[], nodes: StoryNode[]) {
  const chosen = new Set(ids)
  let changed = true
  while (changed) {
    changed = false
    for (const node of nodes) if (node.parentId && chosen.has(node.parentId) && !chosen.has(node.id)) { chosen.add(node.id); changed = true }
  }
  return nodes.filter(node => chosen.has(node.id) && ['text', 'script', 'character', 'scene', 'image', 'imageGeneration', 'video', 'videoGeneration'].includes(node.type || '')).map(node => node.id)
}
export const nodeRunning = (node: StoryNode) => ['queued', 'running', 'awaiting_composite'].includes(String(node.data.status))
export const nodeResultReady = (node: StoryNode) => !nodeRunning(node) && !['failed', 'error', 'cancelled'].includes(String(node.data.status)) && (writingNode(node) ? !!String(node.data.text || '').trim() : !!collectMediaUrls(node.data).length)

/** Follow dependencies, not canvas position. Completed results cut off their ancestors. */
export function dependencyPlan(targets: string[], nodes: StoryNode[], edges: StoryEdge[]) {
  const byId = new Map(nodes.map(node => [node.id, node])), visiting = new Set<string>(), visited = new Set<string>()
  const ordered: StoryNode[] = []
  const visit = (id: string) => {
    if (visiting.has(id)) throw new Error('节点连线存在循环，请断开循环后运行')
    if (visited.has(id)) return
    const node = byId.get(id)
    if (!node) throw new Error('依赖节点已删除，请检查连线')
    visiting.add(id)
    if (!nodeResultReady(node) || writingNode(node) && writingParametersChanged(node, writingContext(node,nodes,edges).outputs)) {
      if (nodeRunning(node)) { ordered.push(node); visiting.delete(id); visited.add(id); return }
      if (!writingNode(node) && !['image', 'video'].includes(nodeMediaKind(node))) throw new Error(`「${node.data.label || id}」暂不支持依赖运行`)
      if (writingNode(node) && !String(node.data.writingPrompt || '').trim() && !nodeRunning(node)) throw new Error(`请先填写「${node.data.label || id}」的 AI 写作要求`)
      for (const source of edges.filter(edge => edge.target === id).map(edge => edge.source)) visit(source)
      for (const source of [node.data.promptNodeId, ...(Array.isArray(node.data.referenceNodeIds) ? node.data.referenceNodeIds : [])].filter(Boolean).map(String)) {
        if (!edges.some(edge => edge.source === source && edge.target === id)) throw new Error(`「${node.data.label || id}」的依赖连线不完整`)
      }
      ordered.push(node)
    }
    visiting.delete(id); visited.add(id)
  }
  targets.forEach(visit)
  return ordered
}

/** Immutable requirements/links are checked again before each submission. */
export function dependencySignature(ids: string[], nodes: StoryNode[], edges: StoryEdge[]) {
  const selected = new Set(ids)
  const context = new Set(ids)
  for (const writer of nodes.filter(node => selected.has(node.id) && writingNode(node))) {
    nodes.filter(node => node.data.promptNodeId === writer.id || writer.data.outputNodeId === node.id || edges.some(edge => edge.source === writer.id && edge.target === node.id)).forEach(node => context.add(node.id))
  }
  for (const id of context) {
    edges.filter(edge => edge.target === id).forEach(edge => context.add(edge.source))
    const script = nodes.find(node => node.id === id)?.data.sourceScriptId
    if (script) context.add(String(script))
  }
  return JSON.stringify({ nodes: nodes.filter(node => context.has(node.id)).map(node => ({ id: node.id, type: node.type,
    data: Object.fromEntries(Object.entries(node.data).filter(([key]) => !['status', 'taskId', 'error', 'canCancel', 'cancelRequested', 'naturalWidth', 'naturalHeight', 'mediaLayoutUrl', 'userResized'].includes(key) && (!selected.has(node.id) || !['text', 'mediaUrl', 'mediaUrls', 'mediaIndex', 'url', 'cover'].includes(key))).sort(([a], [b]) => a.localeCompare(b))) })).sort((a,b) => a.id.localeCompare(b.id)),
    edges: edges.filter(edge => context.has(edge.target)).map(edge => [edge.source, edge.target]).sort() })
}

/** Only quoting uses stand-in outputs; execution always resolves the live graph. */
export function dependencyQuoteInputs(plan: StoryNode[], nodes: StoryNode[], edges: StoryEdge[], settings: BatchSettings): BatchInput[] {
  const copy = structuredClone(nodes)
  return plan.flatMap(node => {
    const current = copy.find(item => item.id === node.id)!
    let input: BatchInput | undefined
    if (!nodeRunning(node)) {
      if (writingNode(node)) {
        const model = String(node.data.writingModel || settings.textModel || '')
        if (!model) throw new Error('请选择可用的文字模型')
        input = { id: node.id, label: String(node.data.label || '写作'), kind: 'text', prompt: String(node.data.writingPrompt), model, resolution: '', ratio: '', duration: '', references: [] }
      } else input = batchInputs([node.id], copy, edges, settings)[0]
    }
    current.data = { ...current.data, status: 'completed', ...(writingNode(node) ? { text: '运行时由上游写作节点生成', writingOutputSettings: writingContext(node,nodes,edges,settings).outputs } : { mediaUrl: `pending:${node.id}`, mediaUrls: [] }) }
    return input ? [input] : []
  })
}

/** Independent branches run together; dependants start only after successful results. */
export async function executeDependencies(plan: StoryNode[], edges: StoryEdge[], run: (node: StoryNode) => Promise<void>, check: () => void) {
  const remaining = new Map(plan.map(node => [node.id, node])), done = new Set<string>(), ids = new Set(remaining.keys())
  while (remaining.size) {
    check()
    const ready = [...remaining.values()].filter(node => edges.filter(edge => edge.target === node.id && ids.has(edge.source)).every(edge => done.has(edge.source)))
    if (!ready.length) throw new Error('节点依赖存在循环')
    const outcomes = await Promise.allSettled(ready.map(async node => { check(); await run(node) }))
    const failed = outcomes.find((result): result is PromiseRejectedResult => result.status === 'rejected')
    if (failed) throw failed.reason
    ready.forEach(node => { remaining.delete(node.id); done.add(node.id) })
  }
}
