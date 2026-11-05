import { points } from '../lib/points'
import { useEffect, useState, useSyncExternalStore } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, ArrowUpRight, CheckCircle2, Clock3, Download, Eye, FileText, ListChecks, ListFilter, Loader2, Plus, RefreshCw, Search, X } from 'lucide-react'
import { resolveToolMediaUrl, type ToolRunRecord } from '../api/tools'
import { listGenerationTasks } from '../api/generationTasks'
import GenerationLayout from '../components/tools/GenerationLayout'
import GenerationDateRange from '../components/tools/GenerationDateRange'
import GenerationSelect from '../components/tools/GenerationSelect'
import { AssetDetailDialog } from '../components/assets/AssetDetailDialog'
import { useToolRunDetail } from '../hooks/useToolRunDetail'
import { mediaIcons, useGenerationText } from '../lib/generationMedia'
import { formatGenerationErrorMessage } from '../lib/generationError'
import { generationBillingState, generationRecordKey, generationTaskKind, generationTaskKinds as taskKinds, type GenerationTaskKind as TaskKind } from '../lib/generationTaskHistory'
import { subscribeWorkspace, workspaceScope } from '../features/teams/workspaceScope'
import Pagination from '../components/ui/Pagination'
import { fetchMediaBlob, triggerBlobDownload } from '../lib/clientDownload'

const taskIcons = { ...mediaIcons, all: ListChecks, text: FileText }
const workspaceSnapshot = () => workspaceScope.epoch

export default function GenerationTasksPage() {
  if (!localStorage.getItem('token')) return <Navigate to="/auth?next=/tasks" replace />
  return <TaskHistory />
}

function TaskHistory() {
  const workspaceEpoch = useSyncExternalStore(subscribeWorkspace, workspaceSnapshot)
  return <TaskHistoryContent key={workspaceEpoch} />
}

function TaskHistoryContent() {
  const text = useGenerationText()
  const [params, setParams] = useSearchParams()
  const kind = generationTaskKind(params.get('kind'))
  const status = ['processing', 'succeeded', 'failed', 'cancelled'].includes(params.get('status') || '') ? params.get('status')! : ''
  const taskId = params.get('task_id') || ''
  const [query, setQuery] = useState(taskId)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(8)
  const [items, setItems] = useState<ToolRunRecord[]>([])
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const { detail, asset: detailAsset, error: detailError, resultIndex, selectResult, openDetail, closeDetail } = useToolRunDetail()
  const [downloading, setDownloading] = useState<string | null>(null)
  const Icon = taskIcons[kind]
  const createPath = kind === 'all' ? '/' : `/tools/${kind}`
  const labels: Record<string, string> = {
    all: text('全部', 'All'), processing: text('处理中', 'Processing'), succeeded: text('已完成', 'Completed'),
    failed: text('失败', 'Failed'), cancelled: text('已取消', 'Cancelled'), queued: text('排队中', 'Queued'), running: text('处理中', 'Processing'),
  }
  const kindLabels: Record<TaskKind, string> = {
    all: text('全部任务', 'All tasks'), video: text('视频任务', 'Video tasks'), image: text('图片任务', 'Image tasks'),
    audio: text('音频任务', 'Audio tasks'),
  }
  const billingLabels = {
    hidden: text('费用不可见', 'Cost hidden'), pending: text('待结算', 'Pending charge'), settled: text('已结算', 'Charged'),
    refunded: text('已退还', 'Refunded'), free: text('无需结算', 'No charge'), not_charged: text('未收费', 'Not charged'),
  }
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    setParams(next); setPage(1)
  }
  useEffect(() => {
    const requestedKind = params.get('kind')
    if (!requestedKind || requestedKind === kind) return
    const next = new URLSearchParams(params)
    next.delete('kind')
    setParams(next, { replace: true })
  }, [params, setParams, kind])
  useEffect(() => { setQuery(taskId) }, [taskId])
  useEffect(() => {
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    setLoading(true)
    async function refresh() {
      if (from && to && from > to) { setError(text('开始日期不能晚于结束日期', 'Start date must precede end date')); setLoading(false); return }
      try {
        const data = await listGenerationTasks(page, pageSize, { kind: kind === 'all' ? undefined : kind, status, task_id: taskId,
          created_from: from ? new Date(`${from}T00:00:00`).toISOString() : '',
          created_to: to ? new Date(`${to}T23:59:59.999`).toISOString() : '' })
        if (disposed) return
        setItems(data.items); setTotal(data.total); setCounts(data.counts || {}); setError('')
        if (page > Math.max(1, Math.ceil(data.total / pageSize))) setPage(Math.max(1, Math.ceil(data.total / pageSize)))
        timer = setTimeout(refresh, 5000)
      } catch (err) {
        if (!disposed) { setError(err instanceof Error ? err.message : text('加载失败', 'Loading failed')); timer = setTimeout(refresh, 10000) }
      } finally { if (!disposed) setLoading(false) }
    }
    void refresh()
    return () => { disposed = true; clearTimeout(timer) }
  }, [kind, status, taskId, from, to, page, pageSize, revision, text])

  async function download(item: ToolRunRecord, url = item.urls[0]) {
    setDownloading(generationRecordKey(item))
    try {
      const blob = item.kind === 'text' ? new Blob([item.text_content || ''], { type: 'text/plain;charset=utf-8' }) : await fetchMediaBlob(resolveToolMediaUrl(url))
      triggerBlobDownload(blob, `printfilm_${item.kind}_${item.id}.${item.kind === 'video' ? 'mp4' : item.kind === 'audio' ? 'mp3' : item.kind === 'text' ? 'txt' : 'png'}`)
    } catch (err) { setError(err instanceof Error ? err.message : text('下载失败', 'Download failed')) }
    finally { setDownloading(null) }
  }
  function when(value?: string | null) {
    return value ? new Date(value).toLocaleString(text('zh-CN', 'en-US'), { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'
  }
  function elapsed(item: ToolRunRecord) {
    if (!item.started_at || !item.finished_at) return '—'
    const seconds = Math.max(0, Math.round((Date.parse(item.finished_at) - Date.parse(item.started_at)) / 1000))
    return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  }
  function errorSummary(error: string) {
    const friendlyMessage = formatGenerationErrorMessage(error)
    if (friendlyMessage !== error) return friendlyMessage
    if (/sensitive|policyviolation|content.?filter|审核/i.test(error)) return text('内容未通过审核，请调整描述后重试', 'Content review failed. Try adjusting your prompt.')
    if (/余额不足|insufficient.*balance/i.test(error)) return text('余额不足，请充值后重试', 'Insufficient balance. Please top up.')
    if (/timeout|timed out|超时/i.test(error)) return text('生成超时，请稍后重试', 'Generation timed out. Please try again.')
    return error.length > 90 || /^[{[]/.test(error) ? text('生成未完成，点击查看详情', 'Generation failed. View details for more information.') : error
  }
  const hasFilters = Boolean(status || taskId || from || to)
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const StatusIcon = { succeeded: CheckCircle2, failed: AlertCircle, running: Clock3, queued: Clock3, cancelled: X }
  return <GenerationLayout tasks>
    <header className="gen-tasks-heading">
      <div><div className="gen-section-eyebrow">{text('创作管理', 'CREATION LIBRARY')}</div><h1>{text('我的任务', 'My tasks')}<span className="gen-heading-dot" /></h1><p>{text('每一次灵感，都有迹可循。', 'Every idea, all in one place.')}</p></div>
      <div className="gen-task-actions"><button className="gen-secondary" type="button" onClick={() => setRevision(value => value + 1)} disabled={loading}><RefreshCw size={16} className={loading ? 'gen-spin' : ''} />{text('刷新', 'Refresh')}</button><Link className="gen-primary" to={createPath}><Plus size={18} />{text('去创作', 'Create something')}</Link></div>
    </header>
    <div className="gen-library">
      <div className="gen-task-tabs"><div role="tablist" aria-label={text('任务类型', 'Media type')}>
        {taskKinds.map((value, index) => {
          const TabIcon = taskIcons[value]
          return <button type="button" key={value} id={`gen-tab-${value}`} role="tab" tabIndex={value === kind ? 0 : -1}
            aria-selected={value === kind} className={value === kind ? 'is-active' : ''} onClick={() => filter('kind', value === 'all' ? '' : value)}
            onKeyDown={event => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
              event.preventDefault()
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? taskKinds.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : taskKinds.length - 1)) % taskKinds.length
              filter('kind', taskKinds[next] === 'all' ? '' : taskKinds[next]); document.getElementById(`gen-tab-${taskKinds[next]}`)?.focus()
            }}><TabIcon size={18} />{kindLabels[value]}</button>
        })}
      </div><span className="gen-auto-sync"><i />{text('自动更新', 'Auto-updating')}</span></div>
      <div className="gen-task-filters">
        <div className="gen-status-tabs" aria-label={text('任务状态', 'Task status')}>
          {['all', 'processing', 'succeeded', 'failed', 'cancelled'].map(value => <button type="button" key={value} aria-pressed={(status || 'all') === value} className={(status || 'all') === value ? 'is-active' : ''} onClick={() => filter('status', value === 'all' ? '' : value)}>{labels[value]}<span>{counts[value] || 0}</span></button>)}
        </div>
        <div className="gen-filter-inputs">
          <form className={`gen-search ${taskId ? 'has-value' : ''}`} role="search" onSubmit={event => { event.preventDefault(); filter('task_id', query.trim()) }}>
            <Search size={18} aria-hidden /><input value={query} onChange={event => setQuery(event.target.value)} placeholder={text('搜索任务 ID 或上游 ID', 'Search task or upstream ID')} aria-label={text('搜索任务 ID', 'Search task ID')} />
            {query && <button className="gen-search-clear" type="button" aria-label={text('清除搜索', 'Clear search')} onClick={() => { setQuery(''); filter('task_id', '') }}><X size={14} /></button>}
            <button type="submit" className="gen-search-submit" aria-label={text('搜索', 'Search')}><ArrowUpRight size={17} /></button>
          </form>
          <GenerationDateRange from={from} to={to} onChange={(start, end) => { setFrom(start); setTo(end); setPage(1) }} />
          {hasFilters && <button type="button" className="gen-reset-filters" onClick={() => { setFrom(''); setTo(''); setQuery(''); setParams({ kind }); setPage(1) }}>{text('重置筛选', 'Reset filters')}</button>}
        </div>
      </div>
      {error && <p className="gen-inline-error" role="alert">{error}</p>}
      <div className="gen-list-heading" aria-hidden><span><ListFilter size={14} />{text('生成内容', 'Creation')}</span><span>{text('任务状态', 'Status')}</span><span>{text('费用', 'Cost')}</span><span>{text('创建时间', 'Created')}</span><span>{text('操作', 'Actions')}</span></div>
      <section className="gen-task-list" aria-label={text('生成任务记录', 'Generation history')} aria-busy={loading}>
      {loading && !items.length ? <div className="gen-empty"><Loader2 className="gen-spin" size={28} />{text('加载任务中…', 'Loading tasks…')}</div> : !items.length ? <div className="gen-empty"><Icon size={36} /><strong>{text('暂无符合条件的任务', 'No matching tasks')}</strong><p>{text('调整筛选条件，或开始一次新的创作。', 'Adjust your filters or create something new.')}</p><Link to={createPath}>{text('开始创作', 'Start creating')} →</Link></div> : items.map(item => {
        const RowStatusIcon = StatusIcon[item.status as keyof typeof StatusIcon] || Clock3
        const RowIcon = taskIcons[item.kind as TaskKind] || FileText
        const recordKey = generationRecordKey(item)
        const billingState = generationBillingState(item)
        const ratio = typeof (item.params?.aspect_ratio ?? item.params?.ratio) === 'string' ? String(item.params?.aspect_ratio ?? item.params?.ratio) : ''
        const shortVideoImage = item.domain === 'kepu' && item.kind === 'image'
        const title = item.prompt || (shortVideoImage ? text('AI短视频生图', 'AI short video images') : text('生成任务', 'Generation task'))
        const formatLabel = item.kind === 'video' ? 'MP4' : item.kind === 'audio' ? 'MP3' : item.kind === 'text' ? text('文字', 'Text') : text('图片', 'Image')
        return <article className={`gen-task-row ${item.status === 'failed' ? 'has-error' : ''}`} key={recordKey}>
        <button className="gen-task-cover" type="button" onClick={() => openDetail(item)} aria-label={text('查看生成结果', 'View result')}>
          {item.kind === 'image' && (item.preview_url || item.urls[0]) ? <img src={resolveToolMediaUrl(item.preview_url || item.urls[0])} alt="" /> : item.kind === 'video' && item.preview_url ? <img src={resolveToolMediaUrl(item.preview_url)} alt="" /> : item.kind === 'video' && item.urls[0] ? <video src={resolveToolMediaUrl(item.urls[0])} preload="metadata" muted /> : <RowIcon size={28} />}
          <span className="gen-cover-overlay"><Eye size={18} /></span>
        </button>
        <div className="gen-task-description"><button type="button" className="gen-task-title" onClick={() => openDetail(item)} title={title}>{title}</button><div className="gen-task-metadata"><span className="gen-task-tag">{kindLabels[item.kind as TaskKind] || 'AI'}</span>{shortVideoImage && <span className="gen-task-tag">{text('AI短视频', 'AI short video')}</span>}{item.kind === 'image' && item.urls.length > 1 && <span className="gen-task-tag">{text(`${item.urls.length} 张图片`, `${item.urls.length} images`)}</span>}{ratio && <span className="gen-task-tag">{ratio}</span>}</div>{item.error && <button type="button" className="gen-task-error" onClick={() => openDetail(item)} title={formatGenerationErrorMessage(item.error)}><AlertCircle size={12} /><span>{errorSummary(item.error)}</span><ArrowUpRight size={12} /></button>}</div>
        <div className="gen-task-state"><span className={`gen-state is-${item.status}`}><RowStatusIcon size={13} />{labels[item.status] || item.status}</span><small>{formatLabel}</small></div>
        <div className="gen-task-cost"><strong>{billingState === 'hidden' ? '—' : points(item.billing_charged_fen || 0)}</strong><small>{billingLabels[billingState]}</small></div>
        <div className="gen-task-time"><span>{when(item.created_at)}</span><small>{text('耗时', 'Duration')} {elapsed(item)}</small></div>
        <div className="gen-row-actions">{item.status === 'succeeded' && (item.kind === 'text' ? item.text_content : item.urls[0]) && <button type="button" className="gen-secondary" disabled={downloading === recordKey} onClick={() => void download(item)}>{downloading === recordKey ? <Loader2 size={15} className="gen-spin" /> : <Download size={15} />}{text('下载', 'Download')}</button>}<button type="button" className="gen-icon-button" onClick={() => openDetail(item)} aria-label={text('查看任务详情', 'Task details')}><Eye size={18} /></button></div>
      </article>})}
    </section>
    <footer className="gen-task-pagination"><span>{text('共', 'Total')} <strong>{total}</strong> {text('条记录', 'creations')}<span className="gen-pagination-divider" />{text(`第 ${page} / ${pageCount} 页`, `Page ${page} of ${pageCount}`)}</span>
      <div><Pagination page={page} pageCount={pageCount} onChange={setPage} showSummary={false} /><GenerationSelect compact label={text('每页条数', 'Items per page')} value={String(pageSize)} options={[8, 16, 24, 50].map(value => ({ value: String(value), label: text(`${value} 条 / 页`, `${value} / page`) }))} onChange={value => { setPageSize(Number(value)); setPage(1) }} /></div>
    </footer>
    </div>
    {detail && detailAsset && <AssetDetailDialog key={generationRecordKey(detail)} asset={detailAsset} onClose={closeDetail}
      notice={<section className="pf-asset-detail-prompt"><div className="pf-asset-detail-text">
        <p role="status">{labels[detail.status] || detail.status}{(detail.status === 'queued' || detail.status === 'running') && text('，结果会自动更新。', '. Results will update automatically.')}</p>
        {(detail.error || detailError) && <p role="alert">{formatGenerationErrorMessage(detail.error || detailError)}</p>}
      </div></section>}
      actions={detail.urls.length > 1 && <div className="pf-asset-detail-utilities" role="group" aria-label={text('生成结果', 'Generation results')}>
        {detail.urls.map((url, index) => <button type="button" key={url} className="pf-btn pf-btn-sm" aria-pressed={resultIndex === index} onClick={() => selectResult(index)}>{text(`结果 ${index + 1}`, `Result ${index + 1}`)}</button>)}
      </div>}>
    </AssetDetailDialog>}
  </GenerationLayout>
}
