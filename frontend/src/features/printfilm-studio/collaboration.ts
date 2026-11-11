import { useCallback, useEffect, useRef } from 'react'
import { API_BASE } from '../../api/client'

export type CanvasPoint = { x: number; y: number }
export type CanvasActivity = 'idle' | 'selecting' | 'dragging' | 'editing' | 'connecting' | 'generating' | 'saved'
export type Awareness = { cursor: CanvasPoint | null; action: CanvasActivity; node_ids: string[]; positions: (CanvasPoint & {id: string})[] }
export type CanvasPeer = Awareness & { session_id: string; user_id: number; name: string; color: string; seen_at: number }
export type PresenceStatus = 'connecting' | 'online' | 'offline' | 'denied'
export const emptyAwareness = (): Awareness => ({cursor:null,action:'idle',node_ids:[],positions:[]})

export function createPresenceStore() {
  let snapshot: {peers: CanvasPeer[];status: PresenceStatus} = {peers:[],status:'connecting'}
  const listeners = new Set<()=>void>()
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: ()=>void) => {listeners.add(listener);return ()=>{listeners.delete(listener)}},
    update: (patch: Partial<typeof snapshot>) => {
      if (Object.entries(patch).every(([key,value])=>snapshot[key as keyof typeof snapshot]===value)) return
      snapshot={...snapshot,...patch};listeners.forEach(listener=>listener())
    },
  }
}
export type PresenceStore = ReturnType<typeof createPresenceStore>

/** Token travels only in the first authenticated frame, never in a URL or log. */
export function connectPresence(url: string, token: string, onPeers: (peers: CanvasPeer[]) => void, onStatus: (status: PresenceStatus) => void, Socket: typeof WebSocket = WebSocket) {
  let socket: WebSocket | null = null, closed = false, denied = false, retry = 500, lastSent = 0
  let selfUserId: number | undefined
  let state = emptyAwareness(), flushTimer: ReturnType<typeof setTimeout> | undefined, reconnectTimer: ReturnType<typeof setTimeout> | undefined
  const send = () => {
    flushTimer = undefined
    if (socket?.readyState === 1) {socket.send(JSON.stringify(state));lastSent=Date.now()}
  }
  const update = (patch: Partial<Awareness>) => {
    state = {...state,...patch}
    if (!flushTimer) flushTimer = setTimeout(send,Math.max(0,100-(Date.now()-lastSent)))
  }
  const open = () => {
    if (closed || denied) return
    onStatus('connecting')
    socket = new Socket(url)
    socket.onopen = () => {lastSent=0;socket?.send(JSON.stringify({token}))}
    socket.onmessage = event => {
      try {
        const message = JSON.parse(String(event.data))
        if (message.type !== 'presence' || !Array.isArray(message.peers)) return
        retry=500;onStatus('online')
        const self = message.peers.find((peer: CanvasPeer) => peer.session_id === message.self_id)
        if (typeof self?.user_id === 'number') selfUserId = self.user_id
        // Other tabs and reconnecting sessions of this account are still ourselves.
        onPeers(message.peers.filter((peer: CanvasPeer) => peer.session_id !== message.self_id && (selfUserId === undefined || peer.user_id !== selfUserId) && Date.now()/1000-peer.seen_at<20).slice(0,64))
        // Background tabs throttle timers. Reply to the server's periodic snapshot
        // as well, so an open collaborator is not repeatedly evicted and rejoined.
        if (!lastSent || Date.now()-lastSent>=5000) send()
      } catch { /* A malformed awareness packet must not interrupt canvas editing. */ }
    }
    socket.onerror = () => { /* onclose schedules reconnection. */ }
    socket.onclose = event => {
      onPeers([])
      if (closed) return
      denied = event.code===4401 || event.code===4403
      onStatus(denied?'denied':'offline')
      if (!denied) {reconnectTimer=setTimeout(open,retry);retry=Math.min(10_000,retry*2)}
    }
  }
  const heartbeat=setInterval(()=>{if(socket?.readyState===1)send()},5000)
  open()
  return {update, close:()=>{closed=true;clearInterval(heartbeat);clearTimeout(flushTimer);clearTimeout(reconnectTimer);if(socket){socket.onclose=null;socket.onmessage=null;socket.onopen=null;socket.close()}}}
}

export function useCanvasPresence(projectId: number, enabled: boolean, epoch: number) {
  // Only the overlay subscribes. Cursor packets never rerender the canvas page.
  const storeRef=useRef<PresenceStore | null>(null)
  if (!storeRef.current) storeRef.current=createPresenceStore()
  const store=storeRef.current
  const channel=useRef<ReturnType<typeof connectPresence> | null>(null)
  useEffect(()=>{
    if (!enabled) return
    const token=localStorage.getItem('token') || ''
    if (token.split('.').length!==3 || typeof WebSocket==='undefined') {store.update({status:'offline'});return}
    const endpoint=new URL(`/api/printfilm-studio/projects/${projectId}/presence`,API_BASE || window.location.origin)
    endpoint.protocol=endpoint.protocol==='https:'?'wss:':'ws:'
    channel.current=connectPresence(endpoint.toString(),token,peers=>store.update({peers}),status=>store.update({status}))
    const clearCursor=()=>{if(document.hidden)channel.current?.update({cursor:null,action:'idle',positions:[]})}
    document.addEventListener('visibilitychange',clearCursor)
    return ()=>{document.removeEventListener('visibilitychange',clearCursor);channel.current?.close();channel.current=null;store.update({peers:[]})}
  },[projectId,enabled,epoch,store])
  const update=useCallback((patch: Partial<Awareness>)=>channel.current?.update(patch),[])
  return {store,update}
}

type PositionedNode = {id: string;parentId?:string;position:{x:number;y:number}}
export function absoluteNodePosition(node: PositionedNode, nodes: PositionedNode[]): CanvasPoint {
  let {x,y}=node.position, parent=node.parentId
  const visited=new Set([node.id])
  while(parent && !visited.has(parent)) {
    visited.add(parent)
    const item=nodes.find(item=>item.id===parent)
    if(!item)break
    x+=item.position.x;y+=item.position.y;parent=item.parentId
  }
  return {x,y}
}
