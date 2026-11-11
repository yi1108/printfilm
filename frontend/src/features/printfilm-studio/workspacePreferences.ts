import { nodeMediaKind } from './canvas/nodeOperations.ts'
import type { CanvasDocument } from './canvas/canvasCodec'
import { currentImageModel, currentTextModel } from './modelPreferences.ts'
import { studioMediaRatio } from './mediaRatio.ts'
export type NodeDefaults = { image: string; video: string; text: string }
const key = 'printfilm.node-defaults.v1'
export function readNodeDefaults(): NodeDefaults { try { const value={image:'',video:'',text:'',...JSON.parse(localStorage.getItem(key)||'{}')}; return {...value,image:currentImageModel(String(value.image || '')),text:currentTextModel(String(value.text || ''))} } catch { return {image:'',video:'',text:''} } }
export function saveNodeDefaults(value: NodeDefaults) { localStorage.setItem(key,JSON.stringify(value)) }
export function defaultNodeData(type: string) { const kind=nodeMediaKind({type,data:{}}), value=readNodeDefaults(); return kind==='text'? {writingModel:value.text||undefined} : kind==='image'||kind==='video'? {modelId:value[kind]||undefined,ratio:studioMediaRatio(kind)}:{} }
export type CanvasSnapshot = { id: string; savedAt: string; version: number; document: CanvasDocument }
function snapshotKey(projectId: number) { const token=localStorage.getItem('token')||''; let owner='guest'; try { owner=String(JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub) } catch { let hash=0;for(const char of token)hash=Math.imul(hash,31)+char.charCodeAt(0)|0;owner=String(hash) };return `printfilm.snapshots.${owner}.${projectId}` }
export function readSnapshots(projectId: number): CanvasSnapshot[] { try { return JSON.parse(localStorage.getItem(snapshotKey(projectId))||'[]') } catch { return [] } }
export function storeSnapshot(projectId: number, document: CanvasDocument, version: number) {
  try { const items=readSnapshots(projectId); const now=Date.now(); const previous=items[0]; if(previous && now-new Date(previous.savedAt).getTime()<60000) return; const next=[{id:crypto.randomUUID(),savedAt:new Date(now).toISOString(),version,document},...items].slice(0,12); while(next.length && JSON.stringify(next).length>1800000) next.pop(); localStorage.setItem(snapshotKey(projectId),JSON.stringify(next)) } catch { /* Saving the canvas must never fail because browser storage is full. */ }
}
