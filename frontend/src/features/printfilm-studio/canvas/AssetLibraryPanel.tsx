import { useEffect, useMemo, useRef, useState } from 'react'
import { FolderOpen, ImagePlus, Search, Star, Upload, X, Film, Mic } from 'lucide-react'
import { dramaApi } from '../../../api/drama'
import type { ProjectAsset } from '../types'

export const ASSET_DRAG_TYPE = 'application/x-printfilm-asset'
export function assetMediaKind(asset: ProjectAsset): 'image' | 'video' | 'audio' {
  const kind = String(asset.asset_type || asset.type || '').toLowerCase()
  return kind === 'video' ? 'video' : kind === 'audio' || kind === 'voice' ? 'audio' : 'image'
}

function assetTags(asset: ProjectAsset): string[] {
  const tags = asset.params?.tags
  return Array.isArray(tags) ? tags.filter((tag): tag is string => typeof tag === 'string') : []
}

type Props = { projectId: number; assets: ProjectAsset[]; writable: boolean; acceptKinds?: readonly string[]; onClose: () => void; onUpload: () => void; onGenerate: () => void; onPick: (asset: ProjectAsset) => Promise<void> }

export function AssetLibraryPanel({ projectId, assets, writable, acceptKinds, onClose, onUpload, onGenerate, onPick }: Props) {
  const [source, setSource] = useState<'project' | 'library'>('project')
  const [library, setLibrary] = useState<ProjectAsset[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [tag, setTag] = useState('')
  const [page, setPage] = useState(1)
  const grid = useRef<HTMLDivElement>(null)
  const favoriteKey = `printfilm-studio:${projectId}:favorite-assets`
  const [favorites, setFavorites] = useState<number[]>(() => {
    try { const saved: unknown = JSON.parse(localStorage.getItem(favoriteKey) || '[]'); return Array.isArray(saved) ? saved.filter((id) => typeof id === 'number') : [] } catch { return [] }
  })
  useEffect(() => {
    if (source !== 'library') return
    let active = true
    setLoading(true); setError('')
    void dramaApi.listAssets().then((items) => { if (active) setLibrary(items) }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : '素材加载失败') }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [source])
  const items = source === 'project' ? assets : library
  const tags = useMemo(() => [...new Set(items.flatMap(assetTags))].sort(), [items])
  const visible = useMemo(() => items.filter((asset) => {
    if (acceptKinds && !acceptKinds.includes(assetMediaKind(asset))) return false
    if (query.trim() && !`${asset.name || ''} ${assetTags(asset).join(' ')}`.toLowerCase().includes(query.trim().toLowerCase())) return false
    if (tag && !assetTags(asset).includes(tag)) return false
    if (filter === 'favorite') return favorites.includes(asset.id)
    if (['image', 'video', 'audio'].includes(filter)) return assetMediaKind(asset) === filter
    if (filter !== 'all') return asset.type === filter
    return true
  }), [items, query, tag, filter, favorites, acceptKinds])
  const pages = Math.max(1, Math.ceil(visible.length / 24))
  const currentPage = Math.min(page, pages)
  const pageItems = visible.slice((currentPage - 1) * 24, currentPage * 24)
  useEffect(() => { setPage(1) }, [source, query, tag, filter])
  useEffect(() => { if (grid.current) grid.current.scrollTop = 0 }, [currentPage, source, query, tag, filter])
  const toggleFavorite = (id: number) => {
    const next = favorites.includes(id) ? favorites.filter((item) => item !== id) : [...favorites, id]
    setFavorites(next)
    try { localStorage.setItem(favoriteKey, JSON.stringify(next)) } catch { setError('浏览器无法保存收藏') }
  }
  const pick = async (asset: ProjectAsset) => {
    if (!writable || pending !== null) return
    setPending(asset.id); setError('')
    try { await onPick(asset) } catch (reason) { setError(reason instanceof Error ? reason.message : '导入素材失败') } finally { setPending(null) }
  }
  return <aside className="pf-library" aria-label="素材库">
    <header><FolderOpen size={20} /><b>素材库</b><span>{items.length}</span><button type="button" aria-label="关闭素材库" onClick={onClose}><X size={20} /></button></header>
    <div className="pf-library-actions"><button type="button" className={source === 'project' ? 'is-active' : ''} onClick={() => setSource('project')}>项目素材</button><button type="button" disabled={!writable} onClick={onUpload}><Upload size={16} />导入素材</button><button type="button" disabled={!writable} onClick={onGenerate}><ImagePlus size={16} />生成图片</button></div>
    <label className="pf-library-search"><Search size={17} /><input aria-label="搜索素材" placeholder="搜索素材" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
    <div className="pf-library-filters">{[['all', '全部'], ['favorite', '已收藏'], ['image', '图片'], ['video', '视频'], ['audio', '音频'], ['character', '角色'], ['scene', '场景'], ['prop', '道具'], ['voice', '声音'], ['material', '其他']].map(([id, label]) => <button type="button" key={id} className={filter === id ? 'is-active' : ''} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}</div>
    <label className="pf-library-tags">标签<select aria-label="素材标签" value={tag} onChange={(event) => setTag(event.target.value)}><option value="">全部标签</option>{tags.map((item) => <option key={item}>{item}</option>)}</select></label>
    <button type="button" className="pf-library-source" onClick={() => setSource((current) => current === 'project' ? 'library' : 'project')}><FolderOpen size={17} />{source === 'project' ? '从我的素材添加' : '返回项目素材'}</button>
    <p className="pf-library-hint">{writable ? acceptKinds ? '仅展示可用的参考素材，点击后新建节点并自动连线' : '点击放到画布中间，或拖到指定位置' : '只读模式：可浏览素材，获取编辑锁后添加'}</p>
    {error && <p className="pf-library-error" role="alert">{error}</p>}
    <div ref={grid} className="pf-library-grid" aria-busy={loading}>
      {loading ? <p className="pf-library-empty">正在加载素材…</p> : pageItems.map((asset) => {
        const kind = assetMediaKind(asset)
        const poster = asset.cover || (kind === 'image' ? asset.url : undefined)
        return <article key={asset.id} className="pf-library-card" draggable={writable} onDragStart={(event) => { event.dataTransfer.setData(ASSET_DRAG_TYPE, String(asset.id)); event.dataTransfer.effectAllowed = 'copy' }}>
          <button type="button" className="pf-library-pick" disabled={!writable || pending !== null} onClick={() => void pick(asset)} aria-label={`添加 ${asset.name || asset.id}`}>
            {poster ? <img src={poster} alt="" draggable={false} loading="lazy" /> : kind === 'video' ? <Film size={32} /> : kind === 'audio' ? <Mic size={32} /> : <ImagePlus size={32} />}
            <span>{pending === asset.id ? '正在添加…' : asset.name || `素材 #${asset.id}`}</span>
          </button>
          <button type="button" className={`pf-library-star${favorites.includes(asset.id) ? ' is-active' : ''}`} onClick={() => toggleFavorite(asset.id)} aria-label={`${favorites.includes(asset.id) ? '取消收藏' : '收藏'} ${asset.name || asset.id}`} aria-pressed={favorites.includes(asset.id)}><Star size={15} /></button>
        </article>
      })}
      {!loading && visible.length === 0 && <p className="pf-library-empty">{items.length ? '没有符合筛选条件的素材' : '暂无素材，可导入文件或生成图片'}</p>}
    </div>
    <nav className="pf-library-pagination" aria-label="素材分页"><button disabled={loading || currentPage === 1} onClick={() => setPage(currentPage - 1)}>上一页</button><span aria-live="polite">{currentPage} / {pages} 页 · {visible.length} 项</span><button disabled={loading || currentPage === pages} onClick={() => setPage(currentPage + 1)}>下一页</button></nav>
  </aside>
}
