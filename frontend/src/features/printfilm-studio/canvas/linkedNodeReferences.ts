import { nodeMediaKind } from './nodeOperations.ts'
import { collectMediaUrls } from './imageVariants.ts'

type RefNode = {id:string;type?:string;data:Record<string,unknown>}

/** Connections describe references even before their first generated result. */
export function linkedNodeReferences<T extends RefNode>(target:T|undefined,nodes:T[],edges:{source:string;target:string}[]):T[] {
  if(!target) return []
  const ids=new Set(edges.filter(edge=>edge.target===target.id).map(edge=>edge.source))
  if(typeof target.data.promptNodeId==='string') ids.add(target.data.promptNodeId)
  if(Array.isArray(target.data.referenceNodeIds)) target.data.referenceNodeIds.forEach(id=>ids.add(String(id)))
  const byId=new Map(nodes.map(node=>[node.id,node]))
  return [...ids].map(id=>byId.get(id)).filter((node):node is T=>!!node && node.id!==target.id && node.type!=='group')
}

export function referenceState(node:RefNode):string {
  if(['queued','running','processing','awaiting_composite'].includes(String(node.data.status))) return '生成中'
  const ready=nodeMediaKind(node)==='text' ? !!String(node.data.text || '').trim() : collectMediaUrls(node.data).length>0
  if(ready) return ''
  if(node.data.status==='failed') return '生成失败'
  return '待生成'
}
