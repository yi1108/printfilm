import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { Project } from '../api'
import BillingErrorNotice from '../components/billing/BillingErrorNotice'
import AppShell from '../components/layout/AppShell'
import PillTabs from '../components/ui/PillTabs'
import Pagination from '../components/ui/Pagination'
import StatCard from '../components/ui/StatCard'
import {
  IconClapper,
  IconClock,
  IconCopy,
  IconDownload,
  IconEdit,
  IconEye,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconSend,
  IconTrash,
} from '../components/ui/Icons'
import { dialog } from '../lib/dialog'
import {
  downloadSingleVideo,
  triggerBlobDownload,
  zipVideosClient,
} from '../lib/clientDownload'
import { hasActiveTasks, isRunning, STATUS_CN, statusTone } from '../lib/status'
import { pageCountOf } from '../lib/pagination'
import { formatDateTime, useI18n } from '../i18n'

type HistoryItem = Omit<Project, 'shots'> & {
  published?: boolean
  final_video_url?: string | null
  error_msg?: string | null
  pipeline_mode?: string
  output_ratio?: string
  updated_at?: string
}

type HistoryTab = 'all' | 'draft' | 'running' | 'done' | 'published'

const PAGE_SIZE_DEFAULT = 8

const TAB_STATUS: Record<HistoryTab, 'all' | 'draft' | 'running' | 'done' | 'published'> = {
  all: 'all',
  draft: 'draft',
  running: 'running',
  done: 'done',
  published: 'published',
}

const HISTORY_TABS: HistoryTab[] = ['all', 'draft', 'running', 'done', 'published']

function canDownload(p: HistoryItem) {
  return p.status === 'DONE' && Boolean(p.final_video_url)
}

function statusBadgeClass(status: string) {
  const tone = statusTone(status)
  if (tone === 'ok') return 'ok'
  if (tone === 'run') return 'run'
  if (tone === 'bad') return 'bad'
  if (status === 'DRAFT') return 'draft'
  return ''
}

export default function HistoryPage() {
  const nav = useNavigate()
  const { t, m, locale } = useI18n()
  /*
   * items 当前页项目
   * total 筛选后总数（后端）
   * stats 顶部统计
   * templates 模板名映射
   * error 错误文案
   * loading 加载中
   * busyId 单条操作中的项目 id
   * packing 打包中
   * packProgress 打包进度
   * selected 勾选 id
   * tab 状态 Tab
   * typeMode 类型筛选（pipeline_mode）
   * q 搜索框
   * debouncedQ 防抖后的搜索词
   * page 页码
   * pageSize 每页条数
   * preview 预览弹层
   */
  const [items, setItems] = useState<HistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState({ total: 0, generating: 0, done: 0, published: 0 })
  const [templates, setTemplates] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [packing, setPacking] = useState(false)
  const [packProgress, setPackProgress] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [tab, setTab] = useState<HistoryTab>('all')
  const [typeMode, setTypeMode] = useState<'' | 'full' | 'image_text'>('')
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT)
  const [preview, setPreview] = useState<{
    url: string
    title: string
    projectId: number
  } | null>(null)

  const hasRunning = useMemo(
    () =>
      items.some((p) => (isRunning(p.status) && p.progress < 100) || hasActiveTasks(p)) ||
      stats.generating > 0,
    [items, stats.generating],
  )

  // 搜索防抖
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(q.trim()), 300)
    return () => window.clearTimeout(t)
  }, [q])

  async function load() {
    try {
      const res = await api.listProjects({
        page,
        page_size: pageSize,
        status: TAB_STATUS[tab] || 'all',
        q: debouncedQ,
        pipeline_mode: typeMode,
      })
      setItems(res.items as HistoryItem[])
      setTotal(res.meta.total)
      setStats(res.stats)
      setError('')
      setSelected((prev) => {
        const ids = new Set(res.items.map((x) => x.id))
        return new Set([...prev].filter((id) => ids.has(id)))
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.loadFailed'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!localStorage.getItem('token')) {
      nav('/auth')
      return
    }
    api.templates().then((list) => {
      const map: Record<string, string> = {}
      for (const t of list) map[t.id] = t.name
      setTemplates(map)
    })
  }, [nav])

  useEffect(() => {
    setLoading(true)
    load().catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional reload keys
  }, [page, pageSize, tab, typeMode, debouncedQ])

  useEffect(() => {
    if (!hasRunning) return
    const timer = setInterval(() => {
      load().catch(() => undefined)
    }, 2000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasRunning, page, pageSize, tab, typeMode, debouncedQ])

  useEffect(() => {
    setPage(1)
  }, [tab, debouncedQ, typeMode, pageSize])

  const pageCount = pageCountOf(total, pageSize)
  const pageItems = items

  // 筛选后若当前页超出范围则回退
  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const downloadable = useMemo(() => items.filter(canDownload), [items])
  const selectedDownloadable = useMemo(
    () => downloadable.filter((p) => selected.has(p.id)),
    [downloadable, selected],
  )

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function remove(id: number) {
    const ok = await dialog.confirm({
      title: t('history.deleteTitle'),
      message: t('history.deleteMessage'),
      confirmText: t('common.delete'),
      cancelText: t('common.cancel'),
      tone: 'danger',
    })
    if (!ok) return
    setBusyId(id)
    try {
      await api.deleteProject(id)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('history.deleteFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function downloadOne(p: HistoryItem) {
    if (!canDownload(p) || !p.final_video_url) return
    setBusyId(p.id)
    setError('')
    try {
      await downloadSingleVideo({
        url: api.assetUrl(p.final_video_url, p.updated_at),
        title: p.title,
        projectId: p.id,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('history.downloadFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function downloadPreview() {
    if (!preview) return
    setBusyId(preview.projectId)
    setError('')
    try {
      await downloadSingleVideo({
        url: preview.url,
        title: preview.title,
        projectId: preview.projectId,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('history.downloadFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function packSelected() {
    if (!selectedDownloadable.length) return
    setPacking(true)
    setPackProgress(`0/${selectedDownloadable.length}`)
    setError('')
    try {
      const { blob, filename } = await zipVideosClient(
        selectedDownloadable.map((p) => ({
          id: p.id,
          title: p.title,
          url: api.assetUrl(p.final_video_url!, p.updated_at),
        })),
        (done, total) => setPackProgress(`${done}/${total}`),
      )
      triggerBlobDownload(blob, filename)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('history.packFailed'))
    } finally {
      setPacking(false)
      setPackProgress('')
    }
  }

  function continueEdit(p: HistoryItem) {
    if (p.status === 'DRAFT') nav(`/studio/${p.id}/style`)
    else nav(`/studio/${p.id}`)
  }

  return (
    <AppShell active="kepu" wide>
      <div className="pf-history-head">
        <div>
          <h1>{t('history.title')}</h1>
          <p>{t('history.lead')}</p>
        </div>
        <div className="pf-history-head-actions">
          <button type="button" className="pf-btn pf-btn-lime pf-btn-icon" onClick={() => nav('/studio/new')}>
            <IconPlus size={16} />
            {t('history.newKepu')}
          </button>
          <Link to="/drama" className="pf-btn pf-btn-ghost pf-btn-sm">
            {t('history.goDrama')}
          </Link>
        </div>
      </div>

      <div className="pf-stats">
        <StatCard
          label={t('history.statTotal')}
          value={stats.total}
          trend="—"
          icon={<IconClapper size={18} />}
        />
        <StatCard
          label={t('history.statRunning')}
          value={stats.generating}
          trend={stats.generating ? t('history.runningNow') : t('history.noTask')}
          icon={<IconRefresh size={18} />}
        />
        <StatCard
          label={t('history.statDone')}
          value={stats.done}
          trend="—"
          icon={<IconSend size={18} />}
        />
        <StatCard
          label={t('history.statDuration')}
          value="—"
          trend={t('history.durationSoon')}
          icon={<IconClock size={18} />}
        />
      </div>

      <div className="pf-history-layout">
        <section className="pf-history-main">
          <div className="pf-history-filters">
            <PillTabs
              items={HISTORY_TABS.map((id) => m.history.tabs[id])}
              value={m.history.tabs[tab]}
              onChange={(label) => {
                const next = HISTORY_TABS.find((id) => m.history.tabs[id] === label)
                if (next) setTab(next)
              }}
              ariaLabel={t('history.statusAria')}
            />
            <div className="pf-history-filter-right">
              <select
                className="pf-type-select"
                value={typeMode}
                aria-label={t('history.typeAria')}
                onChange={(e) => setTypeMode(e.target.value as '' | 'full' | 'image_text')}
              >
                <option value="">{t('history.typeAll')}</option>
                <option value="full">{t('history.typeFull')}</option>
                <option value="image_text">{t('history.typeImageText')}</option>
              </select>
              <label className="pf-search-field">
                <IconSearch size={15} />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder={t('history.searchPlaceholder')}
                />
              </label>
            </div>
          </div>

          <div className="pf-history-batch">
            <button
              type="button"
              className="pf-btn-text"
              disabled={!selectedDownloadable.length || packing}
              onClick={packSelected}
            >
              <IconDownload size={15} />
              {packing
                ? t('history.packing', { progress: packProgress })
                : t('history.packDownload', { count: selectedDownloadable.length })}
            </button>
          </div>

          {error ? <BillingErrorNotice message={error} /> : null}
          {loading ? <p className="pf-muted">{t('common.loading')}</p> : null}
          {!loading && total === 0 ? (
            <div className="pf-history-empty">{t('history.empty')}</div>
          ) : null}

          <div className="pf-project-list">
            {pageItems.map((p) => {
              const badge = statusBadgeClass(p.status)
              const ratio =
                p.output_ratio || (p.pipeline_mode === 'image_text' ? '9:16' : '16:9')
              const tplName = templates[p.template_id] || p.template_id
              return (
                <article key={p.id} className="pf-project-card">
                  <label className="pf-project-check">
                    <input
                      type="checkbox"
                      checked={selected.has(p.id)}
                      disabled={!canDownload(p)}
                      onChange={() => toggle(p.id)}
                    />
                  </label>
                  <button
                    type="button"
                    className="pf-project-thumb"
                    onClick={() => continueEdit(p)}
                  >
                    {p.cover_url ? (
                      <img src={api.assetUrl(p.cover_url, p.updated_at)} alt="" />
                    ) : (
                      <div className="ph">{t('history.noCover')}</div>
                    )}
                    {isRunning(p.status) ? (
                      <span className="pf-thumb-progress">{p.progress}%</span>
                    ) : null}
                  </button>
                  <div className="pf-project-info">
                    <h3>
                      {p.title}
                      {p.published ? <span className="pf-badge ok" style={{ marginLeft: 8 }}>{t('history.published')}</span> : null}
                    </h3>
                    <div className="pf-project-meta">
                      <span className={`pf-badge ${badge}`}>
                        {STATUS_CN[p.status] || p.status}
                      </span>
                      <span className="pf-muted">
                        {t('history.templateMeta', {
                          name: tplName,
                          when: formatDateTime(p.updated_at || p.created_at, locale),
                        })}
                      </span>
                    </div>
                    {isRunning(p.status) ? (
                      <div className="pf-inline-meter">
                        <i style={{ width: `${Math.min(100, p.progress)}%` }} />
                      </div>
                    ) : null}
                    {p.error_msg ? <p className="pf-error pf-project-err">{p.error_msg}</p> : null}
                  </div>
                  <div className="pf-project-ratio">{ratio}</div>
                  <div className="pf-project-actions">
                    <button type="button" className="pf-btn-text" onClick={() => continueEdit(p)}>
                      <IconEdit size={14} />
                      {t('history.continueEdit')}
                    </button>
                    <button
                      type="button"
                      className="pf-btn-text"
                      disabled={!p.final_video_url}
                      onClick={() =>
                        p.final_video_url &&
                        setPreview({
                          url: api.assetUrl(p.final_video_url, p.updated_at),
                          title: p.title,
                          projectId: p.id,
                        })
                      }
                    >
                      <IconEye size={14} />
                      {t('common.preview')}
                    </button>
                    <button
                      type="button"
                      className="pf-btn-text"
                      disabled={!canDownload(p) || busyId === p.id || packing}
                      onClick={() => downloadOne(p)}
                    >
                      <IconDownload size={14} />
                      {busyId === p.id ? t('common.downloading') : t('common.download')}
                    </button>
                    <button type="button" className="pf-btn-text" disabled title={t('common.comingSoon')}>
                      <IconCopy size={14} />
                      {t('common.copy')}
                    </button>
                    <button
                      type="button"
                      className="pf-icon-btn danger"
                      disabled={busyId === p.id}
                      title={t('common.delete')}
                      onClick={() => remove(p.id)}
                    >
                      <IconTrash size={16} />
                    </button>
                  </div>
                </article>
              )
            })}
          </div>

          {total > 0 ? (
            <Pagination
              page={page}
              pageCount={pageCount}
              total={total}
              pageSize={pageSize}
              onPageSizeChange={(size) => {
                setPageSize(size)
                setPage(1)
              }}
              onChange={setPage}
              ariaLabel={t('history.pagination')}
            />
          ) : null}
        </section>
      </div>

      {preview ? (
        <div className="modal-backdrop" onClick={() => setPreview(null)}>
          <div className="modal preview-modal" onClick={(e) => e.stopPropagation()}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: '0.75rem',
                alignItems: 'center',
              }}
            >
              <h3 style={{ margin: 0 }}>{preview.title}</h3>
              <div style={{ display: 'flex', gap: '0.4rem' }}>
                <button
                  type="button"
                  className="pf-btn pf-btn-ghost pf-btn-sm"
                  disabled={busyId === preview.projectId}
                  onClick={downloadPreview}
                >
                  <IconDownload size={14} />
                  {busyId === preview.projectId ? t('common.downloading') : t('common.download')}
                </button>
                <button
                  type="button"
                  className="pf-btn pf-btn-ghost pf-btn-sm"
                  onClick={() => setPreview(null)}
                >
                  {t('common.close')}
                </button>
              </div>
            </div>
            <video className="preview-media" src={preview.url} controls autoPlay />
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}
