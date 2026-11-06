import { useEffect, useState, type FormEvent } from 'react'
import { Pin, Sparkles } from 'lucide-react'
import { AdminModal } from '@/components/admin/AdminModal'
import { PaginationBar } from '@/components/PaginationBar'
import { request, type Item, type Listing } from './api'
import { operationInteger } from './operationInputs'

type TargetType = 'work' | 'series'
type Curation = { target_type: TargetType; target_id: number; is_featured: boolean; is_pinned: boolean; pin_priority: number; version: number }
export type CurationTarget = Omit<Curation, 'version'> & { curation_version: number }
const base = '/api/admin/marketplace'

export function CurationControls({ targetType, targetId, isFeatured = false, isPinned = false, split = false, onSaved }: {
  targetType: TargetType; targetId: number; isFeatured?: boolean; isPinned?: boolean; split?: boolean; onSaved?: () => void
}) {
  const [action, setAction] = useState<'settings' | 'feature' | 'pin' | null>(null)
  return <>{split ? <>
    <button type="button" aria-pressed={isFeatured} onClick={() => setAction('feature')}><Sparkles size={14} />{isFeatured ? '取消加精' : '加精'}</button>
    <button type="button" aria-pressed={isPinned} onClick={() => setAction('pin')}><Pin size={14} />{isPinned ? '取消置顶' : '置顶'}</button>
  </> : <button type="button" onClick={() => setAction('settings')}>设置精选与置顶</button>}
    {action && <CurationEditor targetType={targetType} targetId={targetId} initialAction={action} onClose={() => setAction(null)} onSaved={() => { setAction(null); onSaved?.() }} />}
  </>
}

function CurationEditor({ targetType, targetId, initialAction, onClose, onSaved }: {
  targetType: TargetType; targetId: number; initialAction: 'settings' | 'feature' | 'pin'; onClose: () => void; onSaved: () => void
}) {
  const [value, setValue] = useState<Curation | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [priority, setPriority] = useState('100')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    setError(''); setValue(null)
    request<Curation>(`${base}/curation/${targetType}/${targetId}`).then(result => {
      if (active) {
        setValue({ ...result, is_featured: initialAction === 'feature' ? !result.is_featured : result.is_featured,
          is_pinned: initialAction === 'pin' ? !result.is_pinned : result.is_pinned })
        setPriority(String(result.pin_priority))
      }
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [targetType, targetId, initialAction, revision])
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!value) return
    const form = new FormData(event.currentTarget)
    setError('')
    try {
      const reason = String(form.get('reason') || '').trim()
      if (!reason) throw new Error('请填写调整原因')
      const pinPriority = operationInteger(priority, 9999)
      setBusy(true)
      await request(`${base}/curation/${targetType}/${targetId}`, 'PATCH', { version: value.version, is_featured: value.is_featured, is_pinned: value.is_pinned, pin_priority: pinPriority, reason })
      onSaved()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <AdminModal className="market-ops-operation-modal" open onOpenChange={next => { if (!next && !busy) onClose() }} title="精选与置顶" subtitle={`${targetType === 'work' ? '单视频' : '短剧系列'} #${targetId}`} size="lg">
    {error && <p className="market-ops-feedback is-error" role="alert">{error}<button type="button" disabled={busy} onClick={() => setRevision(v => v + 1)}>重新加载配置</button></p>}
    {!value ? !error && <p role="status">正在加载运营配置…</p> : <form className="market-ops-support market-ops-modal-form" onSubmit={save}>
      <p>Web 广场和 App 推荐列表统一生效。下架、封禁及版权限制仍优先执行；分集目录始终按集号排列。</p>
      <label><input type="checkbox" checked={value.is_featured} disabled={busy} onChange={event => setValue({ ...value, is_featured: event.target.checked })} /> 加精（显示“精选”并在默认推荐排序优先）</label>
      <label><input type="checkbox" checked={value.is_pinned} disabled={busy} onChange={event => setValue({ ...value, is_pinned: event.target.checked })} /> 置顶（优先于精选）</label>
      <label>置顶排序值（0～9999，越大越靠前）<input inputMode="numeric" value={priority} disabled={busy} onChange={event => setPriority(event.target.value)} /></label>
      <label>调整原因<textarea name="reason" required maxLength={300} disabled={busy} /></label><div className="flex gap-3"><button type="submit" disabled={busy}>{busy ? '正在保存…' : '保存配置'}</button><button type="button" disabled={busy} onClick={onClose}>取消</button></div>
    </form>}
  </AdminModal>
}

export function CurationBatchActions({ items, onSaved }: { items: CurationTarget[]; onSaved: () => void }) {
  const [action, setAction] = useState('feature')
  const [priority, setPriority] = useState('100')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setMessage('')
    if (!items.length || busy) return
    try {
      if (!reason.trim()) throw new Error('请填写批量操作原因')
      const pinPriority = operationInteger(priority, 9999)
      const changes = items.map(item => ({ target_type: item.target_type, target_id: item.target_id, version: item.curation_version,
        is_featured: action === 'feature' ? true : action === 'unfeature' ? false : item.is_featured,
        is_pinned: action === 'pin' ? true : action === 'unpin' ? false : item.is_pinned,
        pin_priority: action === 'pin' ? pinPriority : item.pin_priority }))
      setBusy(true)
      const result = await request<{ items: Array<{ target_id: number; target_type: string; ok: boolean; error?: { message?: string } }> }>(`${base}/curation/batch`, 'POST', { items: changes, reason: reason.trim() })
      const failed = result.items.filter(item => !item.ok)
      setMessage(`已处理 ${result.items.length - failed.length} 条${failed.length ? `，失败 ${failed.length} 条：${failed.map(item => `${item.target_type === 'series' ? '系列' : '单视频'} #${item.target_id} ${item.error?.message || '请刷新后重试'}`).join('；')}` : ''}`)
      onSaved()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <details className="market-ops-record market-ops-bulk"><summary>批量加精与置顶 · 已选 {items.length} 条</summary>
    <form className="market-ops-inline-form" onSubmit={save}>
      <label>批量操作<select value={action} disabled={busy} onChange={event => setAction(event.target.value)}><option value="feature">加精</option><option value="unfeature">取消加精</option><option value="pin">置顶</option><option value="unpin">取消置顶</option></select></label>
      {action === 'pin' && <label>置顶排序值<input inputMode="numeric" value={priority} disabled={busy} onChange={event => setPriority(event.target.value)} /></label>}
      <label>调整原因<input required maxLength={300} value={reason} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
      <button type="submit" disabled={busy || !items.length}>{busy ? '正在处理…' : `应用到已选 ${items.length} 条`}</button>
    </form>
    {error && <p className="market-ops-feedback is-error" role="alert">{error}</p>}{message && <p className="market-ops-feedback" role="status">{message}</p>}
  </details>
}

export function CurationHistoryPanel({ revision }: { revision: number }) {
  const [type, setType] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Listing | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true; setData(null); setError('')
    request<Listing>(`${base}/curation/events?${new URLSearchParams({ ...(type ? { target_type: type } : {}), page: String(page), page_size: '20' })}`)
      .then(value => { if (active) setData(value) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [type, page, revision])
  return <section className="market-ops-record"><div className="market-ops-record-head"><h3>精选与置顶操作记录</h3><select aria-label="操作记录内容类型" value={type} onChange={event => { setType(event.target.value); setPage(1) }}><option value="">全部类型</option><option value="work">单视频</option><option value="series">短剧系列</option></select></div>
    {error ? <p role="alert">{error}</p> : !data ? <p role="status">正在读取操作记录…</p> : data.items.length ? <>
      <div className="market-ops-table-scroll"><table className="market-ops-metrics-table"><thead><tr><th>作品</th><th>操作人</th><th>原因</th><th>时间</th><th>修改前后</th></tr></thead><tbody>{data.items.map(item => <tr key={item.id}><td>{item.target_type === 'series' ? '系列' : '单视频'} #{String(item.target_id)}</td><td>#{String(item.operator_id || '')}</td><td>{String(item.reason || '')}</td><td>{new Date(String(item.created_at)).toLocaleString('zh-CN')}</td><td><CurationHistory item={item} /></td></tr>)}</tbody></table></div>
      <PaginationBar page={page} pageSize={data.meta.page_size} total={data.meta.total} onPageChange={setPage} />
    </> : <p>暂无操作记录</p>}
  </section>
}

function CurationHistory({ item }: { item: Item }) {
  const display = (value: unknown) => { const state = typeof value === 'object' && value ? value as Record<string, unknown> : {}; return `${state.is_pinned ? '置顶' : '未置顶'} / ${state.is_featured ? '精选' : '普通'} / 排序值 ${String(state.pin_priority ?? 100)}` }
  return <span>{display(item.before)} → {display(item.after)}</span>
}
