/** 全局漫剧资产库：按角色 / 场景 / 道具 / 音色分类，音色可试听 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import AppShell from '../../components/layout/AppShell'
import Button from '../../components/ui/Button'
import FilterSelect from '../../components/ui/FilterSelect'
import Pagination from '../../components/ui/Pagination'
import PillFilter from '../../components/ui/PillFilter'
import { CharacterVoicePreviewButton } from '../../components/drama/CharacterVoicePreviewButton'
import {
  dramaApi,
  resolveDramaMediaUrl,
  type DramaAsset,
  type DramaProjectListItem,
} from '../../api/drama'
import { readAssetVoiceBinding } from './CharacterVoiceBindModal'
import { DramaImageLightbox } from './DramaImageLightbox'
import { filterDramaLibraryAssets, isDramaLibraryAsset } from '../../lib/dramaLibraryAssets'
import { pageCountOf } from '../../lib/pagination'
import RequireAuth from './RequireAuth'
import './drama.css'

type AssetTabKey = 'all' | 'character' | 'scene' | 'prop' | 'voice'

const PAGE_SIZE_DEFAULT = 12
const PAGE_SIZE_OPTIONS = [12, 24, 36] as const

const TABS: Array<{ value: AssetTabKey; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'character', label: '角色' },
  { value: 'scene', label: '场景' },
  { value: 'prop', label: '道具' },
  { value: 'voice', label: '音色' },
]

const KIND_LABEL: Record<string, string> = {
  character: '角色',
  scene: '场景',
  prop: '道具',
  voice: '音色',
}

export default function AssetLibraryPage() {
  return (
    <RequireAuth>
      <AssetLibraryInner />
    </RequireAuth>
  )
}

// 按资产 type 归入角色 / 场景 / 道具 / 音色
function assetKind(asset: DramaAsset): AssetTabKey | 'other' {
  if (!isDramaLibraryAsset(asset)) return 'other'
  const t = (asset.type || '').toLowerCase()
  if (t === 'character' || t === 'scene' || t === 'prop' || t === 'voice') return t
  return 'other'
}

function matchTab(asset: DramaAsset, tab: AssetTabKey): boolean {
  if (!isDramaLibraryAsset(asset)) return false
  if (tab === 'all') return true
  return assetKind(asset) === tab
}

function fileMeta(asset: DramaAsset): string {
  const kind = assetKind(asset)
  if (kind !== 'other') return KIND_LABEL[kind]
  const url = (asset.cover || asset.url || '').toLowerCase()
  const ext = url.match(/\.([a-z0-9]{2,5})(\?|$)/)?.[1]
  if (ext) return `.${ext}`
  return asset.type || '文件'
}

// 音色资产或角色已绑定音色的试听地址
function voicePreviewUrl(asset: DramaAsset): string {
  if (assetKind(asset) === 'voice') return asset.url || ''
  return readAssetVoiceBinding(asset)?.url || ''
}

function isImageLike(asset: DramaAsset): boolean {
  const kind = assetKind(asset)
  return kind === 'character' || kind === 'scene' || kind === 'prop' || kind === 'other'
}

// 渲染资产库内容
function AssetLibraryInner() {
  /*
   * assets 当前项目范围下的资产
   * projects 项目列表（筛选用）
   * projectId 选中的项目 id，空串表示全部
   * tab 角色/场景/道具/音色
   * query 搜索词
   * page 当前页
   * playingId 正在试听的资产 id
   * error 错误文案
   * loading 加载中
   */
  const [assets, setAssets] = useState<DramaAsset[]>([])
  const [projects, setProjects] = useState<DramaProjectListItem[]>([])
  const [projectId, setProjectId] = useState('')
  const [tab, setTab] = useState<AssetTabKey>('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT)
  const [playingId, setPlayingId] = useState<number | null>(null)
  const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    dramaApi
      .listProjects()
      .then(setProjects)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    const pid = projectId ? Number(projectId) : undefined
    dramaApi
      .listAssets(Number.isFinite(pid) ? pid : undefined, { libraryOnly: true })
      .then((rows) => {
        if (!cancelled) setAssets(filterDramaLibraryAssets(rows))
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  useEffect(() => {
    return () => {
      audioRef.current?.pause()
    }
  }, [])

  const projectNameById = useMemo(() => {
    const map = new Map<number, string>()
    for (const p of projects) map.set(p.id, p.title || `项目 #${p.id}`)
    return map
  }, [projects])

  const projectOptions = useMemo(
    () => [
      { value: '', label: '全部项目' },
      ...projects.map((p) => ({
        value: String(p.id),
        label: p.title || `项目 #${p.id}`,
      })),
    ],
    [projects],
  )

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return assets.filter((asset) => {
      if (!matchTab(asset, tab)) return false
      if (!q) return true
      const name = (asset.name || '').toLowerCase()
      const type = (asset.type || '').toLowerCase()
      const projectName = (projectNameById.get(asset.project_id) || '').toLowerCase()
      return (
        name.includes(q) ||
        type.includes(q) ||
        projectName.includes(q) ||
        String(asset.project_id).includes(q)
      )
    })
  }, [assets, tab, query, projectNameById])

  const pageCount = pageCountOf(filtered.length, pageSize)
  const safePage = Math.min(page, pageCount)
  const pageItems = useMemo(() => {
    const start = (safePage - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, safePage, pageSize])

  useEffect(() => {
    setPage(1)
  }, [tab, query, projectId, pageSize])

  // 卡片缩略图上试听 / 暂停音色
  function toggleVoice(asset: DramaAsset) {
    const src = resolveDramaMediaUrl(voicePreviewUrl(asset))
    if (!src) {
      setError('该音色尚未合成试听')
      return
    }
    if (playingId === asset.id) {
      audioRef.current?.pause()
      setPlayingId(null)
      return
    }
    if (!audioRef.current) audioRef.current = new Audio()
    audioRef.current.src = src
    audioRef.current.onended = () => setPlayingId(null)
    void audioRef.current.play().catch(() => setError('播放失败'))
    setPlayingId(asset.id)
  }

  return (
    <AppShell active="assets">
      <div className="drama-page pf-asset-page">
        <header className="pf-drama-list-head">
          <div className="pf-drama-list-title-row">
            <div>
              <h1>资产管理</h1>
              <p className="pf-muted" style={{ margin: '0.35rem 0 0' }}>
                按角色、场景、道具与音色浏览
              </p>
            </div>
            <div className="pf-drama-list-actions">
              <Button to="/drama" variant="ghost" size="sm">
                漫剧项目
              </Button>
              <Button to="/history" variant="ghost" size="sm">
                科普历史
              </Button>
              <Button to="/settings" variant="ghost" size="sm">
                个人中心
              </Button>
            </div>
          </div>

          <div className="pf-drama-list-toolbar">
            <PillFilter options={TABS} value={tab} onChange={setTab} ariaLabel="资产分类" />
            <div className="pf-asset-toolbar-filters">
              <FilterSelect
                label="按项目筛选"
                value={projectId}
                options={projectOptions}
                onChange={setProjectId}
              />
              <label className="pf-drama-search">
                <span className="sr-only">搜索资产</span>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索名称或项目"
                />
              </label>
            </div>
          </div>
        </header>

        {error ? <BillingErrorNotice message={error} className="drama-error" /> : null}

        <div className="pf-asset-toolbar-meta">
          <p className="pf-muted" style={{ margin: 0 }}>
            {loading
              ? '加载中…'
              : `共 ${assets.length} 项 · 筛选后 ${filtered.length} 项 · 第 ${safePage}/${pageCount} 页`}
          </p>
        </div>

        {!loading && filtered.length === 0 ? (
          <div className="pf-empty-state is-compact">
            <p className="pf-muted">该分类暂无资产</p>
          </div>
        ) : (
          <>
            <div className="pf-asset-grid">
              {pageItems.map((asset) => {
                const kind = assetKind(asset)
                const mediaSrc = resolveDramaMediaUrl(asset.cover || (kind === 'voice' ? '' : asset.url))
                const projectLabel =
                  projectNameById.get(asset.project_id) || `项目 #${asset.project_id}`
                const previewUrl = voicePreviewUrl(asset)
                const isVoice = kind === 'voice'
                const playing = playingId === asset.id
                return (
                  <article key={asset.id} className="pf-asset-card">
                    <div className={`pf-asset-thumb is-${kind}`}>
                      {isVoice ? (
                        <button
                          type="button"
                          className={`pf-asset-play${playing ? ' is-playing' : ''}`}
                          onClick={() => toggleVoice(asset)}
                          disabled={!previewUrl}
                          title={previewUrl ? (playing ? '停止试听' : '试听音色') : '尚未合成试听'}
                        >
                          <span className="pf-asset-play-icon" aria-hidden>
                            {playing ? <Pause size={20} strokeWidth={2} /> : <Play size={20} strokeWidth={2} />}
                          </span>
                        </button>
                      ) : mediaSrc && isImageLike(asset) ? (
                        <button
                          type="button"
                          className="pf-asset-thumb-btn"
                          onClick={() =>
                            setLightbox({ src: mediaSrc, alt: asset.name || fileMeta(asset) })
                          }
                          title="查看大图"
                        >
                          <img src={mediaSrc} alt={asset.name || ''} />
                        </button>
                      ) : (
                        <span>{fileMeta(asset)}</span>
                      )}
                    </div>
                    <h3>{asset.name || '未命名'}</h3>
                    <p>
                      {fileMeta(asset)} · {projectLabel}
                    </p>
                    <div className="pf-asset-card-actions">
                      {previewUrl && !isVoice ? (
                        <CharacterVoicePreviewButton
                          url={previewUrl}
                          label={asset.name || undefined}
                          onError={setError}
                        />
                      ) : isVoice && !previewUrl ? (
                        <span className="pf-muted">尚未合成试听</span>
                      ) : null}
                      <Button to={`/drama/projects/${asset.project_id}`} variant="ghost" size="sm">
                        打开项目
                      </Button>
                    </div>
                  </article>
                )
              })}
            </div>
            <Pagination
              page={safePage}
              pageCount={pageCount}
              total={filtered.length}
              pageSize={pageSize}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              onPageSizeChange={(size) => {
                setPageSize(size)
                setPage(1)
              }}
              onChange={setPage}
              ariaLabel="资产库分页"
            />
          </>
        )}

        {lightbox ? (
          <DramaImageLightbox
            src={lightbox.src}
            alt={lightbox.alt}
            onClose={() => setLightbox(null)}
          />
        ) : null}
      </div>
    </AppShell>
  )
}
