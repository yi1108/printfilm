/** 全局资产库选择弹窗：跨项目挑选图片资产（导入或应用到节点） */
import { useEffect, useMemo, useState } from 'react'
import { dramaApi, type DramaAsset } from '../../api/drama'
import { filterDramaLibraryAssets, isDramaLibraryAsset } from '../../lib/dramaLibraryAssets'
import { DRAMA_VOICE_BINDING_ENABLED } from '../../lib/dramaVoiceBinding'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import Modal from '../../components/ui/Modal'
import { AssetBanner, AssetCard, AssetEmpty, AssetGrid, AssetSearch, AssetTypeFilter } from '../../components/assets/AssetLibrary'
import { TeamPagination } from '../../features/teams/TeamPagination'
import './drama.css'

export type GlobalAssetTabKey = 'character' | 'scene' | 'prop' | 'voice' | 'all'

type Props = {
  open: boolean
  onClose: () => void
  /** 当前项目 ID，用于标注来源与可选排除本项 */
  projectId: number
  /** 默认 Tab；canvas 场景可传 all */
  defaultTab?: GlobalAssetTabKey
  /** 限定可选资产 type 列表；不传则按 Tab 筛选 */
  allowedTypes?: string[]
  /** 标题 */
  title?: string
  /** 确认按钮文案 */
  confirmLabel?: string
  onPick: (asset: DramaAsset) => void | Promise<void>
}

const TABS: Array<{ key: GlobalAssetTabKey; label: string }> = [
  { key: 'character', label: '角色' },
  { key: 'scene', label: '场景' },
  { key: 'prop', label: '道具' },
  ...(DRAMA_VOICE_BINDING_ENABLED ? [{ key: 'voice' as const, label: '音色' }] : []),
]

// 资产是否匹配 Tab
function matchAssetTab(asset: DramaAsset, tab: GlobalAssetTabKey): boolean {
  if (!isDramaLibraryAsset(asset)) return false
  if (tab === 'all') return true
  const t = (asset.type || '').toLowerCase()
  if (tab === 'voice') return t === 'voice'
  return t === tab
}

// asset visible in picker (voice/audio with url; image needs cover/url)
function hasMedia(asset: DramaAsset): boolean {
  const t = (asset.type || '').toLowerCase()
  if (t === 'voice' || t === 'audio') return Boolean(asset.url || asset.cover)
  return Boolean(asset.url || asset.cover)
}

// 渲染全局资产库选择弹窗（使用全局 Modal）
export function GlobalAssetPickerModal({
  open,
  onClose,
  projectId,
  defaultTab = 'character',
  allowedTypes,
  title = '从资产库选择',
  confirmLabel = '确认使用',
  onPick,
}: Props) {
  /*
   * allAssets 用户全部项目资产
   * tab 当前分类
   * query 搜索词
   * selectedId 选中资产
   * loading 加载中
   * busy 提交中
   * error 错误文案
   */
  const [allAssets, setAllAssets] = useState<DramaAsset[]>([])
  const [tab, setTab] = useState<GlobalAssetTabKey>(
    defaultTab === 'voice' && !DRAMA_VOICE_BINDING_ENABLED ? 'character' : defaultTab,
  )
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const allowedTypesKey = allowedTypes?.join(',') || ''

  useEffect(() => {
    if (!open) return
    setTab(
      defaultTab === 'voice' && !DRAMA_VOICE_BINDING_ENABLED ? 'character' : defaultTab,
    )
    setQuery('')
    setSelectedId(null)
    setError('')
    setPage(1)
  }, [open, defaultTab])

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    let active = true
    setLoading(true); setError('')
    const timer = window.setTimeout(() => {
      void dramaApi.listAssets(undefined, { libraryOnly: true }).then(rows => {
        if (active) { setAllAssets(filterDramaLibraryAssets(rows)); setTotal(0) }
      }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : '资产库加载失败') }).finally(() => { if (active) setLoading(false) })
    }, 180)
    return () => { active = false; controller.abort(); window.clearTimeout(timer) }
  }, [open, projectId, query, tab, page, allowedTypesKey])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return allAssets.filter((asset) => {
      if (!hasMedia(asset)) return false
      if (allowedTypes?.length) {
        const t = (asset.type || '').toLowerCase()
        if (!allowedTypes.includes(t)) {
          return false
        }
      } else if (!matchAssetTab(asset, tab)) {
        return false
      }
      if (!q) return true
      const name = (asset.name || '').toLowerCase()
      return name.includes(q) || String(asset.project_id).includes(q)
    })
  }, [allAssets, allowedTypes, query, tab])

  // 确认选用资产
  async function handleConfirm() {
    const picked = allAssets.find((a) => a.id === selectedId)
    if (!picked || busy) return
    setBusy(true)
    setError('')
    try {
      await onPick(picked)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '应用失败')
    } finally {
      setBusy(false)
    }
  }

  const showTabs = !allowedTypes?.length && defaultTab !== 'all'

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="lg"
      dismissible={!busy}
      className="drama-global-picker-modal"
      footer={
        <>
          <button type="button" className="pf-btn" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button
            type="button"
            className="pf-btn pf-btn-lime"
            disabled={!selectedId || busy}
            onClick={() => void handleConfirm()}
          >
            {busy ? '处理中…' : confirmLabel}
          </button>
        </>
      }
    >
      <AssetBanner>展示当前空间内的可用资产，跨项目复用会复制到当前项目。</AssetBanner>
      <div className="pf-library-toolbar">
        {showTabs && <AssetTypeFilter options={TABS.map((item) => ({ value: item.key, label: item.label }))} value={tab} onChange={(value) => { setTab(value); setPage(1); setSelectedId(null) }} />}
        <AssetSearch value={query} onChange={(value) => { setQuery(value); setPage(1); setSelectedId(null) }} placeholder="搜索名称或项目 ID" />
      </div>

      {error ? <BillingErrorNotice message={error} className="drama-error" /> : null}
      {loading ? <p className="drama-muted">加载资产库…</p> : null}

      <AssetGrid picker>
        {filtered.map((asset) => <AssetCard
          key={asset.id}
          asset={asset}
          selected={selectedId === asset.id}
          subtitle={asset.project_id === projectId ? '本项目' : `项目 #${asset.project_id}`}
          footer={asset.type === 'voice' ? asset.url ? '已合成音色' : '未合成音色' : '可复制到当前项目'}
          onOpen={() => setSelectedId(asset.id)}
        />)}
      </AssetGrid>
      <TeamPagination page={page} total={total} onChange={setPage} />
      {!loading && filtered.length === 0 ? (
        <AssetEmpty>当前分类下暂无可用媒体，请先在项目中生成资产。</AssetEmpty>
      ) : null}
    </Modal>
  )
}

// 将外部资产复制到当前项目（导入）
export async function importGlobalAssetToProject(
  projectId: number,
  source: DramaAsset,
): Promise<DramaAsset> {
  if (!source.url && !source.cover) {
    throw new Error('所选资产没有可用图片')
  }
  return dramaApi.copyAsset(source, projectId)
}

// 画布 kind → 资产 type 筛选
export function canvasKindToLibraryTypes(kind: string): string[] {
  if (kind === 'character') return ['character']
  if (kind === 'scene') return ['scene']
  if (kind === 'audio') return DRAMA_VOICE_BINDING_ENABLED ? ['audio', 'voice'] : ['audio']
  return ['prop', 'image']
}
