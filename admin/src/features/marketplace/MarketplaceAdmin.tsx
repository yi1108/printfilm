import { points } from '../../lib/points'
import EngagementOperations from './EngagementOperations'
import UnlockOrders from './UnlockOrders'
import ContentRevenueForm from './ContentRevenueForm'
import { CurationControls } from './CurationOperations'
import CategoryForm from './CategoryForm'
import { useEffect, useState, type FormEvent } from 'react'
import { request, assetFile, assetUrl, letterFile, useMarketplaceStatus, type Item, type Listing } from './api'
import { fieldStatusLabel, recordDetailsTitle, recordStatus, statusLabel, statusOptions } from './presentation'
import { PaginationBar } from '@/components/PaginationBar'
import { AdminModal } from '@/components/admin/AdminModal'
import { RefreshCw, Film, ShieldCheck, Users, Flag, CircleAlert, MessageCircle, Inbox } from 'lucide-react'
import './marketplace-admin.css'

// 独立下游运营工作台；不复用或改变原作品审核页。
const businessTabs = { engagement: '作品运营', works: '作品审核', series: '短剧审核', recruits: '招募审核', reports: '举报处理', support: '客服配置', categories: '作品分类', revenue: '平台分成', app: '视频解锁订单' }
const maintenanceTabs = { previews: '作品试看任务', submissions: '历史投稿记录', jobs: '历史媒体任务', orders: '平台订单', entitlements: '永久播放权益', ledger: '收益账本', payouts: '人工打款', events: '操作记录' }
const tabs = { ...businessTabs, ...maintenanceTabs }
const statusNames: Record<string, string> = { preview_failed: '短试看生成失败', original: '免费原片', missing: '未生成', running: '处理中', done: '已完成', draft: '草稿', pending: '待审核', approved: '已通过', rejected: '已驳回', ready: '已就绪', processing: '处理中', failed: '失败', open: '征集中', closed: '已关闭', expired: '已到期', pending_materials: '待材料', reviewing: '材料核验中', supplement: '待补正', applying: '办理中', certificated: '已取得证书', cancelled: '已取消', to_review: '待看', candidate: '候选', not_selected: '不采用', active: '有效权益', inactive: '已停用', printfilm: 'PRINTFILM 生成', external: '其他平台生成', existing: '已有证书', self_service: '自行办理', assisted: '客服协办', free: '免费公开', copyright_contact: '版权出售收益', platform_unlock: '平台投放收益', work: '单视频作品', series: '短剧', series_episode: '短剧分集', recruit: '招募需求', submission: '历史投稿', manual: '手动上传', drama_import: '漫剧导入', alipay: '支付宝', wxpay: '微信支付' }
const names: Record<string, string> = { app_editions: 'App 投放版本', preview_status: '试看状态', preview_error: '试看错误', playback_status: '播放版本', playback_error: '播放错误', work_id: '作品编号', id: '编号', owner_id: '用户编号', user_id: '购买用户编号', asset_id: '媒体编号', publication_id: '发布版本编号', publication_version: '发布版本', episode_id: '分集编号', order_id: '订单编号', content_type: '内容类型', content_id: '内容编号', publication_owner_id: '创作者编号', active: '权益有效', version: '内容版本', title: '标题', description: '说明', price_fen: '参考价（元）', sale_type: '收益方式', copyright_price_fen: '版权参考价（元）', unlock_price_fen: '解锁价（积分）', free_episode_count: '前置免费集数', episode_count: '分集数量', platform_share_bps: '平台抽成比例（万分比）', share_bps: '本作品平台抽成（万分比）', gross_fen: '订单金额（元）', platform_fen: '平台收益（元）', creator_fen: '创作者收益（元）', amount_fen: '金额（元）', budget_fen: '预算（元）', quote_fen: '报价（元）', category: '分类', source: '来源', source_type: '来源类型', source_snapshot: '导入来源快照', license_scope: '授权意向', audit_status: '内容审核', basic_status: '基础权属', full_status: '完整权属', reason: '审核原因', listed: '作者上架', blocked: '封禁', author: '作者', holder: '权利人', relationship: '发布人与权利人的关系', acquisition: '权利取得方式', scope: '授权范围', third_party: '第三方授权', institution: '登记机构', certificate_number: '证书号', ai_platform_license: 'AI平台许可', ai_generation_record: '生成记录', human_contribution: '人工贡献', official_reference: '申请编号', route: '办理方式', status: '状态', settlement_status: '结算状态', out_trade_no: '订单号', trade_no: '第三方交易号', paid_at: '付款时间', pay_type: '支付渠道', operator_id: '操作人编号', note: '备注', statement: '举报说明', contact: '联系渠道', resolution: '处理结果', target_type: '对象类型', target_id: '对象编号', requirements: '交付要求', wanted_count: '征集数量', deadline_at: '截止时间', valid_until: '授权截止', fingerprint: '文件指纹', filename: '文件名', selection: '筛选标记', withdrawn: '撤回', action: '操作', actor_id: '操作人', attempts: '尝试次数', error: '错误说明', media_status: '媒体状态', state: '业务状态', tags: '标签', authorization_id: '授权函编号', authorization_version: '授权条款版本', authorization_signer: '签署人', copyright_statement: '版权声明', dispute_ack: '版权声明已确认' }

// 按可读字段渲染审核材料，原片和证书另经鉴权打开。
function Summary({ item, kind }: { item: Item; kind: string }) {
  const details = typeof item.details === 'object' && item.details !== null ? item.details : {}
  return <dl className="market-ops-summary">
    {Object.entries(item).filter(([key, value]) => names[key] && !['basic_status', 'full_status', 'id', 'title', 'audit_status', 'status'].includes(key) && value !== null && value !== '').map(([key, value]) => <div key={key}><dt>{names[key]}</dt><dd>{typeof value === 'boolean' ? value ? '是' : '否' : key === 'unlock_price_fen' ? points(Number(value)) : ['price_fen', 'copyright_price_fen', 'unlock_price_fen', 'budget_fen', 'quote_fen', 'gross_fen', 'platform_fen', 'creator_fen', 'amount_fen'].includes(key) ? `¥${(Number(value) / 100).toFixed(2)}` : Array.isArray(value) ? (key === 'app_editions' ? value.map(edition => edition === 'domestic' ? '国内版' : edition === 'international' ? '国际版' : String(edition)) : value).join('、') || '—' : typeof value === 'object' ? JSON.stringify(value) : key === 'preview_status' && value === 'none' ? (isFreeItem(item) ? '无需试看' : '未生成') : key === 'status' ? statusLabel(kind, value) : fieldStatusLabel(key, value) || statusNames[String(value)] || String(value)}</dd></div>)}
    {Object.entries(details).filter(([key, value]) => names[key] && value !== '' && value !== null && value !== undefined).map(([key, value]) => <div key={key}><dt>{key === 'dispute_ack' ? '版权声明已确认' : names[key] || key}</dt><dd>{typeof value === 'boolean' ? value ? '是' : '否' : fieldStatusLabel(key, value) || statusNames[String(value)] || String(value)}</dd></div>)}
  </dl>
}

// 直接从服务端签名，不将原始 OSS key 传到页面。
function FileLink({ id, label, purpose = 'original', video = false }: { id: number; label: string; purpose?: string; video?: boolean }) {
  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState<{ url: string; image: boolean; pdf: boolean } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url) }, [preview])
  async function open() {
    try {
      if (video) { setUrl(await assetUrl(id, purpose)); setError(''); return }
      const blob = await assetFile(id, purpose)
      const type = blob.type
      setPreview(current => { if (current) URL.revokeObjectURL(current.url); return { url: URL.createObjectURL(blob), image: type.startsWith('image/'), pdf: type.includes('pdf') } })
      setError('')
    } catch (e) { setError((e as Error).message) }
  }
  return <div className="market-ops-file"><button type="button" onClick={() => { void open() }}>{label}</button>{url && video && <video src={url} controls className="my-3 max-h-[500px] w-full" />}{preview?.image && <img src={preview.url} alt={label} />}{preview?.pdf && <iframe className="market-ops-file-frame" src={preview.url} title={label} />}{preview && !preview.image && !preview.pdf && <p>这个文件暂时不能在页面里预览。</p>}{error && <p role="alert">{error}</p>}</div>
}

function WorkPreviewLink({ id }: { id: number }) {
  const [url, setUrl] = useState(''); const [error, setError] = useState('')
  return <div className="market-ops-file"><button type="button" onClick={async () => { try { setUrl((await request<{ url: string }>(`/api/marketplace/media/work/${id}/preview`)).url); setError('') } catch (e) { setError((e as Error).message) } }}>查看短试看</button>{url && <video src={url} controls className="my-3 max-h-[500px] w-full" />}{error && <p role="alert">{error}</p>}</div>
}
function AuthorizationLink({ details }: { details: unknown }) {
  const id = details && typeof details === 'object' && 'authorization_id' in details ? Number(details.authorization_id) : 0
  const [preview, setPreview] = useState<{ url: string; image: boolean } | null>(null)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => () => { if (preview?.url) URL.revokeObjectURL(preview.url) }, [preview?.url])
  if (!id) return null
  async function openLetter() {
    setLoading(true); setError('')
    try {
      const blob = await letterFile(id)
      const url = URL.createObjectURL(blob)
      setPreview(current => { if (current?.url) URL.revokeObjectURL(current.url); return { url, image: blob.type.startsWith('image/') } })
      setOpen(true)
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  function downloadLetter() {
    if (!preview) return
    const link = document.createElement('a')
    link.href = preview.url
    link.download = preview.image ? '授权函.png' : '授权函.pdf'
    link.click()
  }
  return <div className="market-ops-file">
    <button type="button" onClick={() => void openLetter()} disabled={loading}>{loading ? '加载授权函…' : '预览授权函'}</button>
    {preview && <button type="button" onClick={downloadLetter}>下载授权函</button>}
    {error && <p role="alert">{error}</p>}
    <AdminModal open={open} onOpenChange={setOpen} title="授权函预览" subtitle="用于核对授权材料与存档，不会自动下载文件。" size="xl" className="market-ops-letter-modal" bodyClassName="market-ops-letter-modal-body">
      <div className="market-ops-letter-preview">
        <div className="market-ops-letter-preview-head"><strong>PRINTFILM 作品授权函</strong><span>{preview?.image ? '图片文件' : 'PDF 文件'} · 在线查看</span></div>
        <div className="market-ops-letter-preview-canvas">
          {preview ? (preview.image ? <img className="market-ops-letter-image" src={preview.url} alt="已签署授权函" /> : <iframe className="market-ops-letter-frame" src={preview.url} title="授权函预览" />) : <p>授权函尚未加载。</p>}
        </div>
      </div>
      {preview && <div className="market-ops-letter-modal-actions"><button type="button" onClick={downloadLetter}>下载授权函</button></div>}
    </AdminModal>
  </div>
}

function CoverImage({ id }: { id?: number }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!id) return
    let active = true
    assetUrl(id, 'cover').then(value => { if (active) setUrl(value) }).catch(() => {})
    return () => { active = false }
  }, [id])
  return url ? <img src={url} alt="" /> : <span><Film size={28} /></span>
}

function Playback({ assetId }: { assetId?: number }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    if (!assetId) return
    let active = true
    assetUrl(assetId, 'original').then(value => { if (active) setUrl(value) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [assetId])
  if (!assetId) return <p>没有可播放的原片</p>
  if (error) return <p role="alert">{error}</p>
  if (!url) return <p role="status">正在加载原片…</p>
  return <video src={url} controls />
}

function auditLabel(item: Item) {
  const name = statusNames[String(item.audit_status || 'draft')] || String(item.audit_status || '草稿')
  return item.listed ? `${name} · 已上架` : name
}

function isFreeItem(item: Item) {
  return item.sale_type === 'free'
}

function priceLabel(item: Item, series = false, recruit = false) {
  if (recruit) return `¥${(Number(item.budget_fen || 0) / 100).toFixed(2)}`
  if (isFreeItem(item)) return '免费'
  if (series && item.sale_type === 'platform_unlock') return '按集解锁'
  const fen = series ? Number(item.copyright_price_fen ?? item.price_fen ?? 0) : Number(item.sale_type === 'platform_unlock' ? item.unlock_price_fen : item.price_fen)
  return `¥${(fen / 100).toFixed(2)}`
}

function ReviewGallery({ items, series, recruit = false, onOpen }: { items: Item[]; series: boolean; recruit?: boolean; onOpen: (item: Item) => void }) {
  if (!items.length) return null
  return <div className="market-ops-gallery">{items.map(item => <button type="button" className="market-ops-card" key={item.id} onClick={() => onOpen(item)}>
    <span className="market-ops-card-cover"><CoverImage id={typeof item.cover_asset_id === 'number' ? item.cover_asset_id : undefined} /><em className={`market-ops-badge status-${String(item.audit_status || 'draft')}`}>{auditLabel(item)}</em></span>
    <span className="market-ops-card-body">
      <em>{recruit ? '招募' : series ? '短剧' : String(item.category || '作品')}</em>
      <strong>{String(item.title || '未命名作品')}</strong>{!recruit && <span className="market-ops-curation-tags">{item.is_pinned ? <span>置顶</span> : null}{item.is_featured ? <span>精选</span> : null}</span>}
      <small><i>{String(item.author || '创').slice(0, 1)}</i>{String(item.author || `用户 #${item.owner_id || ''}`)}</small>
      <b>{priceLabel(item, series, recruit)}{recruit ? <span>/ 条预算 · 征集 {String(item.wanted_count || 0)} 条</span> : series ? <span>{Number(item.episode_count || (Array.isArray(item.episodes) ? item.episodes.length : 0))} 集{Number(item.free_episode_count) > 0 ? ` · 前${item.free_episode_count}集免费` : ''}</span> : !isFreeItem(item) && <span>{item.sale_type === 'platform_unlock' ? '解锁价' : '参考价'}</span>}</b>
    </span>
  </button>)}</div>
}

function ReviewStage({ item, series, recruit = false, onBack, onReview }: { item: Item; series: boolean; recruit?: boolean; onBack: () => void; onReview: (event: FormEvent<HTMLFormElement>, item: Item) => void }) {
  const episodes = Array.isArray(item.episodes) ? item.episodes as Item[] : []
  const [episodeId, setEpisodeId] = useState<number | undefined>(typeof episodes[0]?.id === 'number' ? episodes[0].id : undefined)
  const episode = episodes.find(entry => entry.id === episodeId)
  const assetId = series ? (typeof episode?.asset_id === 'number' ? episode.asset_id : undefined) : (typeof item.asset_id === 'number' ? item.asset_id : undefined)
  const coverId = typeof item.cover_asset_id === 'number' ? item.cover_asset_id : undefined
  return <section className="market-ops-stage">
    <button type="button" className="market-ops-back" onClick={onBack}>返回列表</button>
    <div className="market-ops-stage-layout">
      <div className="market-ops-stage-player">{recruit ? <CoverImage id={coverId} /> : <><p className="market-ops-original-note">管理员审核完整原片</p><Playback key={assetId || 'none'} assetId={assetId} /></>}</div>
      <aside>
        <span className={`market-ops-badge status-${String(item.audit_status || 'draft')}`}>{auditLabel(item)}</span>
        <h2>{String(item.title || '未命名作品')}</h2>
        <p>{String(item.author || '创作者')} · {priceLabel(item, series, recruit)}{series ? ` · ${episodes.length} 集` : ''}{recruit ? ` · 征集 ${String(item.wanted_count || 0)} 条` : ''}</p>
        <p>{String(item.description || '暂无简介')}</p>{!recruit && <CurationControls targetType={series ? 'series' : 'work'} targetId={item.id} />}
        {!recruit && <ContentRevenueForm key={`${series ? 'series' : 'work'}-${item.id}-${item.version}`} item={item} kind={series ? 'series' : 'work'} />}
        {series && episode && <ContentRevenueForm key={`episode-${episode.id}-${episode.version}`} item={episode} kind="series_episode" />}
        {recruit && <p>交付要求：{String(item.requirements || '未填写')}</p>}
        <p>授权意向：{String(item.license_scope || '未填写')}</p>
        {recruit && <p>截止时间：{String(item.deadline_at || '未填写')}</p>}
        {series && <div className="market-ops-episode-picks">{episodes.map(episode => <button type="button" key={episode.id} aria-pressed={episode.id === episodeId} onClick={() => setEpisodeId(Number(episode.id))}>第 {String(episode.episode_no)} 集</button>)}</div>}
        {!recruit && <AuthorizationLink details={series ? episodes.find(episode => episode.id === episodeId)?.details : item.details} />}
        {item.audit_status === 'pending' ? <form className="market-ops-review" onSubmit={event => onReview(event, item)}><h3>审核处理</h3><p>{recruit ? '看完需求说明和参考图后，给出这次审核结论。' : '看完播放文件和版权材料后，给出这次审核结论。'}</p>{!recruit && <div className="grid gap-3"><section><h3>内容检查</h3><label><input name="checks" value="content" type="checkbox" /> 已检查视频、封面、标题和简介</label></section><section><h3>版权检查</h3><label><input name="checks" value="copyright" type="checkbox" /> 已检查授权函或证书编号、证明材料及版权声明</label></section></div>}<label className="block">审核依据及原因<textarea name="reason" required maxLength={3000} className="block w-full rounded border bg-background p-2" /></label><div className="flex gap-3"><button type="submit" value="approved" className="market-ops-approve">通过该版本</button><button type="submit" value="rejected" className="market-ops-reject">驳回该版本</button></div></form> : <p>这个版本不是待审核状态。</p>}
      </aside>
    </div>
  </section>
}

function PayoutStatusForm({ item, onSaved }: { item: Item; onSaved: () => void }) {
  const [status, setStatus] = useState(String(item.status || 'pending'))
  const [note, setNote] = useState(String(item.note || ''))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      await request(`/api/admin/marketplace/payouts/${item.id}`, 'PATCH', { owner_id: Number(item.owner_id), amount_fen: Number(item.amount_fen), status, note })
      onSaved()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <form className="market-ops-inline-form" onSubmit={save}>
    <label>打款状态<select value={status} onChange={event => setStatus(event.target.value)} disabled={status === 'paid'}><option value="pending">待打款</option><option value="paid">已打款</option><option value="failed">打款失败</option></select></label>
    <label>备注<input value={note} maxLength={3000} onChange={event => setNote(event.target.value)} /></label>
    <button type="submit" disabled={busy || status === String(item.status || '')}>{busy ? '保存中…' : '更新打款记录'}</button>
    {error && <span role="alert">{error}</span>}
  </form>
}


// 独立工作台含分页、错误态、敏感材料检查和明确原因输入。
export default function MarketplaceAdmin() {
  const availability = useMarketplaceStatus()
  const enabled = availability.enabled
  const [kind, setKind] = useState<keyof typeof tabs>('works')
  const [listing, setListing] = useState<Listing | null>(null)
  const [overview, setOverview] = useState<Record<string, number>>({})
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('pending')
  const [curationFilter, setCurationFilter] = useState('')
  const [selected, setSelected] = useState<Item | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [maintenanceOpen, setMaintenanceOpen] = useState(false)
  const [entitlementUserId, setEntitlementUserId] = useState('')
  const [entitlementOwnerId, setEntitlementOwnerId] = useState('')
  function navigateTab(next: keyof typeof tabs, nextStatus?: string) {
    if (next === 'jobs' || next === 'events' || next === 'previews' || next === 'submissions' || next === 'orders' || next === 'entitlements' || next === 'ledger' || next === 'payouts') setMaintenanceOpen(true)
    const fallback = next === 'works' || next === 'series' || next === 'recruits' ? 'pending' : ''
    setKind(next); setCurationFilter(''); setPage(1); setStatus(nextStatus === undefined ? fallback : nextStatus); setSelected(null); setListing(null); setError(''); setMessage('')
  }
  useEffect(() => {
    if (!enabled || kind === 'support' || kind === 'categories' || kind === 'revenue' || kind === 'engagement' || kind === 'app') return
    let active = true; setLoading(true); setError('')
    const params = new URLSearchParams({ page: String(page), status })
    if ((kind === 'works' || kind === 'series') && curationFilter) params.set('curation', curationFilter)
    if (kind === 'entitlements') { if (entitlementUserId) params.set('user_id', entitlementUserId); if (entitlementOwnerId) params.set('owner_id', entitlementOwnerId) }
    request<Listing>(`/api/admin/marketplace/records/${kind}?${params}`).then(result => { if (active) setListing(result) }).catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setLoading(false) })
    request<Record<string, number>>('/api/admin/marketplace/overview').then(value => { if (active) setOverview(value) }).catch(() => {})
    return () => { active = false }
  }, [enabled, kind, page, status, refresh, entitlementUserId, entitlementOwnerId, curationFilter])
  // 统一提交审核意图，后端始终重新核对版本与状态。
  async function action(path: string, body: unknown) { setError(''); setMessage(''); try { await request(`/api/admin/marketplace${path}`, 'POST', body); setRefresh(v => v + 1); setMessage('操作成功'); return true } catch (e) { setError((e as Error).message); return false } }
  // 审核原因和逐项确认来自该记录的表单，不自动勾选。
  function review(e: FormEvent<HTMLFormElement>, item: Item) {
    e.preventDefault(); const form = new FormData(e.currentTarget); const submitter = (e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement
    void action(`/${kind}/${item.id}/review`, { version: item.version, decision: submitter.value, reason: form.get('reason'), checks: form.getAll('checks') }).then(ok => { if (ok) setSelected(null) })
  }
  if (availability.loading) return <p role="status">正在读取数字资产市场服务状态…</p>
  if (availability.error) return <div className="market-ops"><p role="alert">暂时无法获取数字资产市场服务状态，请重试。{availability.error}</p><button type="button" onClick={availability.retry}>重新加载</button></div>
  if (!enabled) return <div className="market-ops"><p>数字资产市场尚未启用，请先开启此功能后重试。</p><button type="button" onClick={availability.retry}>刷新服务状态</button></div>
  const reviewView = kind === 'works' || kind === 'series' || kind === 'recruits' ? (selected ? 'detail' : 'cards') : 'records'
  return <div className="market-ops">
    <header className="market-ops-header"><div><div className="market-ops-eyebrow"><ShieldCheck size={15} /> 运营工作台</div><h1>数字资产平台运营</h1><p>统一审核作品、短剧及招募信息，管理版权材料、举报和收益。</p></div><button type="button" className="market-ops-refresh" onClick={() => setRefresh(v => v + 1)} disabled={loading}><RefreshCw size={16} className={loading ? 'animate-spin' : ''} />刷新数据</button></header>
    <div className="market-ops-stats">{([
      { key: 'works_pending', label: '待审作品', icon: Film, tab: 'works', tone: 'green' },
      { key: 'recruits_pending', label: '待审招募', icon: Users, tab: 'recruits', tone: 'blue' },
      { key: 'reports_pending', label: '待处理举报', icon: Flag, tab: 'reports', tone: 'amber' },
      { key: 'jobs_failed', label: '失败媒体任务', icon: CircleAlert, tab: 'jobs', tone: 'red' },
    ] as const).map(card => <button type="button" className={`market-ops-stat tone-${card.tone}`} key={card.key} onClick={() => navigateTab(card.tab, card.tab === 'jobs' ? 'failed' : 'pending')}><span className="market-ops-stat-icon"><card.icon size={20} /></span><span><span className="market-ops-stat-label">{card.label}</span><strong>{overview[card.key] ?? '—'}</strong></span><span className="market-ops-stat-arrow">↗</span></button>)}</div>
    <div className="market-ops-context"><span><MessageCircle size={15} />累计咨询 <strong>{overview.consultations ?? '—'}</strong> 次</span><span>文件容量 <strong>{overview.storage_bytes === undefined ? '—' : `${(overview.storage_bytes / 1024 / 1024).toFixed(1)} MB`}</strong></span><span className="market-ops-context-note">版权交易与招募由客服对接，平台解锁收入单独记账</span></div>
    <nav className="market-ops-tabs" aria-label="数字资产运营业务">{Object.entries(businessTabs).map(([key, label]) => <button type="button" key={key} aria-current={kind === key ? 'page' : undefined} onClick={() => navigateTab(key as keyof typeof tabs)}>{label}</button>)}<button type="button" aria-expanded={maintenanceOpen} className="market-ops-maintenance-toggle" onClick={() => { if (maintenanceOpen && (kind === 'jobs' || kind === 'events' || kind === 'previews' || kind === 'submissions' || kind === 'orders' || kind === 'entitlements' || kind === 'ledger' || kind === 'payouts')) navigateTab('works'); setMaintenanceOpen(!maintenanceOpen) }}>更多运营功能 {maintenanceOpen ? '−' : '+'}</button></nav>
    {maintenanceOpen && <div className="market-ops-maintenance"><div><strong>更多运营功能</strong><p>查看订单、播放权益、收益与打款记录，以及短试看任务和历史操作。招募接单由客服对接。</p></div><nav aria-label="更多运营功能">{Object.entries(maintenanceTabs).map(([key, label]) => <button type="button" key={key} aria-current={kind === key ? 'page' : undefined} onClick={() => navigateTab(key as keyof typeof tabs)}>{label}</button>)}</nav></div>}
    {kind === 'jobs' && <p className="market-ops-feedback">此处保留历史媒体任务用于排查；招募不再创建投稿或审片任务，收费作品的短试看请查看“作品试看任务”。</p>}
    {error && <p role="alert" className="market-ops-feedback is-error">{error}</p>}{message && <p role="status" className="market-ops-feedback">{message}</p>}
    {kind === 'app' ? <UnlockOrders revision={refresh} /> : kind === 'engagement' ? <EngagementOperations revision={refresh} /> : kind === 'support' ? <SupportForm /> : kind === 'categories' ? <CategoryForm /> : kind === 'revenue' ? <RevenueConfigForm /> : <><div className="market-ops-filter"><div><h2>{tabs[kind]}</h2><span>{listing ? `共 ${listing.meta.total} 条记录` : '正在加载记录'}</span></div><select aria-label="状态筛选" className="rounded border bg-background p-2" value={status} onChange={e => { setStatus(e.target.value); setPage(1) }}><option value="">全部状态</option>{statusOptions(kind).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{(kind === 'works' || kind === 'series') && <select aria-label="精选置顶筛选" value={curationFilter} onChange={event => { setCurationFilter(event.target.value); setPage(1); setSelected(null) }}><option value="">全部运营状态</option><option value="featured">已加精</option><option value="pinned">已置顶</option><option value="normal">普通内容</option></select>}{kind === 'entitlements' && <div className="market-ops-entitlement-filter"><input aria-label="购买用户编号" type="number" min="1" placeholder="购买用户编号" value={entitlementUserId} onChange={e => { setEntitlementUserId(e.target.value); setPage(1) }} /><input aria-label="创作者编号" type="number" min="1" placeholder="创作者编号" value={entitlementOwnerId} onChange={e => { setEntitlementOwnerId(e.target.value); setPage(1) }} /></div>}<button type="button" onClick={() => setRefresh(v => v + 1)}>刷新</button></div>{kind === 'payouts' && <PayoutCreateForm onSaved={() => setRefresh(v => v + 1)} />}{loading ? <p role="status">正在加载…</p> : reviewView === 'detail' && selected ? <ReviewStage item={selected} series={kind === 'series'} recruit={kind === 'recruits'} onBack={() => setSelected(null)} onReview={review} /> : reviewView === 'cards' ? <ReviewGallery items={listing?.items ?? []} series={kind === 'series'} recruit={kind === 'recruits'} onOpen={setSelected} /> : listing?.items.map(item => <article className="market-ops-record" key={`${kind}-${item.id}-${refresh}`}><header className="market-ops-record-head"><div><span className="market-ops-record-id">#{item.id} · {tabs[kind]}</span><h3>{String(item.title || item.filename || item.recruit_title || (kind === 'entitlements' ? `用户 #${item.user_id} 的永久权益` : '业务记录'))}</h3></div><span className={`market-ops-badge status-${recordStatus(kind, item) || 'record'}`}>{kind === 'events' ? '操作记录' : kind === 'submissions' ? statusNames[String(item.selection)] || '历史投稿' : statusLabel(kind, recordStatus(kind, item))}</span></header><details className="market-ops-details" open={kind === 'works' || kind === 'recruits' || kind === 'series' || kind === 'entitlements'}><summary>{recordDetailsTitle(kind)}</summary><Summary item={item} kind={kind} /></details>
      {kind === 'works' && item.sale_type !== 'free' && <WorkPreviewLink id={Number(item.id)} />}
      {typeof item.asset_id === 'number' && <FileLink id={item.asset_id} label="视频预览" purpose="original" video />}
      {kind === 'works' && typeof item.cover_asset_id === 'number' && <FileLink id={item.cover_asset_id} label="作品封面" />}{typeof item.certificate_asset_id === 'number' && <FileLink id={item.certificate_asset_id} label="权属证明／登记证书" />}
      {Array.isArray(item.evidence_ids) && item.evidence_ids.map(id => <FileLink key={Number(id)} id={Number(id)} label="证明材料" />)}
      {kind === 'series' && Array.isArray(item.episodes) && <div className="market-ops-episodes"><h4>分集材料</h4>{item.episodes.map((episode: Item) => <section key={episode.id}><strong>第 {String(episode.episode_no)} 集 · {String(episode.title || '')}</strong>{typeof episode.asset_id === 'number' && <FileLink id={episode.asset_id} label="分集视频" purpose="original" video />}{typeof episode.cover_asset_id === 'number' && <FileLink id={episode.cover_asset_id} label="分集封面" />}{typeof episode.certificate_asset_id === 'number' && <FileLink id={episode.certificate_asset_id} label="分集版权证明" />}{Array.isArray(episode.evidence_ids) && episode.evidence_ids.map(value => <FileLink key={Number(value)} id={Number(value)} label="分集证明材料" />)}<AuthorizationLink details={episode.details} /></section>)}</div>}
      <AuthorizationLink details={item.details} />{kind === 'submissions' && <p>投稿快照：{JSON.stringify(item.snapshot)}</p>}
      {((kind === 'recruits' || kind === 'series' || kind === 'works') && item.audit_status === 'pending') && <form className="market-ops-review" onSubmit={e => review(e, item)}><h3>审核处理</h3><p>查看内容和版权材料后，给出本次审核结论。</p>{(kind === 'works' || kind === 'series') && <div className="grid gap-3"><section><h3>内容检查</h3><label><input name="checks" value="content" type="checkbox" /> 已检查视频、封面、标题和简介</label></section><section><h3>版权检查</h3><label><input name="checks" value="copyright" type="checkbox" /> 已检查授权函或证书编号、证明材料及版权声明</label></section></div>}<label className="block">审核依据及原因<textarea name="reason" required maxLength={3000} className="block w-full rounded border bg-background p-2" /></label><div className="flex gap-3"><button type="submit" value="approved" className="market-ops-approve">通过该版本</button><button type="submit" value="rejected" className="market-ops-reject">驳回该版本</button></div></form>}
      {kind === 'reports' && <form className="market-ops-review" onSubmit={e => { e.preventDefault(); const form = new FormData(e.currentTarget); if (window.confirm('确认记录举报处理结果？')) void action(`/reports/${item.id}/resolve`, { resolution: form.get('resolution') }) }}><textarea name="resolution" aria-label="处理结果" required maxLength={3000} className="block w-full rounded border bg-background p-2" /><div className="flex gap-3"><button type="submit" className="market-ops-approve">记录处理结果</button><button type="button" className="market-ops-reject" onClick={() => { const reason = window.prompt('临时限制该举报对象的依据和原因'); if (reason) void action(`/block/${item.target_type}/${item.target_id}`, { blocked: true, reason }) }}>临时限制举报对象</button></div></form>}
      {kind === 'payouts' && <PayoutStatusForm item={item} onSaved={() => setRefresh(v => v + 1)} />}
      {['works', 'recruits', 'submissions'].includes(kind) && <button type="button" className="market-ops-reject" onClick={() => { const reason = window.prompt(`${item.blocked ? '解除限制' : '限制播放和咨询'}的原因`); if (reason) void action(`/block/${({ works: 'work', recruits: 'recruit', submissions: 'submission' } as Record<string, string>)[kind]}/${item.id}`, { blocked: !item.blocked, reason }) }}>{item.blocked ? '解除限制（不自动上架）' : '封禁／临时下架'}</button>}
    </article>)}{!selected && !loading && !error && listing?.items.length === 0 && <div className="market-ops-empty"><Inbox size={36} /><h3>暂无{tabs[kind]}记录</h3><p>{status ? '当前筛选条件下暂无记录，请调整状态筛选。' : '当前暂无记录，新的业务记录会显示在这里。'}</p></div>}{!selected && listing && <PaginationBar page={page} pageSize={listing.meta.page_size} total={listing.meta.total} onPageChange={setPage} />}</>}
  </div>
}

// 二维码同样必须走独立 OSS；无配置时清晰报错，不生成假图片。
function SupportForm() {
  const [settings, setSettings] = useState<Item | null>(null)
  const [qr, setQr] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { request<Item>('/api/admin/marketplace/support').then(value => { setSettings(value); setQr(typeof value.qr_asset_id === 'number' ? value.qr_asset_id : null) }).catch(e => setMessage(e.message)) }, [])
  // 小二维码也使用同一分片协议，上传完成后需要 Worker 校验。
  async function uploadQr(file?: File) {
    if (!file) return; setBusy(true)
    try {
      const session = await request<{ id: number; asset_id: number; part_size: number }>('/api/marketplace/uploads', 'POST', { filename: file.name, size_bytes: file.size, kind: 'qr' })
      for (let start = 0, number = 1; start < file.size; start += session.part_size, number++) await request(`/api/marketplace/uploads/${session.id}/parts/${number}`, 'PUT', file.slice(start, start + session.part_size))
      await request(`/api/marketplace/uploads/${session.id}/complete`, 'POST'); setQr(session.asset_id); setMessage('二维码上传完成，请保存客服配置。')
    } catch (e) { setMessage((e as Error).message) } finally { setBusy(false) }
  }
  // 后台保存仍校验二维码属于管理员且状态 ready。
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = new FormData(e.currentTarget); setBusy(true)
    try { await request('/api/admin/marketplace/support', 'PUT', { name: form.get('name'), name_en: form.get('name_en'), hours_en: form.get('hours_en'), wechat: form.get('wechat'), hours: form.get('hours'), enabled: form.get('enabled') === 'on', qr_asset_id: qr }); setMessage('客服配置已保存') } catch (e) { setMessage((e as Error).message) } finally { setBusy(false) }
  }
  if (!settings) return <p>{message || '正在加载客服配置…'}</p>
  return <form className="market-ops-support" onSubmit={save}><label className="block">客服名称<input name="name" required maxLength={80} defaultValue={String(settings.name ?? '平台客服')} className="block w-full rounded border bg-background p-2" /></label><label className="block">英文客服名称<input name="name_en" maxLength={160} defaultValue={String(settings.name_en ?? '')} className="block w-full rounded border bg-background p-2" /></label><label className="block">英文服务时间说明<input name="hours_en" maxLength={200} defaultValue={String(settings.hours_en ?? '')} className="block w-full rounded border bg-background p-2" /></label><label className="block">微信号<input name="wechat" maxLength={100} defaultValue={String(settings.wechat ?? '')} className="block w-full rounded border bg-background p-2" /></label><label className="block">服务时间<input name="hours" maxLength={100} defaultValue={String(settings.hours ?? '')} className="block w-full rounded border bg-background p-2" /></label><label className="block">上传真实客服二维码<input type="file" accept=".png,.jpg,.jpeg,.webp" disabled={busy} onChange={e => uploadQr(e.target.files?.[0])} /></label><p>二维码文件编号：{qr ?? '未设置'}</p>{qr && <FileLink id={qr} label="检查二维码" />}<label className="block"><input name="enabled" type="checkbox" defaultChecked={Boolean(settings.enabled)} /> 启用平台客服</label><button type="submit" disabled={busy}>保存客服配置</button><p role="status">{message}</p></form>
}

function RevenueConfigForm() {
  const [value, setValue] = useState<Item | null>(null)
  const [share, setShare] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [message, setMessage] = useState('正在加载平台分成配置…')
  const [busy, setBusy] = useState(false)
  useEffect(() => { request<Item>('/api/admin/marketplace/revenue-config').then(item => { setValue(item); setShare(String(item.platform_share_bps ?? '')); setEnabled(Boolean(item.enabled)); setMessage('') }).catch(e => setMessage(e.message)) }, [])
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setMessage('')
    try {
      const bps = Number(share)
      if (!Number.isInteger(bps) || bps < 0 || bps > 10000) throw new Error('平台抽成比例须填写 0 至 10000 的整数，2000 表示 20%')
      const result = await request<Item>('/api/admin/marketplace/revenue-config', 'PUT', { version: value?.version ?? 0, platform_share_bps: bps, enabled })
      setValue(result); setEnabled(Boolean(result.enabled)); setShare(String(result.platform_share_bps ?? '')); setMessage(result.enabled ? '配置已保存，平台投放收益已启用。' : '配置已保存，平台投放收益未启用，暂不能提交此类作品。')
    } catch (e) { setMessage((e as Error).message) } finally { setBusy(false) }
  }
  return <form className="market-ops-support" onSubmit={save}><h2>平台投放收益分成</h2><p>按万分比填写平台抽成，例如 2000 表示平台 20%，创作者自动获得剩余 80%。分成仅由后台运营管理；作品、系列和分集的单独比例在审核详情中设置，仅用于后续新发布版本，不改写已冻结的发布版本和历史收益。</p><label className="block">平台抽成比例（万分比）<input type="number" min="0" max="10000" step="1" value={share} onChange={e => setShare(e.target.value)} required className="block w-full rounded border bg-background p-2" /></label>{share !== '' && Number.isInteger(Number(share)) && Number(share) >= 0 && Number(share) <= 10000 && <p>当前比例：平台 {Number(share) / 100}% / 创作者 {(10000 - Number(share)) / 100}%</p>}<label className="block"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> 启用平台投放收益</label><button type="submit" disabled={busy || !value}>{busy ? '保存中…' : '保存配置'}</button><p role="status">{message}</p></form>
}

function PayoutCreateForm({ onSaved }: { onSaved: () => void }) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setMessage('')
    const formElement = e.currentTarget; const form = new FormData(formElement)
    try {
      await request('/api/admin/marketplace/payouts', 'POST', { owner_id: Number(form.get('owner_id')), amount_fen: Math.round(Number(form.get('amount')) * 100), status: form.get('status'), note: form.get('note') })
      formElement.reset(); setMessage('打款记录已保存'); onSaved()
    } catch (err) { setMessage((err as Error).message) } finally { setBusy(false) }
  }
  return <form className="market-ops-support" onSubmit={save}><h3>记录人工打款</h3><div className="pf-market-field-row"><label>创作者用户编号<input name="owner_id" type="number" min="1" required /></label><label>金额（元）<input name="amount" type="number" min="0.01" step="0.01" required /></label></div><label>状态<select name="status" defaultValue="paid"><option value="pending">待打款</option><option value="paid">已打款</option><option value="failed">打款失败</option></select></label><label>备注<textarea name="note" maxLength={3000} /></label><button type="submit" disabled={busy}>{busy ? '保存中…' : '保存打款记录'}</button><p role="status">{message}</p></form>
}








