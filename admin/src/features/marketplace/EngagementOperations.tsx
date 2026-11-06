import { useEffect, useState, type FormEvent } from 'react'
import { PaginationBar } from '@/components/PaginationBar'
import { AdminModal } from '@/components/admin/AdminModal'
import { Bookmark, Film, Heart, History, Play, RefreshCw, Search, Share2, SlidersHorizontal } from 'lucide-react'
import { request, assetUrl } from './api'
import { displayMetricsInput } from './operationInputs'
import { CurationBatchActions, CurationControls, CurationHistoryPanel, type CurationTarget } from './CurationOperations'

type Counts = Record<'like_count' | 'favorite_count' | 'share_count', number>
type Metric = { target_type: 'work' | 'series' | 'series_episode'; target_id: number; title: string; version: number; real: Counts; initial: Counts; display: Counts;
  author: string; owner_id: number; category: string; cover_asset_id: number | null; asset_id: number | null; series_title?: string | null; episode_no?: number | null;
  audit_status: string; listed: boolean; blocked: boolean; is_featured: boolean; is_pinned: boolean; pin_priority: number; curation_version: number; updated_at?: string; updated_by?: number }
type Job = { id: number; status: string; total: number; processed: number; initialized: number; skipped: number; failed: number; errors?: unknown[] }
const base = '/api/admin/marketplace/app/social'
const labels = { like_count: '点赞', favorite_count: '收藏', share_count: '分享' } as const
const targetNames: Record<string, string> = { work: '单视频', series_episode: '短剧分集', series: '短剧系列' }
const number = (value: number) => value.toLocaleString('zh-CN')
const metricKey = (item: Metric) => `${item.target_type}:${item.target_id}`

export default function EngagementOperations({ revision = 0 }: { revision?: number }) {
  const [target, setTarget] = useState('')
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [curation, setCuration] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [showEvents, setShowEvents] = useState(false)
  const [previewing, setPreviewing] = useState<Metric | null>(null)
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [listing, setListing] = useState<{ items: Metric[]; total: number; page_size: number } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Metric | null>(null)
  const [history, setHistory] = useState<Metric | null>(null)
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState<number | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [jobId, setJobId] = useState('')
  const [jobTarget, setJobTarget] = useState('')
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setListing(null); setSelected([])
    request<typeof listing>(`${base}/metrics?${new URLSearchParams({ page: String(page), page_size: '20', ...(target ? { target_type: target } : {}), q: query, curation })}`)
      .then(value => { if (active) setListing(value) }).catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [target, query, curation, page, refresh, revision])
  useEffect(() => {
    if (!job || !['pending', 'running', 'queued'].includes(job.status)) return
    let active = true
    const timer = window.setTimeout(() => {
      request<Job>(`${base}/initialization-jobs/${job.id}`).then(value => { if (active) { setJob(value); if (!['pending', 'running', 'queued'].includes(value.status)) setRefresh(v => v + 1) } }).catch(e => { if (active) setError(e.message) })
    }, 2500)
    return () => { active = false; window.clearTimeout(timer) }
  }, [job])
  async function initialize(previewOnly: boolean) {
    if (!previewOnly && !reason.trim()) { setError('请填写初始化原因'); return }
    setBusy(true); setError('')
    try {
      const result = await request<Job & { preview?: boolean; total: number }>(`${base}/initialization-jobs`, 'POST', { preview: previewOnly, ...(jobTarget ? { target_type: jobTarget } : {}), reason: reason.trim() || '预览可初始化内容' })
      if (previewOnly) setPreview(result.total)
      else { setJob(result); setJobId(String(result.id)); setPreview(null) }
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  async function loadJob(retry = false) {
    if (!/^\d+$/.test(jobId)) { setError('请输入任务编号'); return }
    setBusy(true); setError('')
    try { setJob(await request<Job>(`${base}/initialization-jobs/${jobId}${retry ? '/retry' : ''}`, retry ? 'POST' : 'GET')); setRefresh(v => v + 1) }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  const selectable = listing?.items.filter(item => item.target_type !== 'series_episode') || []
  const batchItems = selectable.filter(item => selected.includes(metricKey(item))).map(item => ({ ...item, target_type: item.target_type as 'work' | 'series' })) satisfies CurationTarget[]
  return <section className="market-ops-engagement">
    <header className="market-ops-content-heading"><div><span>内容推荐与互动管理</span><h2>作品运营</h2><p>用封面找到作品，集中管理精选、置顶和互动数量。</p></div><button type="button" aria-expanded={showEvents} onClick={() => setShowEvents(value => !value)}><History size={15} />{showEvents ? '收起运营记录' : '运营记录'}</button></header>
    <form className="market-ops-content-filters" onSubmit={event => { event.preventDefault(); setQuery(q.trim()); setPage(1); setRefresh(value => value + 1) }}>
      <div className="market-ops-type-tabs" aria-label="运营内容类型">{[['', '全部作品'], ...Object.entries(targetNames)].map(([value, label]) => <button key={value} type="button" aria-pressed={target === value} onClick={() => { setTarget(value); if (value === 'series_episode') setCuration(''); setPage(1) }}>{label}</button>)}</div>
      <div className="market-ops-content-search"><label><Search size={17} /><input aria-label="搜索运营作品" value={q} maxLength={100} onChange={event => setQ(event.target.value)} placeholder="搜索作品名称或短剧名称" /></label><select aria-label="精选置顶状态" value={curation} disabled={target === 'series_episode'} onChange={event => { setCuration(event.target.value); setPage(1) }}><option value="">全部运营状态</option><option value="featured">已加精</option><option value="pinned">已置顶</option><option value="normal">普通内容</option></select><button type="submit"><Search size={15} />搜索</button><button type="button" aria-label="刷新作品运营" onClick={() => setRefresh(value => value + 1)}><RefreshCw size={15} /></button></div>
    </form>
    <div className="market-ops-content-toolbar"><span>{loading ? '正在更新作品…' : `共 ${number(listing?.total || 0)} 件作品`}</span><label><input type="checkbox" disabled={!selectable.length} checked={!!selectable.length && selected.length === selectable.length} onChange={event => setSelected(event.target.checked ? selectable.map(metricKey) : [])} />选择本页单视频与系列</label></div>
    <CurationBatchActions items={batchItems} onSaved={() => setRefresh(value => value + 1)} />
    <details className="market-ops-record"><summary>历史内容初始化与任务恢复</summary><div className="market-ops-inline-form">
      <label>初始化范围<select value={jobTarget} disabled={busy} onChange={event => { setJobTarget(event.target.value); setPreview(null) }}><option value="">单视频和分集</option><option value="work">单视频</option><option value="series_episode">短剧分集</option></select></label>
      <label>操作原因<input value={reason} maxLength={300} disabled={busy} onChange={event => setReason(event.target.value)} /></label>
      <button type="button" disabled={busy} onClick={() => void initialize(true)}>预览待初始化数量</button><button type="button" disabled={busy || preview === null || preview === 0} onClick={() => void initialize(false)}>创建初始化任务</button>
      {preview !== null && <p role="status">待初始化 {number(preview)} 条；已有初始配置不会重复生成。</p>}
      <label>任务编号<input inputMode="numeric" value={jobId} onChange={event => setJobId(event.target.value)} placeholder="关闭页面后凭编号恢复" /></label><button type="button" disabled={busy} onClick={() => void loadJob()}>查询任务</button>
    </div>{job && <div className="market-ops-feedback" role="status"><strong>任务 #{job.id} · {({ pending: '排队中', queued: '排队中', running: '处理中', completed: '已完成', done: '已完成', failed: '失败', partial: '部分失败', completed_with_errors: '部分失败' } as Record<string, string>)[job.status] || job.status}</strong><p>总计 {job.total} · 已处理 {job.processed} · 已初始化 {job.initialized} · 跳过 {job.skipped} · 失败 {job.failed}</p>{!!job.failed && <button type="button" disabled={busy} onClick={() => void loadJob(true)}>重试失败项</button>}{job.errors?.length ? <ul>{job.errors.map((item, index) => <li key={index}>{typeof item === 'string' ? item : typeof item === 'object' && item ? String((item as Record<string, unknown>).message || (item as Record<string, unknown>).error || '处理失败，请查询服务日志') : '处理失败'}</li>)}</ul> : null}</div>}</details>
    {error && <p className="market-ops-feedback is-error" role="alert">{error}</p>}
    {loading ? <div className="market-ops-content-grid" role="status" aria-label="正在读取运营作品">{[0, 1, 2, 3].map(value => <div className="market-ops-content-skeleton" key={value}><div /><span /><span /></div>)}</div> : listing?.items.length ? <div className="market-ops-content-grid">{listing.items.map(item => <article className="market-ops-content-card" key={metricKey(item)}>
      <div className="market-ops-content-cover"><OperationCover assetId={item.cover_asset_id} /><span className="market-ops-content-type">{targetNames[item.target_type]}</span><span className={`market-ops-content-status${item.blocked ? ' is-blocked' : ''}`}>{item.blocked ? '已限制' : item.audit_status === 'approved' && item.listed ? '已上架' : ({ draft: '草稿', pending: '待审核', rejected: '未通过', approved: '未上架' } as Record<string, string>)[item.audit_status] || '未上架'}</span>
        {item.target_type !== 'series_episode' && <label className="market-ops-content-pick"><input type="checkbox" aria-label={`选择${item.title}`} checked={selected.includes(metricKey(item))} onChange={event => setSelected(value => event.target.checked ? [...value, metricKey(item)] : value.filter(key => key !== metricKey(item)))} /></label>}
        {item.asset_id && <button type="button" className="market-ops-content-play" aria-label={`预览${item.title}`} onClick={() => setPreviewing(item)}><Play size={18} /></button>}
      </div>
      <div className="market-ops-content-body"><div className="market-ops-content-meta"><span>{item.category || targetNames[item.target_type]} · #{item.target_id}</span><div className="market-ops-curation-tags">{item.is_pinned && <span>置顶</span>}{item.is_featured && <span>精选</span>}</div></div><h3 title={item.title}>{item.title}</h3>
        {item.series_title && <p className="market-ops-content-series" title={item.series_title}>{item.series_title} · 第 {item.episode_no} 集</p>}
        <p className="market-ops-content-author"><span>{(item.author || '创作者').slice(0, 1)}</span>{item.author || '创作者'}<small>#{item.owner_id}</small></p>
        <div className="market-ops-content-counts">{([[ 'like_count', Heart ], [ 'favorite_count', Bookmark ], [ 'share_count', Share2 ]] as const).map(([key, Icon]) => <div key={key}><span><Icon size={14} />{labels[key]}</span><strong>{number(item.display[key])}</strong><small>真实 {number(item.real[key])}</small><small>初始 {number(item.initial[key])}</small></div>)}</div>
        <div className="market-ops-content-actions">{item.target_type !== 'series_episode' && <CurationControls split targetType={item.target_type} targetId={item.target_id} isFeatured={item.is_featured} isPinned={item.is_pinned} onSaved={() => setRefresh(value => value + 1)} />}
          {item.target_type !== 'series' && <button type="button" onClick={() => setEditing(item)}><SlidersHorizontal size={14} />修改数量</button>}<button type="button" onClick={() => setHistory(item)}><History size={14} />数量记录</button>
        </div>{item.target_type === 'series' && <small className="market-ops-content-note">系列仅展示真实数量；分集数量可独立调整。</small>}{item.target_type === 'series_episode' && <small className="market-ops-content-note">加精与置顶在所属系列设置，分集按集号展示。</small>}
      </div>
    </article>)}</div> : <div className="market-ops-empty"><Film size={28} /><h3>{error ? '作品暂时无法读取' : '暂无匹配作品'}</h3><p>{error ? '请刷新重试。' : '试试其他作品名称或运营状态。'}</p></div>}
    {listing && <PaginationBar page={page} pageSize={listing.page_size} total={listing.total} onPageChange={setPage} />}
    {editing && editing.target_type !== 'series' && <MetricsEditor key={`${editing.target_type}-${editing.target_id}`} item={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setRefresh(v => v + 1) }} />}
    {history && <MetricsHistory item={history} onClose={() => setHistory(null)} />}
    {previewing && <OperationPreview item={previewing} onClose={() => setPreviewing(null)} />}
    {showEvents && <CurationHistoryPanel revision={refresh + revision} />}
  </section>
}

function OperationCover({ assetId }: { assetId: number | null }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let active = true; setUrl('')
    if (assetId) assetUrl(assetId, 'cover').then(value => { if (active) setUrl(value) }).catch(() => undefined)
    return () => { active = false }
  }, [assetId])
  return url ? <img src={url} alt="作品封面" loading="lazy" onError={() => setUrl('')} /> : <span className="market-ops-cover-empty"><Film size={36} /><small>暂无封面</small></span>
}

function OperationPreview({ item, onClose }: { item: Metric; onClose: () => void }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    if (item.asset_id) assetUrl(item.asset_id, 'original').then(value => { if (active) setUrl(value) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [item.asset_id])
  return <AdminModal open onOpenChange={open => { if (!open) onClose() }} title="作品预览" subtitle={item.title} size="xl">{error ? <p role="alert">{error}</p> : url ? <video src={url} controls className="market-ops-content-video" /> : <p role="status">正在读取视频…</p>}</AdminModal>
}

function MetricsEditor({ item, onClose, onSaved }: { item: Metric; onClose: () => void; onSaved: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [clear, setClear] = useState(false)
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget)
    setError('')
    try {
      const reason = String(form.get('reason') || '').trim()
      if (!reason) throw new Error('请填写调整原因')
      const values = clear ? {} : displayMetricsInput(Object.fromEntries(form), item.real)
      setBusy(true)
      await request(`${base}/metrics/${item.target_type}/${item.target_id}`, 'PATCH', { ...values, version: item.version, reason, clear })
      onSaved()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <AdminModal className="market-ops-operation-modal" open onOpenChange={open => { if (!open && !busy) onClose() }} title="调整互动展示数量" subtitle={item.title} size="lg"><form className="market-ops-support market-ops-modal-form" onSubmit={save}>
    <p>真实数量不能改写。服务端将根据提交时的真实统计计算初始值；数据有变化时请重新加载后提交。</p>
    <label><input type="checkbox" checked={clear} disabled={busy} onChange={event => setClear(event.target.checked)} /> 清零全部初始值，只展示真实数量</label>
    {Object.entries(labels).map(([key, label]) => <label key={key}>{label}展示数量（真实 {number(item.real[key as keyof Counts])}）<input name={key} inputMode="numeric" required={!clear} defaultValue={item.display[key as keyof Counts]} disabled={busy || clear} /></label>)}
    <label>调整原因<textarea name="reason" required maxLength={300} disabled={busy} /></label><div className="flex gap-3"><button type="submit" disabled={busy}>{busy ? '正在保存…' : '保存调整'}</button><button type="button" disabled={busy} onClick={onClose}>取消</button></div>{error && <p role="alert">{error}</p>}
  </form></AdminModal>
}

function MetricsHistory({ item, onClose }: { item: Metric; onClose: () => void }) {
  type Audit = { id: number; operator_id: number | null; action: string; reason: string; before: Record<string, unknown>; after: Record<string, unknown>; created_at: string }
  const [page, setPage] = useState(1)
  const [data, setData] = useState<{ items: Audit[]; total: number } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true; setData(null); setError('')
    request<{ items: Audit[]; total: number }>(`${base}/metrics/events?${new URLSearchParams({ target_type: item.target_type, target_id: String(item.target_id), page: String(page), page_size: '20' })}`)
      .then(value => { if (active) setData(value) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [item.target_type, item.target_id, page])
  const snapshot = (value: Record<string, unknown>) => Object.entries(labels).map(([key, label]) => `${label} ${typeof value[key] === 'number' ? number(value[key]) : '—'}`).join(' / ')
  return <AdminModal className="market-ops-operation-modal" open onOpenChange={open => { if (!open) onClose() }} title="互动数量操作历史" subtitle={item.title} size="xl">
    {error ? <p role="alert">{error}</p> : !data ? <p role="status">正在读取操作历史…</p> : data.items.length ? <div className="grid gap-3">{data.items.map(row => <article className="market-ops-feedback" key={row.id}><strong>{({ initialize: '初始化', adjust: '调整初始值', clear: '清零初始值' } as Record<string, string>)[row.action] || row.action}</strong><p>操作人：{row.operator_id ? `管理员 #${row.operator_id}` : '系统自动处理'} · {new Date(row.created_at).toLocaleString('zh-CN')}</p><p>原因：{row.reason}</p><p>修改前：{snapshot(row.before)}</p><p>修改后：{snapshot(row.after)}</p></article>)}</div> : <p>暂无操作历史</p>}
    {data && <PaginationBar page={page} pageSize={20} total={data.total} onPageChange={setPage} />}
  </AdminModal>
}
