/** 漫剧 / 自由画布项目列表，共享项目管理与空间隔离。 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FolderOpen,
  Layers,
  Library,
  Plus,
  Search,
  UserRound,
  Trash2,
} from 'lucide-react'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import AppShell from '../../components/layout/AppShell'
import Button from '../../components/ui/Button'
import PillFilter, { type PillOption } from '../../components/ui/PillFilter'
import { dramaApi, resolveDramaMediaUrl, type DramaProjectListItem } from '../../api/drama'
import { dialog } from '../../lib/dialog'
import { formatDramaUsageBrief } from '../../lib/dramaUsage'
import {
  dramaProjectEntryPath,
  formatDramaCardMeta,
  isCanvasWorkflow,
  type DramaProjectFilter,
  type DramaWorkflow,
} from '../../lib/dramaWorkflow'
import { pageCountOf } from '../../lib/pagination'
import Pagination from '../../components/ui/Pagination'
import RequireAuth from './RequireAuth'
import { useI18n } from '../../i18n'
import { DramaProjectCardMenu } from './DramaProjectCardMenu'
import { ProjectCard, ProjectGrid } from '../../components/projects/ProjectCard'
import ProjectCreateDialog, { type ProjectCreateValues } from '../../components/projects/ProjectCreateDialog'
import DramaPublishModal from '../../features/marketplace/DramaPublishModal'
import { useMarketplace } from '../../features/marketplace/hooks'
import './drama.css'
import './project-list.css'

const CANVAS_PLACEHOLDER =
  '自由画布创作项目，稍后在画布中完善故事与资产。'

// 格式化更新时间
function formatUpdatedAt(raw?: string) {
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const FILTER_KEYS: DramaProjectFilter[] = ['all', 'running', 'done', 'draft']

// 每页条数选项：卡片网格一行 3 个，6 / 9 恰好整行；默认 9
const PAGE_SIZE_OPTIONS = [6, 9] as const
const PAGE_SIZE_DEFAULT = 9

export default function DramaListPage({ workflow = 'script' }: { workflow?: DramaWorkflow }) {
  return (
    <RequireAuth>
      <DramaListInner key={workflow} workflow={workflow} />
    </RequireAuth>
  )
}

// 渲染 Agent 首页内容
function DramaListInner({ workflow }: { workflow: DramaWorkflow }) {
  const navigate = useNavigate()
  const { capabilities } = useMarketplace()
  const [publishProjectId, setPublishProjectId] = useState<number | null>(null)
  const { t, m } = useI18n()
  const canvasMode = workflow === 'canvas'
  const createLabel = canvasMode ? t('canvasList.newCanvas') : t('dramaList.newProject')
  const filterOptions = useMemo<PillOption<DramaProjectFilter>[]>(
    () =>
      FILTER_KEYS.filter((value) => !canvasMode || value !== 'done').map((value) => ({
        value,
        label: canvasMode && value === 'draft' ? t('canvasList.emptyFilter') : m.dramaList.filters[value],
      })),
    [m, t, canvasMode],
  )
  const [items, setItems] = useState<DramaProjectListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZE_DEFAULT)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [filter, setFilter] = useState<DramaProjectFilter>('all')
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  // 搜索防抖，避免每敲一个字就请求一次
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [query])

  // 请求序号：筛选/页码连续变化时按序号丢弃过期响应，避免旧数据覆盖新页
  const loadSeq = useRef(0)

  // 加载当前页项目：筛选与分页均在服务端完成
  const loadProjects = useCallback(async () => {
    const seq = ++loadSeq.current
    try {
      const res = await dramaApi.listProjects({
        workflow,
        status: filter,
        q: debouncedQuery || undefined,
        page,
        page_size: pageSize,
      })
      if (seq !== loadSeq.current) return
      setItems(res.items)
      setTotal(res.meta.total)
      setError('')
      // 服务端会对越界页码收口（如删除后末页变空），同步回真实页码
      if (res.meta.page !== page) setPage(res.meta.page)
    } catch (err) {
      if (seq !== loadSeq.current) return
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }, [workflow, filter, debouncedQuery, page, pageSize])

  useEffect(() => {
    setLoading(true)
    void loadProjects()
  }, [loadProjects])

  const pageCount = pageCountOf(total, pageSize)
  // 筛选后若当前页超出范围则回退
  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  async function handleCreateProject(values: ProjectCreateValues) {
    const project = await dramaApi.createProject({
      title: values.title || values.source.slice(0, 40),
      source: canvasMode ? CANVAS_PLACEHOLDER : values.source,
      description: values.description || undefined,
      episode_count: canvasMode ? 1 : values.episodeCount,
      image_style_id: !canvasMode && values.imageStyleId ? values.imageStyleId : undefined,
      workflow,
    })
    setShowCreate(false)
    if (canvasMode) navigate(`/drama/projects/${project.id}/canvas`)
    else navigate(`/drama/projects/${project.id}`, { state: { activeStep: 'outline' } })
  }

  const selectionMode = selected.size > 0
  // 未加任何筛选且结果为空时才展示「还没有项目」大空态
  const pristineEmpty = total === 0 && filter === 'all' && !debouncedQuery

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
      // allSettled 保证单项失败不影响其余删除；已被删除（404）的视为完成并移出选择
      const results = await Promise.allSettled(ids.map((id) => dramaApi.deleteProject(id)))
      const gone = new Set<number>()
      let failed = 0
      results.forEach((result, index) => {
        const status = result.status === 'rejected' ? (result.reason as { status?: number } | undefined)?.status : undefined
        if (result.status === 'fulfilled' || status === 404) gone.add(ids[index])
        else failed += 1
      })
      setSelected((prev) => new Set([...prev].filter((id) => !gone.has(id))))
      if (failed > 0) setError(t('dramaList.deleteFailed'))
      await loadProjects()
    } finally {
      setDeleting(false)
    }
  }

  return (
    <AppShell active={canvasMode ? 'canvas' : 'drama'}>
      <div className="drama-page pf-project-list-page">
        <header className="pf-project-page-header">
          <div>
            <span className="pf-project-page-eyebrow">{canvasMode ? 'FREE CANVAS' : 'PERSONAL WORKSPACE'}</span>
            <h1>{canvasMode ? t('canvasList.title') : t('dramaList.title')}</h1>
            <p>{t(canvasMode ? 'canvasList.description' : 'dramaList.description')}</p>
          </div>
          <Button variant="outline" to="/drama/assets">
            <Library size={17} strokeWidth={1.75} aria-hidden />
            {t('dramaList.assets')}
          </Button>
        </header>

        <section className="pf-project-list-panel" aria-label={canvasMode ? '我的画布' : '我的项目'}>
          <div className="pf-project-list-heading">
            <div>
              <h2>{canvasMode ? '我的画布' : '我的项目'}{!loading && <span>{total}</span>}</h2>
              <p>{canvasMode ? '收集灵感，自由连接每一个创作节点。' : '让每一个好故事，稳步成为作品。'}</p>
            </div>
            <Button variant="lime" onClick={() => setShowCreate(true)}>
              <Plus size={19} strokeWidth={1.8} aria-hidden />{createLabel}
            </Button>
          </div>
          <div className="pf-project-list-toolbar">
            <PillFilter<DramaProjectFilter>
              options={filterOptions}
              value={filter}
              onChange={(next) => { setFilter(next); setPage(1) }}
              ariaLabel={t('dramaList.filterAria')}
            />
            <label className="pf-project-list-search">
              <Search size={18} strokeWidth={1.8} aria-hidden />
              <span className="sr-only">{t('dramaList.searchAria')}</span>
              <input
                type="search"
                value={query}
                onChange={(e) => { setQuery(e.target.value); setPage(1) }}
                placeholder={t(canvasMode ? 'canvasList.searchPlaceholder' : 'dramaList.searchPlaceholder')}
              />
            </label>
          </div>

          {error ? <BillingErrorNotice message={error} className="drama-error" /> : null}
          {loading ? (
            <div aria-busy="true" aria-label="正在加载项目">
              <ProjectGrid>{Array.from({ length: pageSize }).map((_, i) => <div key={i} className="pf-project-list-skeleton" aria-hidden />)}</ProjectGrid>
            </div>
          ) : pristineEmpty ? (
            <div className="pf-empty-state">
              <div className="pf-empty-illust" aria-hidden><FolderOpen size={48} strokeWidth={1.2} /></div>
              <h2>{t(canvasMode ? 'canvasList.emptyTitle' : 'dramaList.emptyTitle')}</h2>
              <p className="pf-muted">{t(canvasMode ? 'canvasList.emptyDescription' : 'dramaList.emptyDescription')}</p>
              <Button variant="lime" onClick={() => setShowCreate(true)}><Plus size={17} />{createLabel}</Button>
            </div>
          ) : items.length === 0 ? (
            <div className="pf-empty-state is-compact">
              <p className="pf-muted">没有符合筛选的项目</p>
              <Button variant="ghost" size="sm" onClick={() => { setFilter('all'); setQuery('') }}>清除筛选</Button>
            </div>
          ) : (
            <>
            <ProjectGrid>
              {items.map((item) => {
                const canvas = isCanvasWorkflow(item)
                const active = canvas ? item.asset_count > 0 : item.has_script
                const status = item.cover_pending && !canvas ? '封面生成中' : active ? (canvas ? '创作中' : '已写剧本') : (canvas ? '空画布' : '构思中')
                return <ProjectCard
                  key={item.id}
                  title={item.title}
                  kind={canvas ? 'canvas' : 'drama'}
                  coverUrl={item.cover_url ? resolveDramaMediaUrl(item.cover_url) : undefined}
                  category={canvas ? '自由画布' : `漫剧项目 · ${item.episode_count} 集`}
                  status={{ label: status, tone: active || item.cover_pending ? 'producing' : 'draft' }}
                  description={item.description || (canvas ? '在画布中添加图片、视频与灵感，展开自由创作。' : '从故事到分镜，在项目中继续完善你的作品。')}
                  meta={<>
                    <span className="pf-project-list-card-meta"><Layers size={14} aria-hidden />{formatDramaCardMeta(item)}</span>
                    <span title={canvasMode ? t('canvasList.usageTitle') : '本剧累计费用与生成次数'}>{formatDramaUsageBrief(item.usage)}</span>
                  </>}
                  footer={<>
                    <span><UserRound size={13} aria-hidden />个人项目</span>
                    <time dateTime={item.updated_at || item.created_at}>{formatUpdatedAt(item.updated_at || item.created_at)}</time>
                  </>}
                  menu={<DramaProjectCardMenu
                    onRename={() => void handleRename(item)}
                    onDelete={() => void handleDeleteOne(item)}
                    onPublish={capabilities?.enabled ? () => setPublishProjectId(item.id) : undefined}
                  />}
                  selection={{ checked: selected.has(item.id), visible: selectionMode, onChange: () => toggleSelect(item.id), label: `选择 ${item.title}` }}
                  onOpen={() => openProject(item)}
                  openLabel={selectionMode ? `切换选择 ${item.title}` : `打开 ${item.title}`}
                />
              })}
            </ProjectGrid>
            <Pagination
              page={page}
              pageCount={pageCount}
              total={total}
              pageSize={pageSize}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              onPageSizeChange={(size) => {
                setPageSize(size)
                setPage(1)
              }}
              onChange={setPage}
            />
            </>
          )}
        </section>
        <ProjectCreateDialog open={showCreate} onClose={() => setShowCreate(false)} kind={canvasMode ? 'canvas' : 'drama'} onSubmit={handleCreateProject} />

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
      {publishProjectId && capabilities?.enabled && <DramaPublishModal projectId={publishProjectId} selectReady onClose={() => setPublishProjectId(null)} />}
    </AppShell>
  )
}
