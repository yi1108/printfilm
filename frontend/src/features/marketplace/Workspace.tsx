import { points } from '../../lib/points'
import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Film, Play, RefreshCw, UsersRound } from 'lucide-react'
import { date, labels, money, request, type Listing, type Row } from './api'
import { Media, Pager } from './shared'
import Button from '../../components/ui/Button'
import { EmptyState, PageHeading } from './ui'
import AssetPreview from './AssetPreview'
import { dialog } from '../../lib/dialog'
import { isFreeWork } from './playbackPolicy'
import { explainMarketplaceError } from './messages'

const fileKindNames: Record<string, string> = new Proxy<Record<string, string>>({ video: '视频', image: '图片', document: '文档' }, { get: (target, key: string) => target[key] ? mt(target[key]) : undefined })

function mineHref(item: Row) {
  return item.kind === 'series' ? `/marketplace/series/${item.id}/edit` : `/marketplace/works/${item.id}/manage`
}

function mineStatus(item: Row) {
  if (item.blocked) return mt("已限制")
  if (item.listed) return mt("已上架")
  return labels[item.audit_status || ''] || mt("草稿")
}

function recruitStatus(item: Row) {
  if (item.blocked) return mt("已限制")
  if (item.state === 'closed') return mt("已关闭")
  if (item.state === 'expired') return mt("已到期")
  return labels[item.audit_status || ''] || mt("草稿")
}

function freeMine(item: Row) {
  return isFreeWork(item)
}

function MineRecruits({ listing, loading, page, changePage }: { listing: Listing | null; loading: boolean; page: number; changePage: (value: number) => void }) {
  useMarketplaceLocale()
  return <section className="pf-market-discover pf-market-mine">
    <header className="pf-discover-heading"><div><span className="pf-market-kicker">{mt("创作需求")}</span><h1>{mt("我的招募")}</h1><p>{mt("草稿、审核和已通过的需求都在这里。")}</p></div><Button variant="dark" to="/marketplace/recruits/new" icon>{mt("发布招募")}<ArrowUpRight size={17} /></Button></header>
    {loading || !listing ? <div key="loading" className="pf-market-grid" role="status">{[0, 1, 2].map(item => <div key={item} className="pf-market-skeleton"><div /><span /><span /></div>)}</div> : listing.items.length ? <div key="ready" className="pf-market-grid">{listing.items.map(item => {
      const href = `/marketplace/recruits/${item.id}/manage`
      return <article className="pf-market-item" key={`recruit-${item.id}`}>
        <div className="pf-market-item-cover">{item.image_ids?.length ? <Media kind="recruit" id={item.id} purpose="image-0" /> : <span className="pf-market-series-mark"><UsersRound size={36} strokeWidth={1.4} /></span>}<span className="pf-market-badge">{recruitStatus(item)}</span><Link className="pf-market-cover-play" to={href} aria-label={mt("管理{0}", [item.title])}><ArrowUpRight size={16} /></Link></div>
        <div className="pf-market-item-body">
          <h3><Link to={href}>{item.title}</Link></h3>
          <p className="pf-market-author"><span>{mt("需")}</span>{mt("截止")} {date(item.deadline_at)}  {mt("· 征集")} {item.wanted_count || 0}  {mt("条")}</p>
          <div className="pf-market-item-price"><div><strong>{money(item.budget_fen)}</strong><span>{mt("/ 条预算")}</span></div><Link to={href} aria-label={mt("管理{0}", [item.title])}><ArrowUpRight size={20} /></Link></div>
        </div>
      </article>
    })}</div> : <EmptyState title={mt("还没有招募")} description={mt("写下创作需求，审核通过后会出现在招募广场。")} action={mt("发布招募需求")} to="/marketplace/recruits/new" />}
    <Pager listing={listing} page={page} change={changePage} />
  </section>
}

function MineWorks({ listing, loading, page, changePage, remove }: { listing: Listing | null; loading: boolean; page: number; changePage: (value: number) => void; remove: (item: Row) => void }) {
  useMarketplaceLocale()
  return <section className="pf-market-discover pf-market-mine">
    <header className="pf-discover-heading"><div><span className="pf-market-kicker">{mt("单视频与短剧")}</span><h1>{mt("我的作品")}</h1><p>{mt("草稿、审核和已上架的作品都在这里。")}</p></div><Button variant="dark" to="/marketplace/works/new" icon>{mt("发布作品")}<ArrowUpRight size={17} /></Button></header>
    {loading || !listing ? <div key="loading" className="pf-market-grid" role="status">{[0, 1, 2].map(item => <div key={item} className="pf-market-skeleton"><div /><span /><span /></div>)}</div> : listing.items.length ? <div key="ready" className="pf-market-grid">{listing.items.map(item => {
      const href = mineHref(item)
      const free = freeMine(item)
      const copyrightPrice = item.kind === 'series' ? item.copyright_price_fen ?? item.price_fen : item.price_fen
      return <article className="pf-market-item" key={`${item.kind}-${item.id}`}>
        <div className="pf-market-item-cover">{item.cover_asset_id ? <Media kind={item.kind === 'series' ? 'series' : 'work'} id={item.id} purpose="cover" /> : <span className="pf-market-series-mark"><Film size={36} /></span>}<Link className="pf-market-cover-play" to={href} aria-label={mt("管理{0}", [item.title])}><Play size={16} /></Link></div>
        <div className="pf-market-item-body">
          <h3><Link to={href}>{item.title}</Link></h3>
          <p className="pf-market-author"><span>{item.kind === 'series' ? mt("剧") : mt("作")}</span>{mineStatus(item)}{item.kind === 'series' ? mt(" · {0} 集", [item.episode_count || 0]) : ''}</p>
          <div className="pf-market-item-price"><div><strong>{free ? mt("免费") : item.kind === 'series' && item.sale_type === 'platform_unlock' ? mt("按集解锁") : (item.sale_type === 'platform_unlock' ? points(item.unlock_price_fen) : money(copyrightPrice))}</strong>{!free && <span>{item.sale_type === 'platform_unlock' ? item.kind === 'series' ? mt("分集定价") : mt("解锁价") : mt("参考价")}</span>}</div><button type="button" onClick={() => remove(item)}>{mt("删除")}</button><Link to={href} aria-label={mt("管理{0}", [item.title])}><ArrowUpRight size={20} /></Link></div>
        </div>
      </article>
    })}</div> : <EmptyState title={mt("还没有作品")} description={mt("单条视频和短剧都会出现在这里。")} action={mt("发布我的作品")} to="/marketplace/works/new" />}
    <Pager listing={listing} page={page} change={changePage} />
  </section>
}

// 所有列表由后端按当前账号隔离；不与原个人中心数据混合。
export default function Workspace() {
  const locale = useMarketplaceLocale()
  /* kind 工作台分类；listing/page 当前列表；refresh 重新读取；mediaId 当前文件预览。 */
  const [kind, setKind] = useState('works')
  const [listing, setListing] = useState<Listing | null>(null)
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [mediaId, setMediaId] = useState<number | null>(null)
  useEffect(() => { let active = true; setLoading(true); setListing(null); setError(''); request<Listing>(`/mine/${kind}?page=${page}`).then(value => { if (active) setListing(value) }).catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setLoading(false) }); return () => { active = false } }, [kind, page, refresh, locale])
  async function action(path: string) { try { await request(path, 'POST'); setRefresh(v => v + 1) } catch (e) { setError((e as Error).message) } }
  async function removeOwned(item: Row) {
    const ok = await dialog.confirm({ title: mt("删除作品"), message: mt("删除后「{0}」会从我的作品和作品广场撤下。文件和审核记录会保留，但不能再展示。", [item.title || mt("未命名作品")]), confirmText: mt("删除"), tone: 'danger' })
    if (!ok || !item.id) return
    try { await request(item.kind === 'series' ? `/series/${item.id}` : `/works/${item.id}`, 'DELETE'); setRefresh(value => value + 1) } catch (e) { setError((e as Error).message) }
  }
  const tabs = { works: mt("我的作品"), series: mt("我的短剧"), recruits: mt("我的招募"), rights: mt("版权材料"), assets: mt("我的文件"), notifications: mt("站内通知") }
  return <><PageHeading title={mt("我的发布与业务进度")} description={mt("从作品草稿到合作机会，在这里跟进作品发布与需求审核。招募接单请联系客服。")} /><p><Link to="/marketplace/authorization">{mt("签署 / 查看 PrintFilm 授权函")}</Link></p>
    <div className="pf-market-workspace-toolbar"><nav className="pf-market-tabs" aria-label={mt("个人业务分类")}>{Object.entries(tabs).map(([key, label]) => <button key={key} type="button" aria-pressed={key === kind} onClick={() => { setKind(key); setPage(1); setMediaId(null); setListing(null); setLoading(true) }}>{label}</button>)}</nav><button type="button" onClick={() => setRefresh(v => v + 1)}><RefreshCw size={14} />{mt("刷新")}</button></div>
    {error && <p role="alert">{marketFeedback(error)}</p>}
    {kind === 'works' ? <MineWorks listing={listing} loading={loading} page={page} changePage={setPage} remove={item => void removeOwned(item)} /> : kind === 'recruits' ? <MineRecruits listing={listing} loading={loading} page={page} changePage={setPage} /> : <>
      {kind === 'series' && <section className="pf-market-discover pf-market-mine"><header className="pf-discover-heading"><div><span className="pf-market-kicker">{mt("剧集资产")}</span><h1>{mt("我的短剧")}</h1><p>{mt("查看短剧草稿、统一审核和上架状态。")}</p></div><Button variant="dark" to="/marketplace/works/new?type=series" icon>{mt("发布短剧")}<ArrowUpRight size={17} /></Button></header>{loading || !listing ? <div key="loading" className="pf-market-grid" role="status">{[0, 1, 2].map(item => <div key={item} className="pf-market-skeleton"><div /><span /><span /></div>)}</div> : listing.items.length ? <div key="ready" className="pf-market-grid">{listing.items.map(item => { const href = `/marketplace/series/${item.id}/edit`; const free = item.sale_type === 'free'; const price = item.copyright_price_fen ?? item.price_fen; return <article className="pf-market-item" key={`series-${item.id}`}><div className="pf-market-item-cover">{item.cover_asset_id ? <Media kind="series" id={item.id} purpose="cover" /> : <span className="pf-market-series-mark"><Film size={36} /></span>}<Link className="pf-market-cover-play" to={href} aria-label={mt("管理{0}", [item.title])}><Play size={16} /></Link></div><div className="pf-market-item-body"><h3><Link to={href}>{item.title}</Link></h3><p className="pf-market-author"><span>{mt("剧")}</span>{mineStatus(item)} · {item.episode_count || 0}  {mt("集")}</p><div className="pf-market-item-price"><div><strong>{free ? mt("免费") : item.sale_type === 'platform_unlock' ? mt("按集解锁") : money(price)}</strong>{!free && <span>{item.sale_type === 'platform_unlock' ? mt("分集定价") : mt("参考价")}</span>}</div><Link to={href} aria-label={mt("管理{0}", [item.title])}><ArrowUpRight size={20} /></Link></div></div></article> })}</div> : <EmptyState title={mt("还没有短剧")} description={mt("创建系列后，可逐集上传或导入漫剧分集。")} action={mt("发布短剧")} to="/marketplace/works/new?type=series" />}<Pager listing={listing} page={page} change={setPage} /></section>}
      {kind !== 'series' && kind !== 'recruits' && <>{loading ? <div className="pf-market-empty" role="status">{mt("正在读取你的业务进度…")}</div> : listing?.items.map(item => <article className="pf-market-workspace-item" key={item.id}>
        <div className="pf-market-record-head"><h2>{item.title || item.filename || item.recruit_title || item.message || mt("记录 #{0}", [item.id])}</h2><span className="pf-market-badge">{item.historical ? mt("历史记录") : item.blocked ? mt("已限制") : item.withdrawn ? mt("已撤回") : labels[item.audit_status ?? item.status ?? item.state ?? item.selection ?? ''] || (kind === 'notifications' ? item.read ? mt("已读") : mt("未读") : mt("业务记录"))}</span></div>
        <p>{date(item.created_at)}  {mt("· 编号 #")}{item.id}</p>
        {(item.reason || item.note || item.error) && <p className="pf-market-record-note">{item.reason || item.note || (item.error ? explainMarketplaceError(item.error) : '')}</p>}
        {kind === 'assets' && <><p>{mt("文件类型：")}{fileKindNames[item.kind || ''] || mt("文件")}</p><button type="button" onClick={() => setMediaId(mediaId === item.id ? null : item.id)}>{mediaId === item.id ? mt("收起预览") : mt("查看文件预览")}</button>{mediaId === item.id && <AssetPreview id={item.id} />}{item.status === 'failed' && <button type="button" onClick={() => action(`/assets/${item.id}/retry`)}>{mt("重新校验文件")}</button>}{item.kind === 'video' && item.status === 'ready' && <Link to={`/marketplace/assets/${item.id}/rights?return=${encodeURIComponent('/marketplace/mine')}`}>{mt("查看版权材料")}</Link>}</>}
        {kind === 'rights' && <><p>{mt("材料状态：")}{labels[item.full_status ?? ''] || mt("待补充")}</p><p>{mt("版权材料随作品一并提交审核，无需单独申请审核。")}</p><Link to={`/marketplace/assets/${item.asset_id}/rights?return=${encodeURIComponent('/marketplace/mine')}`}>{mt("查看与补充材料")}</Link></>}
        {kind === 'notifications' && <>{item.link && <Link to={item.link}>{mt("前往工作台")}</Link>}<button type="button" disabled={item.read} onClick={() => action(`/notifications/${item.id}/read`)}>{item.read ? mt("已读") : mt("标记已读")}</button></>}
      </article>)}
      {!loading && !error && listing?.items.length === 0 && kind !== 'recruits' && <EmptyState title={mt("这里还没有记录")} description={kind === 'notifications' ? mt("发布及审核状态发生变化时，通知会出现在这里。") : mt("你的需求与合作进展，都会在这里留下记录。")} />}
      <Pager listing={listing} page={page} change={setPage} /></>}
    </>}
  </>
}
