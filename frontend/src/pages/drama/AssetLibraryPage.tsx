/** 资产目录：项目素材、分镜与成片，以及无项目的独立生成结果。 */
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { Pause, Play, Image } from 'lucide-react'
import { AssetBanner, AssetCard, AssetEmpty, AssetGrid, AssetSearch } from '../../components/assets/AssetLibrary'
import MediaLibraryFilters, { type MediaLibraryFilter } from '../../components/assets/MediaLibraryFilters'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import AppShell from '../../components/layout/AppShell'
import Button from '../../components/ui/Button'
import FilterSelect from '../../components/ui/FilterSelect'
import Pagination from '../../components/ui/Pagination'
import { api } from '../../api'
import { CharacterVoicePreviewButton } from '../../components/drama/CharacterVoicePreviewButton'
import { dramaApi, resolveDramaMediaUrl, type MediaLibraryItem, type MediaLibraryPage } from '../../api/drama'
import { readAssetVoiceBinding } from './CharacterVoiceBindModal'
import { AssetDetailDialog } from '../../components/assets/AssetDetailDialog'
import { DRAMA_VOICE_BINDING_ENABLED } from '../../lib/dramaVoiceBinding'
import { pageCountOf } from '../../lib/pagination'
import { subscribeWorkspace, workspaceScope } from '../../features/teams/workspaceScope'
import RequireAuth from './RequireAuth'
import './drama.css'

const PAGE_SIZE = 8
type LibraryProject = { id: number; title: string; kind: 'drama' | 'short_video' }

/** 漫剧与短视频使用独立项目编号空间，不能只传数字筛选。 */
function projectSelection(value: string): { unassigned: boolean; projectId?: number; projectKind?: LibraryProject['kind'] } {
  const [kind, rawId] = value.split(':')
  const id = Number(rawId)
  return {
    unassigned: value === 'unassigned',
    ...(Number.isInteger(id) && id > 0 && (kind === 'drama' || kind === 'short_video')
      ? { projectId: id, projectKind: kind } : {}),
  }
}

export default function AssetLibraryPage() {
  const workspaceEpoch = useSyncExternalStore(subscribeWorkspace, () => workspaceScope.epoch)
  return <RequireAuth><AssetLibraryInner key={workspaceEpoch} /></RequireAuth>
}

function previewAudio(asset: MediaLibraryItem): string {
  return asset.media_kind === 'audio' ? asset.url || '' : readAssetVoiceBinding(asset)?.url || ''
}

function AssetLibraryInner() {
  const [listing, setListing] = useState<MediaLibraryPage>({ items: [], meta: { total: 0, total_all: 0, page: 1, page_size: PAGE_SIZE } })
  const [projects, setProjects] = useState<LibraryProject[]>([])
  const [projectId, setProjectId] = useState('')
  const [mediaFilter, setMediaFilter] = useState<MediaLibraryFilter>({ kind: 'image', imageType: 'all', generationStatus: 'all' })
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = PAGE_SIZE
  const [playingKey, setPlayingKey] = useState<string | null>(null)
  const [selectedAsset, setSelectedAsset] = useState<MediaLibraryItem | null>(null)
  const [error, setError] = useState('')
  const [playbackError, setPlaybackError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const playbackEpoch = useRef(0)

  useEffect(() => {
    let active = true
    /** 分别读取两类项目，团队范围不列出个人短视频项目。 */
    async function loadProjects(kind: LibraryProject['kind']) {
      const rows: LibraryProject[] = []
      let page = 1
      while (active) {
        const result = kind === 'drama' ? await dramaApi.listProjects({ page, page_size: 50 }) : await api.listProjects({ page, page_size: 50 })
        if (!active) return []
        rows.push(...result.items.map((project) => ({ id: project.id, title: project.title || '未命名项目', kind })))
        if (rows.length >= result.meta.total || result.items.length === 0) break
        page += 1
      }
      return rows
    }
    const kinds: LibraryProject['kind'][] = ['drama', 'short_video']
    void Promise.allSettled(kinds.map(loadProjects)).then((results) => {
      if (active) setProjects(results.flatMap((result) => result.status === 'fulfilled' ? result.value : []))
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => { setSearch(query.trim().slice(0, 200)); setPage(1) }, 250)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    dramaApi.listLibraryAssets({ type: mediaFilter.kind === 'image' && mediaFilter.imageType !== 'all' ? mediaFilter.imageType : mediaFilter.kind,
      mediaKind: mediaFilter.kind, generationStatus: mediaFilter.generationStatus, ...projectSelection(projectId), q: search, page, pageSize }, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setListing(result) })
      .catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '加载失败') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [mediaFilter, projectId, search, page, pageSize, revision])

  useEffect(() => {
    playbackEpoch.current += 1
    audioRef.current?.pause()
    setPlayingKey(null)
    setPlaybackError('')
    return () => { playbackEpoch.current += 1; audioRef.current?.pause() }
  }, [mediaFilter, projectId, search, page, pageSize])

  const projectOptions = useMemo(() => [
    { value: '', label: '全部项目' }, { value: 'unassigned', label: '未关联项目' },
    ...projects.map((project) => ({ value: `${project.kind}:${project.id}`, label: `${project.kind === 'drama' ? '漫剧项目' : 'AI短视频'} · ${project.title}` })),
  ], [projects])
  const pageCount = pageCountOf(listing.meta.total, pageSize)

  async function toggleAudio(asset: MediaLibraryItem) {
    const epoch = ++playbackEpoch.current
    audioRef.current?.pause()
    setPlaybackError('')
    if (playingKey === asset.key) { setPlayingKey(null); return }
    const src = resolveDramaMediaUrl(previewAudio(asset))
    if (!src) return
    const audio = audioRef.current || new Audio()
    audioRef.current = audio
    audio.src = src
    audio.onended = () => { if (epoch === playbackEpoch.current) setPlayingKey(null) }
    setPlayingKey(asset.key)
    try { await audio.play() }
    catch { if (epoch === playbackEpoch.current) { setPlayingKey(null); setPlaybackError('播放失败，请重试') } }
  }

  return <AppShell active="assets">
    <div className="drama-page pf-library-panel pf-digital-library">
      <header className="pf-library-page-head">
        <div className="pf-library-heading"><div><h1>数字资产库</h1><p className="pf-muted" style={{ margin: '0.35rem 0 0' }}>按图片、视频、音频浏览，可筛选已生成与未生成资产；图片可进一步筛选角色、场景与道具</p></div>
          <span className="pf-library-count"><Image size={14} />{listing.meta.total} 项资产</span>
        </div>
        <AssetBanner>项目素材、分镜视频与成片汇集在这里，按来源项目筛选；独立生成的素材也可直接预览与下载。</AssetBanner>
        <div className="pf-library-toolbar pf-library-toolbar--hierarchical">
          <MediaLibraryFilters value={mediaFilter} onChange={value => { setMediaFilter(value); setPage(1) }} />
          <div className="pf-library-toolbar-end">
            <FilterSelect label="按项目筛选" value={projectId} options={projectOptions} onChange={(value) => { setProjectId(value); setPage(1) }} />
            <AssetSearch value={query} onChange={setQuery} placeholder="搜索资产名称或项目" />
          </div>
        </div>
      </header>
      {error && <div role="alert"><BillingErrorNotice message={error} className="drama-error" /><Button size="sm" onClick={() => setRevision((value) => value + 1)}>重新加载</Button></div>}
      {playbackError && <p role="alert" className="drama-error">{playbackError}</p>}
      <div className="pf-library-meta"><p className="pf-muted" style={{ margin: 0 }} role="status">{loading ? '加载中…' : `共 ${listing.meta.total_all} 项 · 筛选后 ${listing.meta.total} 项 · 第 ${listing.meta.page}/${pageCount} 页`}</p></div>
      {loading ? <div className="pf-library-empty" aria-busy="true">正在加载资产…</div> : error ? null : listing.items.length === 0 ? <AssetEmpty /> : <>
        <AssetGrid>{listing.items.map((asset) => {
          const audio = asset.media_kind === 'audio'
          const preview = previewAudio(asset)
          const playing = playingKey === asset.key
          const sourceLabel = asset.source_kind === 'drama_fragment' ? '分镜视频' : asset.source_kind === 'short_video' ? 'AI短视频' : asset.source_kind === 'task' ? '生成结果' : asset.source_kind === 'tool' && !asset.project_id ? '独立生成' : '项目素材'
          const workspaceLabel = asset.project_id ? '项目资产' : '个人资产'
          return <AssetCard key={asset.key} asset={asset} subtitle={asset.project_title || (asset.project_id ? '项目素材' : '未关联项目')} footer={`${sourceLabel} · ${workspaceLabel}`} updatedAt={asset.updated_at} onOpen={() => setSelectedAsset(asset)}
            status={audio ? playing ? '正在试听' : preview ? '可试听' : '待合成' : undefined}
            actions={<>
              {audio && preview && <button type="button" className="pf-btn pf-btn-sm" onClick={() => void toggleAudio(asset)} aria-label={playing ? '停止试听' : '试听音频'}>{playing ? <Pause size={14} /> : <Play size={14} />}{playing ? '停止试听' : '试听'}</button>}
              {!audio && DRAMA_VOICE_BINDING_ENABLED && preview && <CharacterVoicePreviewButton url={preview} label={asset.name || undefined} onError={setPlaybackError} />}
              {asset.project_url ? <Button to={asset.project_url} variant="ghost" size="sm">打开项目</Button> : <Button size="sm" onClick={() => setSelectedAsset(asset)}>查看素材</Button>}
            </>} />
        })}</AssetGrid>
        <Pagination page={listing.meta.page} pageCount={pageCount} total={listing.meta.total} pageSize={pageSize} onChange={setPage} ariaLabel="数字资产库分页" />
      </>}
      {selectedAsset && <AssetDetailDialog asset={selectedAsset} audioUrl={selectedAsset.media_kind !== 'audio' ? previewAudio(selectedAsset) : undefined} onClose={() => setSelectedAsset(null)} actions={selectedAsset.project_url ? <Button to={selectedAsset.project_url} variant="dark">打开来源项目</Button> : undefined} />}
    </div>
  </AppShell>
}
