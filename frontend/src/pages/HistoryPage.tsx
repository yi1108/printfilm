import { marketText as mt } from '../features/marketplace/translate'
import { useMarketplaceLocale } from '../features/marketplace/useMarketplaceLocale'
import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { Project } from '../api'
import BillingErrorNotice from '../components/billing/BillingErrorNotice'
import AppShell from '../components/layout/AppShell'
import PillTabs from '../components/ui/PillTabs'
import Pagination from '../components/ui/Pagination'
import { ProjectCard, ProjectGrid } from '../components/projects/ProjectCard'
import {
  IconClapper,
  IconDownload,
  IconEdit,
  IconEye,
  IconPlus,
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
import { hasActiveTasks, isRunning, STATUS_CN } from '../lib/status'
import { pageCountOf } from '../lib/pagination'
import { SHORT_VIDEO_CREATE_PATH, shortVideoProjectPath } from '../lib/shortVideoRoutes'
import { withReturn } from '../features/marketplace/ui'
import { formatGenerationErrorMessage } from '../lib/generationError'
import { formatDateTime, useI18n } from '../i18n'
import './drama/project-list.css'
import './shortVideoList.css'

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

export default function HistoryPage() {
  useMarketplaceLocale()
  const nav = useNavigate()
  const location = useLocation()
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
  const pageSize = PAGE_SIZE_DEFAULT
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
    }).catch(() => undefined)
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
    nav(shortVideoProjectPath(p))
  }

  return (
    <AppShell active="kepu">
      <div className="pf-project-list-page pf-short-video-list-page">
        <header className="pf-project-page-header">
          <div>
            <span className="pf-project-page-eyebrow">SHORT VIDEO STUDIO</span>
            <h1>{t('history.title')}</h1>
            <p>{t('history.lead')}</p>
          </div>
          <Link to="/templates" className="pf-btn pf-btn-ghost pf-btn-sm">
            <IconClapper size={17} />{t('home.templatesTitle')}
          </Link>
        </header>

        <section className="pf-project-list-panel" aria-label={t('history.projectsHeading')}>
          <div className="pf-project-list-heading">
            <div>
              <h2>{t('history.projectsHeading')}{!loading && <span>{stats.total}</span>}</h2>
              <p>{t('history.workflowHint')}</p>
            </div>
            <button type="button" className="pf-btn pf-btn-lime pf-btn-icon" onClick={() => nav(SHORT_VIDEO_CREATE_PATH)}>
              <IconPlus size={18} />{t('history.newKepu')}
            </button>
          </div>

          <div className="pf-project-list-toolbar">
            <PillTabs
              items={HISTORY_TABS.map((id) => m.history.tabs[id])}
              value={m.history.tabs[tab]}
              onChange={(label) => {
                const next = HISTORY_TABS.find((id) => m.history.tabs[id] === label)
                if (next) setTab(next)
              }}
              ariaLabel={t('history.statusAria')}
              lime
            />
            <div className="pf-short-video-filters">
              <select className="pf-type-select" value={typeMode} aria-label={t('history.typeAria')} onChange={(e) => setTypeMode(e.target.value as '' | 'full' | 'image_text')}>
                <option value="">{t('history.typeAll')}</option>
                <option value="full">{t('history.typeFull')}</option>
                <option value="image_text">{t('history.typeImageText')}</option>
              </select>
              <label className="pf-project-list-search">
                <IconSearch size={17} />
                <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('history.searchPlaceholder')} aria-label={t('history.searchPlaceholder')} />
              </label>
            </div>
          </div>

          {selectedDownloadable.length > 0 ? <div className="pf-short-video-batch">
            <button type="button" className="pf-btn-text" disabled={packing} onClick={packSelected}>
              <IconDownload size={15} />
              {packing ? t('history.packing', { progress: packProgress }) : t('history.packDownload', { count: selectedDownloadable.length })}
            </button>
            <button type="button" className="pf-btn-text" disabled={packing} onClick={() => setSelected(new Set())}>{t('common.cancel')}</button>
          </div> : null}

          {error ? <BillingErrorNotice message={error} /> : null}
          {loading ? (
            <div aria-busy="true" aria-label={t('common.loading')}><ProjectGrid>{Array.from({ length: 6 }, (_, i) => <div key={i} className="pf-project-list-skeleton" aria-hidden />)}</ProjectGrid></div>
          ) : total === 0 ? (
            <div className="pf-empty-state">
              <div className="pf-empty-illust" aria-hidden><IconClapper size={42} /></div>
              <p className="pf-muted">{t('history.empty')}</p>
              <button type="button" className="pf-btn pf-btn-lime" onClick={() => nav(SHORT_VIDEO_CREATE_PATH)}><IconPlus size={17} />{t('history.newKepu')}</button>
            </div>
          ) : (
            <ProjectGrid>
              {pageItems.map((p) => {
                const running = isRunning(p.status) || hasActiveTasks(p)
                const ratio = p.output_ratio || (p.pipeline_mode === 'image_text' ? '9:16' : '16:9')
                const tplName = templates[p.template_id] || p.template_id
                return <ProjectCard
                  key={p.id}
                  kind="short-video"
                  title={p.title}
                  coverUrl={p.cover_url ? api.assetUrl(p.cover_url, p.updated_at) : undefined}
                  category={`${tplName} · ${ratio}`}
                  status={{ label: STATUS_CN[p.status] || p.status, tone: p.status === 'DONE' ? 'completed' : running ? 'producing' : p.status === 'DRAFT' ? 'draft' : 'neutral' }}
                  description={p.source_text || t('history.workflowHint')}
                  progress={running ? { label: t('history.progress'), value: Math.max(0, Math.min(100, p.progress)), total: 100 } : undefined}
                  meta={p.error_msg ? <span className="pf-error" role="status">{formatGenerationErrorMessage(p.error_msg)}</span> : undefined}
                  footer={<>
                    <span>{p.published ? t('history.published') : (p.pipeline_mode === 'image_text' ? t('history.typeImageText') : t('history.typeFull'))}</span>
                    <time dateTime={p.updated_at || p.created_at}>{formatDateTime(p.updated_at || p.created_at, locale)}</time>
                  </>}
                  selection={canDownload(p) ? { checked: selected.has(p.id), visible: selected.size > 0, onChange: () => toggle(p.id), label: t('history.selectProject', { title: p.title }) } : undefined}
                  onOpen={() => continueEdit(p)}
                  openLabel={`${t('history.continueEdit')} ${p.title}`}
                  menu={<button type="button" className="pf-icon-btn danger" disabled={busyId === p.id} title={t('common.delete')} aria-label={`${t('common.delete')} ${p.title}`} onClick={() => remove(p.id)}><IconTrash size={16} /></button>}
                  actions={<>
                    <button type="button" className="pf-btn-text" onClick={() => continueEdit(p)}><IconEdit size={14} />{t('history.continueEdit')}</button>
                    <button type="button" className="pf-btn-text" disabled={!p.final_video_url} onClick={() => p.final_video_url && setPreview({ url: api.assetUrl(p.final_video_url, p.updated_at), title: p.title, projectId: p.id })}><IconEye size={14} />{t('common.preview')}</button>
                    <button type="button" className="pf-btn-text" disabled={!canDownload(p) || busyId === p.id || packing} onClick={() => downloadOne(p)}><IconDownload size={14} />{busyId === p.id ? t('common.downloading') : t('common.download')}</button>
                    <button type="button" className="pf-btn-text" disabled={!p.final_video_url} onClick={() => nav(withReturn(`/marketplace/from-printfilm?project=${p.id}`, `${location.pathname}${location.search}`))}><IconSend size={14} />{mt("发布到数字资产市场")}</button>
                  </>}
                />
              })}
            </ProjectGrid>
          )}
          {total > 0 ? (
            <Pagination page={page} pageCount={pageCount} total={total} onChange={setPage} ariaLabel={t('history.pagination')} />
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
