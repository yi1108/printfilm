import { collectMediaUrls } from './imageVariants.ts'
export type MediaSnapshot = { mediaUrl: string; mediaUrls?: string[]; mediaIndex?: number; assetId?: number; mediaType?: string; label?: string; savedAt: string; prompt?: string; modelId?: string; ratio?: string; resolution?: string; duration?: string }
export function mediaSnapshot(data: Record<string, unknown>): MediaSnapshot {
  const details=data.mediaOutputMetadata && typeof data.mediaOutputMetadata==='object' ? data.mediaOutputMetadata as Record<string,unknown> : data
  return { mediaUrl:String(data.mediaUrl || data.url || ''),mediaUrls:collectMediaUrls(data),mediaIndex:Number(data.mediaIndex)||0,assetId:typeof data.assetId==='number'?data.assetId:undefined,mediaType:String(data.mediaType || ''),label:String(data.label || ''),savedAt:new Date().toISOString(),...Object.fromEntries(['prompt','modelId','ratio','resolution','duration'].filter(key=>details[key]!=null).map(key=>[key,String(details[key])])) }
}
export function mediaHistory(data: Record<string, unknown>): MediaSnapshot[] {
  return Array.isArray(data.mediaHistory) ? data.mediaHistory.filter((item): item is MediaSnapshot => !!item && typeof item === 'object' && typeof item.mediaUrl === 'string').slice(-30) : []
}
export function replaceNodeMedia(data: Record<string, unknown>, next: Partial<MediaSnapshot>) {
  const previous = String(data.mediaUrl || data.url || '')
  const history = mediaHistory(data)
  const snapshot=mediaSnapshot(data)
  const signature=(item:MediaSnapshot)=>JSON.stringify([collectMediaUrls(item).sort(),item.prompt,item.modelId,item.ratio,item.resolution,item.duration])
  // Navigating candidates must not consume history slots or evict other runs.
  if (previous && previous !== next.mediaUrl && !history.some(item=>signature(item)===signature(snapshot))) history.push(snapshot)
  return { ...data, ...next, mediaOutputMetadata:undefined, mediaUrl: next.mediaUrl, url: next.mediaUrl, mediaUrls: next.mediaUrls || [next.mediaUrl], mediaIndex: next.mediaIndex || 0, taskId: undefined, inpaint: undefined, error: undefined, status: 'completed', mediaHistory: history.slice(-30) }
}

/** Combine every output from every run; URLs are stable identities, not array positions. */
export function mediaCandidates(data: Record<string, unknown>): MediaSnapshot[] {
  const byUrl = new Map<string,MediaSnapshot>()
  for (const snapshot of [...mediaHistory(data),mediaSnapshot(data)]) {
    for (const [index,url] of collectMediaUrls(snapshot).entries()) byUrl.set(url,{...snapshot,mediaUrl:url,mediaIndex:index})
  }
  const order=Array.isArray(data.mediaCandidateOrder)?data.mediaCandidateOrder.map(String):[]
  return [...new Set([...order,...byUrl.keys()])].flatMap(url=>byUrl.has(url)?[byUrl.get(url)!]:[])
}

export function adoptMediaCandidate(data:Record<string,unknown>,candidate:MediaSnapshot) {
  // Media selection does not silently replace the user's current generation settings.
  const next=replaceNodeMedia(data,{mediaUrl:candidate.mediaUrl,mediaUrls:candidate.mediaUrls,mediaIndex:candidate.mediaIndex,assetId:candidate.assetId,mediaType:candidate.mediaType || String(data.mediaType || '')})
  return {...next,mediaOutputMetadata:Object.fromEntries(['prompt','modelId','ratio','resolution','duration'].map(key=>[key,candidate[key as keyof MediaSnapshot]])),mediaCandidateOrder:mediaCandidates(data).map(item=>item.mediaUrl)}
}
