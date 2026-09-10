/** 漫剧 Agent 首页：AI 生剧本 / 自由画布 + 我的项目（多选删除） */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FolderOpen,
  LayoutGrid,
  Library,
  PenLine,
  Search,
  Sparkles,
  Trash2,
} from 'lucide-react'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import AppShell from '../../components/layout/AppShell'
import Button from '../../components/ui/Button'
import PillFilter, { type PillOption } from '../../components/ui/PillFilter'
import { dramaApi, resolveDramaMediaUrl, type DramaProjectListItem } from '../../api/drama'
import { dialog } from '../../lib/dialog'
import { type ImageStyleId } from '../../lib/dramaImageStyles'
import { formatDramaUsageBrief } from '../../lib/dramaUsage'
import {
  dramaProjectEntryPath,
  formatDramaCardMeta,
  isCanvasWorkflow,
} from '../../lib/dramaWorkflow'
import RequireAuth from './RequireAuth'
import { useI18n } from '../../i18n'
import { DramaEpisodeCountPopover } from './DramaEpisodeCountPopover'
import { DramaImageStyleModal } from './DramaImageStyleModal'
import { DramaProjectCardMenu } from './DramaProjectCardMenu'
import './drama.css'

const CREATIVE_MIN_LENGTH = 20
const CREATIVE_MAX_LENGTH = 2000
const CANVAS_PLACEHOLDER =
  '自由画布创作项目，稍后在画布中完善故事与资产。'

type AgentTab = 'ai' | 'canvas'

// 格式化更新时间
function formatUpdatedAt(raw?: string) {
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 封面竖排标题（无预览图时）
function verticalTitleLabel(name: string, max = 12): string {
  const clean = (name || '').replace(/\s+/g, '')
  if (clean.length <= max) return clean
  return `${clean.slice(0, max - 1)}…`
}

type ProjectFilter = 'all' | 'running' | 'done' | 'draft'

const FILTER_KEYS: ProjectFilter[] = ['all', 'running', 'done', 'draft']

export default function DramaListPage() {
  return (
    <RequireAuth>
      <DramaListInner />
    </RequireAuth>
  )
}

// 渲染 Agent 首页内容
function DramaListInner() {
  const navigate = useNavigate()
  const { t, m } = useI18n()
  const filterOptions = useMemo<PillOption<ProjectFilter>[]>(
    () =>
      FILTER_KEYS.map((value) => ({
        value,
        label: m.dramaList.filters[value],
      })),
    [m],
  )
  /*
   * storyText AI 创意输入
   * episodeCount 目标集数
   * imageStyleId 画面风格
   * items 我的项目列表
   * loading 列表加载中
   * busy 创建中
   * canvasBusy 画布创建中
   * error 错误文案
   * selected 多选 id
   * deleting 批量删除中
   * filter 列表筛选
   * query 搜索
   * showCreate 是否展开新建面板
   */
  const [storyText, setStoryText] = useState('')
  const [episodeCount, setEpisodeCount] = useState(12)
  const [imageStyleId, setImageStyleId] = useState<ImageStyleId | ''>('')
  const [items, setItems] = useState<DramaProjectListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [canvasBusy, setCanvasBusy] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [filter, setFilter] = useState<ProjectFilter>('all')
  const [query, setQuery] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  // 加载项目列表
  async function loadProjects() {
    const rows = await dramaApi.listProjects()
    setItems(rows)
    setSelected((prev) => {
      const ids = new Set(rows.map((r) => r.id))
      return new Set([...prev].filter((id) => ids.has(id)))
    })
  }

  useEffect(() => {
    setLoading(true)
    loadProjects()
      .catch((err) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [])

  // AI 立即生成：创建项目并进入大纲步骤
  async function handleGenerate() {
    const source = storyText.trim()
    if (source.length < CREATIVE_MIN_LENGTH) {
      setError(`故事内容至少 ${CREATIVE_MIN_LENGTH} 字`)
      return
    }
    if (source.length > CREATIVE_MAX_LENGTH) {
      setError(`故事内容请控制在 ${CREATIVE_MAX_LENGTH} 字以内`)
      return
    }
    setBusy(true)
    setError('')
    try {
      const project = await dramaApi.createProject({
        source,
        episode_count: episodeCount,
        image_style_id: imageStyleId || undefined,
        title: source.slice(0, 40),
      })
      navigate(`/drama/projects/${project.id}`, { state: { activeStep: 'outline' } })
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setBusy(false)
    }
  }

  // 自由画布：创建占位创意项目并进入画布
  async function handleEnterCanvas() {
    if (canvasBusy) return
    setCanvasBusy(true)
    setError('')
    try {
      const project = await dramaApi.createProject({
        source: CANVAS_PLACEHOLDER,
        episode_count: 1,
        title: '自由画布项目',
        workflow: 'canvas',
      })
      navigate(`/drama/projects/${project.id}/canvas`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建画布项目失败')
    } finally {
      setCanvasBusy(false)
    }
  }

  // 切换 Tab；画布 Tab 直接创建并跳转
  function handleTabClick(next: AgentTab) {
    if (next === 'canvas') {
      void handleEnterCanvas()
    }
  }

  const selectionMode = selected.size > 0
  const storyLen = storyText.trim().length
  const canGenerate = storyLen >= CREATIVE_MIN_LENGTH && storyLen <= CREATIVE_MAX_LENGTH && !busy
  const charCountClass =
    storyLen > CREATIVE_MAX_LENGTH
      ? ' is-over'
      : storyLen >= CREATIVE_MIN_LENGTH
        ? ' is-ok'
        : ''

  const filteredItems = items.filter((item) => {
    const canvas = isCanvasWorkflow(item)
    if (filter === 'draft') {
      if (canvas) return (item.asset_count || 0) === 0
      if (item.has_script) return false
    }
    if (filter === 'running') {
      if (canvas) return (item.asset_count || 0) > 0
      if (!(item.has_script && (item.episode_count || 0) > 0)) return false
    }
    if (filter === 'done') {
      if (canvas) return false
      if (!(item.has_script && (item.episode_count || 0) >= 8)) return false
    }
    const q = query.trim().toLowerCase()
    if (q && !(item.title || '').toLowerCase().includes(q)) return false
    return true
  })

  // 切换选中
  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // 打开项目：自由画布进画布，普通项目进工作台
  function openProject(item: DramaProjectListItem) {
    if (selectionMode) {
      toggleSelect(item.id)
      return
    }
    navigate(dramaProjectEntryPath(item))
  }

  // 重命名
  async function handleRename(item: DramaProjectListItem) {
    const name = await dialog.prompt({
      title: t('dramaList.renameTitle'),
      message: t('dramaList.renameMessage'),
      defaultValue: item.title,
      confirmText: t('common.save'),
    })
    if (!name?.trim() || name.trim() === item.title) return
    try {
      await dramaApi.updateProject(item.id, { title: name.trim() })
      await loadProjects()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('dramaList.renameFailed'))
    }
  }

  // 删除单个
  async function handleDeleteOne(item: DramaProjectListItem) {
    const ok = await dialog.confirm({
      title: t('dramaList.deleteTitle'),
      message: t('dramaList.deleteOne', { title: item.title }),
      confirmText: t('common.delete'),
      tone: 'danger',
    })
    if (!ok) return
    try {
      await dramaApi.deleteProject(item.id)
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(item.id)
        return next
      })
      await loadProjects()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('dramaList.deleteFailed'))
    }
  }

  // 批量删除
  async function handleDeleteSelected() {
    const ids = [...selected]
    if (ids.length === 0) return
    const ok = await dialog.confirm({
      title: t('dramaList.deleteTitle'),
      message: t('dramaList.deleteMany', { count: ids.length }),
      confirmText: t('common.delete'),
      tone: 'danger',
    })
    if (!ok) return
    setDeleting(true)
    try {
      await Promise.all(ids.map((id) => dramaApi.deleteProject(id)))
      setSelected(new Set())
      await loadProjects()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('dramaList.deleteFailed'))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <AppShell active="drama">
      <div className="drama-page drama-agent-page pf-drama-list">
        <header className="pf-drama-list-head">
          <div className="pf-drama-list-title-row">
            <h1>{t('dramaList.title')}</h1>
            <div className="pf-drama-list-actions">
              <Button variant="ghost" size="sm" to="/drama/assets">
                <Library size={15} strokeWidth={1.75} aria-hidden />
                {t('dramaList.assets')}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={canvasBusy}
                onClick={() => handleTabClick('canvas')}
              >
                <LayoutGrid size={15} strokeWidth={1.75} aria-hidden />
                {canvasBusy ? t('dramaList.creating') : t('dramaList.canvas')}
              </Button>
              <Button
                variant="lime"
                size="sm"
                onClick={() => {
                  setShowCreate(true)
                  handleTabClick('ai')
                }}
              >
                {t('dramaList.newProject')}
              </Button>
            </div>
          </div>

          <div className="pf-drama-list-toolbar">
            <PillFilter<ProjectFilter>
              options={filterOptions}
              value={filter}
              onChange={setFilter}
              ariaLabel={t('dramaList.filterAria')}
            />
            <label className="pf-drama-search">
              <Search size={16} strokeWidth={2} aria-hidden />
              <span className="sr-only">{t('dramaList.searchAria')}</span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('dramaList.searchPlaceholder')}
              />
            </label>
          </div>
        </header>

        {showCreate ? (
          <section className="drama-agent-panel pf-drama-create-panel" aria-label={t('dramaList.createAria')}>
            <div className="drama-agent-panel-head">
              <div className="drama-agent-tabs" role="tablist">
                <button type="button" role="tab" aria-selected className="active">
                  <PenLine size={15} strokeWidth={1.75} aria-hidden />
                  {t('dramaList.aiScript')}
                </button>
              </div>
              <button type="button" className="pf-link pf-drama-collapse" onClick={() => setShowCreate(false)}>
                {t('dramaList.collapse')}
              </button>
            </div>
            <div className="drama-agent-tips" role="note">
              <Sparkles size={15} strokeWidth={1.75} aria-hidden />
              <span>
                {t('dramaList.tipRest', {
                  a: t('dramaList.tipStrong1'),
                  b: t('dramaList.tipStrong2'),
                  c: t('dramaList.tipStrong3'),
                })}
              </span>
            </div>
            <div className="drama-agent-ai">
              <label className="drama-agent-ai-label" htmlFor="drama-agent-story">
                {t('dramaList.storyLabel')}
              </label>
              <div className={`drama-agent-ai-field${storyText.trim() ? ' has-value' : ''}`}>
                <textarea
                  id="drama-agent-story"
                  value={storyText}
                  onChange={(e) => setStoryText(e.target.value.slice(0, CREATIVE_MAX_LENGTH + 50))}
                  disabled={busy}
                  placeholder="在此输入你构想的故事内容：故事设定、主角特征、剧情脉络、最终结局等"
                  rows={7}
                  maxLength={CREATIVE_MAX_LENGTH + 50}
                />
                <span
                  className={`drama-agent-char-count${charCountClass}`}
                  aria-live="polite"
                >
                  {storyLen}
                  <span className="drama-agent-char-sep">/</span>
                  {CREATIVE_MAX_LENGTH}
                </span>
              </div>
              <div className="drama-agent-ai-footer">
                <div className="drama-agent-ai-options">
                  <DramaImageStyleModal value={imageStyleId} onChange={setImageStyleId} disabled={busy} />
                  <span className="drama-agent-opt-divider" aria-hidden />
                  <DramaEpisodeCountPopover value={episodeCount} onChange={setEpisodeCount} disabled={busy} />
                </div>
                <Button
                  variant="lime"
                  size="md"
                  className="drama-agent-generate-btn"
                  disabled={!canGenerate}
                  onClick={() => void handleGenerate()}
                >
                  <Sparkles size={16} strokeWidth={1.75} aria-hidden />
                  {busy ? '创建中…' : '立即生成'}
                </Button>
              </div>
            </div>
          </section>
        ) : null}

        {error ? <BillingErrorNotice message={error} className="drama-error drama-agent-error" /> : null}

        {loading ? (
          <div className="pf-drama-card-grid" aria-busy="true">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="pf-drama-card is-skeleton" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="pf-empty-state">
            <div className="pf-empty-illust" aria-hidden>
              <FolderOpen size={48} strokeWidth={1.2} />
            </div>
            <h2>还没有项目</h2>
            <p className="pf-muted">用 AI 生剧本或自由画布，创建你的第一部漫剧</p>
            <Button
              variant="lime"
              onClick={() => {
                setShowCreate(true)
                handleTabClick('ai')
              }}
            >
              新建项目
            </Button>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="pf-empty-state is-compact">
            <p className="pf-muted">没有符合筛选的项目</p>
            <Button variant="ghost" size="sm" onClick={() => { setFilter('all'); setQuery('') }}>
              清除筛选
            </Button>
          </div>
        ) : (
          <div className="pf-drama-card-grid">
            <button
              type="button"
              className="pf-drama-card pf-drama-card-new"
              onClick={() => {
                setShowCreate(true)
                handleTabClick('ai')
              }}
            >
              <span className="pf-drama-card-plus" aria-hidden>
                +
              </span>
              <strong>新建项目</strong>
            </button>
            {filteredItems.map((item) => {
              const isSelected = selected.has(item.id)
              const coverSrc = item.cover_url ? resolveDramaMediaUrl(item.cover_url) : ''
              const canvas = isCanvasWorkflow(item)
              return (
                <article
                  key={item.id}
                  className={`pf-drama-card${isSelected ? ' is-selected' : ''}${canvas ? ' is-canvas' : ''}`}
                >
                  <button
                    type="button"
                    className="pf-drama-card-cover"
                    onClick={() => openProject(item)}
                    aria-label={`打开 ${item.title}`}
                  >
                    {coverSrc ? (
                      <img
                        src={coverSrc}
                        alt=""
                        className="pf-drama-card-cover-img"
                        loading="lazy"
                        decoding="async"
                      />
                    ) : (
                      <span className="pf-drama-card-cover-fallback">{verticalTitleLabel(item.title)}</span>
                    )}
                    {canvas ? <span className="pf-drama-card-cover-badge is-canvas">自由画布</span> : null}
                    {!canvas && item.cover_pending ? (
                      <span className="pf-drama-card-cover-badge">封面生成中</span>
                    ) : null}
                    {!canvas && !coverSrc && !item.cover_pending && item.asset_count > 0 ? (
                      <span className="pf-drama-card-cover-badge is-muted">待出图</span>
                    ) : null}
                    <label
                      className={`drama-project-row-check${isSelected || selectionMode ? ' is-visible' : ''}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input type="checkbox" checked={isSelected} onChange={() => toggleSelect(item.id)} />
                    </label>
                  </button>
                  <div className="pf-drama-card-body">
                    <div className="pf-drama-card-top">
                      <button type="button" className="pf-drama-card-title" onClick={() => openProject(item)}>
                        {item.title}
                      </button>
                      <DramaProjectCardMenu
                        onRename={() => void handleRename(item)}
                        onDelete={() => void handleDeleteOne(item)}
                      />
                    </div>
                    <p className="pf-drama-card-meta">{formatDramaCardMeta(item)}</p>
                    <p className="pf-drama-card-usage" title="本剧累计费用与生成次数">
                      {formatDramaUsageBrief(item.usage)}
                    </p>
                    <p className="pf-drama-card-time">{formatUpdatedAt(item.updated_at || item.created_at)}</p>
                  </div>
                </article>
              )
            })}
          </div>
        )}

        {selected.size > 0 ? (
          <div className="drama-project-selection-bar">
            <div className="drama-project-selection-inner">
              <span>已选择 {selected.size} 个项目</span>
              <button
                type="button"
                className="drama-project-selection-cancel"
                disabled={deleting}
                onClick={() => setSelected(new Set())}
              >
                取消选择
              </button>
              <button
                type="button"
                className="drama-project-selection-delete"
                disabled={deleting}
                onClick={() => void handleDeleteSelected()}
              >
                <Trash2 size={16} strokeWidth={1.8} />
                {deleting ? '删除中…' : '删除'}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </AppShell>
  )
}
