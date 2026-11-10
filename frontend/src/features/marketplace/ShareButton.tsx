import { useEffect, useRef, useState } from 'react'
import { Share2 } from 'lucide-react'
import { request } from './api'
import { marketText as mt, marketFeedback } from './translate'

type ShareSession = { token: string; url: string; title: string; description: string; expires_at: string }
type PreparedShare = ShareSession & { anonymous_id: string; target: string; credential: string | null }
type ShareAction = 'completed' | 'copied' | 'cancelled'

function anonymousId(): string {
  const key = 'pf-market-share-installation'
  const current = localStorage.getItem(key)
  if (current && /^[A-Za-z0-9_-]{16,128}$/.test(current)) return current
  const id = crypto.randomUUID().replaceAll('-', '')
  localStorage.setItem(key, id)
  return id
}

export default function ShareButton({ kind, id }: { kind: 'work' | 'series_episode'; id: number }) {
  const [enabled, setEnabled] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [prepared, setPrepared] = useState<PreparedShare | null>(null)
  const [pendingAction, setPendingAction] = useState<ShareAction | null>(null)
  const running = useRef(false)
  const target = `${kind}:${id}`
  const activeTarget = useRef(target)
  activeTarget.current = target
  useEffect(() => {
    let active = true
    request<{ sharing_enabled?: boolean }>('/capabilities').then(value => { if (active) setEnabled(Boolean(value.sharing_enabled)) }).catch(() => undefined)
    return () => { active = false }
  }, [])
  useEffect(() => { setMessage(''); setPrepared(null); setPendingAction(null) }, [id, kind])
  if (!enabled) return null

  async function prepare() {
    if (running.current) return
    running.current = true
    setBusy(true); setMessage('')
    try {
      const identity = { anonymous_id: anonymousId() }
      const credential = localStorage.getItem('token')
      const session = await request<ShareSession>(`/app/v1/${kind === 'work' ? 'works' : 'episodes'}/${id}/share-sessions`, 'POST', identity)
      const url = new URL(session.url)
      if (url.protocol !== 'https:' || url.username || url.password) throw new Error(mt('分享链接暂不可用'))
      if (activeTarget.current === target) setPrepared({ ...session, ...identity, target, credential })
    } catch (error) { if (activeTarget.current === target) setMessage((error as Error).message || mt('分享失败，请稍后重试')) }
    finally { running.current = false; setBusy(false) }
  }

  async function record(session: PreparedShare, action: ShareAction) {
    if (!sameIdentity(session)) return
    try {
      await request(`/app/v1/share-sessions/${encodeURIComponent(session.token)}/events`, 'POST', { anonymous_id: session.anonymous_id, action })
    } catch (error) {
      if ([404, 410].includes((error as { status?: number }).status || 0)) {
        if (activeTarget.current === session.target) {
          setPrepared(null); setPendingAction(null); setMessage((error as Error).message)
        }
        return
      }
      throw error
    }
    if (activeTarget.current === session.target) {
      setPrepared(null); setPendingAction(null)
      setMessage(action === 'cancelled' ? '' : action === 'copied' ? mt('作品链接已复制') : mt('分享操作已完成'))
    }
  }

  function sameIdentity(session: PreparedShare) {
    if (session.credential === localStorage.getItem('token')) return true
    if (activeTarget.current === session.target) {
      setPrepared(null); setPendingAction(null); setMessage(mt('账号状态已变化，请重新准备分享'))
    }
    return false
  }

  async function send(channel: 'native' | 'copy') {
    if (!prepared || prepared.target !== target || running.current) return
    if (!sameIdentity(prepared)) return
    if (Date.parse(prepared.expires_at) <= Date.now()) { setPrepared(null); setMessage(mt('分享链接已过期，请重新准备')); return }
    running.current = true; setBusy(true); setMessage('')
    let action: ShareAction | null = null
    try {
      // A second explicit click preserves Safari's transient user activation.
      if (channel === 'native' && navigator.share) {
        try {
          await navigator.share({ title: prepared.title, text: prepared.description, url: prepared.url })
          action = 'completed'
        } catch (error) {
          if ((error as Error).name !== 'AbortError') throw error
          action = 'cancelled'
        }
      } else {
        await navigator.clipboard.writeText(prepared.url)
        action = 'copied'
      }
      if (activeTarget.current === prepared.target) setPendingAction(action)
      await record(prepared, action)
    } catch (error) {
      if (activeTarget.current === target) setMessage(action ? mt('分享已处理，记录同步失败，请重试同步') : (error as Error).message || mt('分享失败，请稍后重试'))
    } finally { running.current = false; setBusy(false) }
  }

  async function retryRecord() {
    if (!prepared || !pendingAction || running.current) return
    running.current = true; setBusy(true)
    try { await record(prepared, pendingAction) }
    catch { setMessage(mt('分享已处理，记录同步失败，请重试同步')) }
    finally { running.current = false; setBusy(false) }
  }
  return <div className="pf-market-share">
    {!prepared || prepared.target !== target ? <button type="button" disabled={busy} onClick={() => void prepare()}><Share2 size={16} />{busy ? mt('正在准备分享…') : mt('分享作品')}</button>
      : pendingAction ? <button type="button" disabled={busy} onClick={() => void retryRecord()}>{mt('重试同步分享记录')}</button>
        : <>{typeof navigator.share === 'function' && <button type="button" disabled={busy} onClick={() => void send('native')}><Share2 size={16} />{mt('发送作品链接')}</button>}<button type="button" disabled={busy} onClick={() => void send('copy')}>{mt('复制作品链接')}</button></>}
    {message && <small role="status">{marketFeedback(message)}</small>}
  </div>
}
