import { nodeMediaKind } from './nodeOperations.ts'
import { collectMediaUrls,clampMediaIndex } from './imageVariants.ts'
import type { Node,Edge } from '@xyflow/react'
export type CompositionClip={id:string;label:string;url:string;ready:boolean;status:string}
export function compositionClips(id:string,nodes:Node<Record<string,unknown>>[],edges:Edge[]):CompositionClip[] {
  const target=nodes.find(node=>node.id===id),incoming=edges.filter(edge=>edge.target===id).map(edge=>edge.source)
  const saved=Array.isArray(target?.data.compositionOrder)?target.data.compositionOrder.map(String):[]
  return [...new Set([...saved.filter(value=>incoming.includes(value)),...incoming])].flatMap(value=>{
    const node=nodes.find(item=>item.id===value)
    if(!node || nodeMediaKind(node)!=='video')return []
    const urls=collectMediaUrls(node.data),url=urls[clampMediaIndex(node.data.mediaIndex,urls.length)]||'',status=String(node.data.status || '')
    return [{id:value,label:String(node.data.label || '视频片段'),url,ready:!!url&&!['queued','running','awaiting_composite','failed','cancelled'].includes(status),status}]
  })
}
export function compositionError(clips:CompositionClip[]) {
  if(clips.length<2)return '请连接至少 2 个视频片段'
  if(clips.length>8)return '每次最多合成 8 个片段，请分段编排'
  const pending=clips.find(clip=>!clip.ready)
  return pending?`「${pending.label}」${['queued','running','awaiting_composite'].includes(pending.status)?'仍在生成':'尚无可用视频'}`:''
}
