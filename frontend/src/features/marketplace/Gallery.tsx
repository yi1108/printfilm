import ContentBadges from './ContentBadges'
import { points } from '../../lib/points'
import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useCategories } from './useCategories'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Check, Clock3, Film, Handshake, Play, Search, ShieldCheck, SlidersHorizontal, UsersRound } from 'lucide-react'
import Button from '../../components/ui/Button'
import { date, money, request, type Listing, type Row } from './api'
import { Media, Pager } from './shared'
import { EmptyState } from './ui'
import { isFreeWork } from './playbackPolicy'

function plazaHref(item: Row, recruits: boolean) {
  if (item.kind === 'series') return `/marketplace/series/${item.id}`
  return `/marketplace/${recruits ? 'recruits' : 'works'}/${item.id}`
}

function freeListing(item: Row) {
  return isFreeWork(item)
}

// 公开广场只展示后端过滤通过的单视频、短剧或需求。
export default function Gallery({ recruits = false }: { recruits?: boolean }) {
  const locale = useMarketplaceLocale()
  /* listing 服务端分页；query 已提交筛选；page 当前页；revision 手动重试；formRef 重置筛选。 */
  const { names: categories, label: categoryLabel, error: categoryError } = useCategories()
  const [listing, setListing] = useState<Listing | null>(null)
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [category, setCategory] = useState('')
  const formRef = useRef<HTMLFormElement>(null)
  useEffect(() => {
    let active = true; setLoading(true); setError('')
    request<Listing>(`/${recruits ? 'recruits' : 'works'}?${query}&page=${page}`).then(value => { if (active) setListing(value) }).catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [query, page, recruits, revision, locale])
  // 筛选提交后从第一页查询，金额转分并由服务端执行分页。
  function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = new FormData(e.currentTarget); const params = new URLSearchParams()
    for (const key of ['q', 'category_code', 'sort']) if (form.get(key)) params.set(key, String(form.get(key)))
    for (const [field, key] of [['min', recruits ? 'min_budget' : 'min_price'], ['max', recruits ? 'max_budget' : 'max_price']]) if (form.get(field)) params.set(key, String(Math.round(Number(form.get(field)) * 100)))
    setPage(1); setQuery(params.toString()); setRevision(value => value + 1)
  }
  // 清空条件并恢复最新目录。
  function reset() { setCategory(''); formRef.current?.reset(); setPage(1); setQuery(''); setRevision(value => value + 1) }
  const filtered = [...new URLSearchParams(query)].some(([key, value]) => key !== 'sort' && value)
  return <div className={recruits ? 'pf-market-recruit-gallery' : 'pf-market-discover'}>
    {!recruits && <header className="pf-discover-heading"><div><span className="pf-market-kicker">{mt("创作有价值 · 灵感有回响")}</span><h1>{mt("发现好作品")}</h1><p>{mt("从一帧灵感，到下一次合作。探索创作者的数字影像。")}</p></div><Button variant="dark" to="/marketplace/works/new" icon>{mt("发布作品")}<ArrowUpRight size={17} /></Button></header>}
    <section className={`pf-market-hero${recruits ? ' is-recruit' : ''}`}>
      <div className="pf-market-hero-copy"><span className="pf-market-kicker">{recruits ? mt("连接需求与创作") : mt("让创作，继续发生")}</span><h1>{recruits ? <>{mt("发现值得投入的")}<br /><em>{mt("下一个创作机会。")}</em></> : <>{mt("让好作品，")}<br /><em>{mt("遇见新的价值。")}</em></>}</h1><p>{recruits ? mt("寻找适合你的创作需求，先联系平台客服，开启下一次合作。") : mt("发现创作者的优质视频，也让你的作品被更多人看见。")}</p><Button variant="dark" to={recruits ? '/marketplace/recruits/new' : '/marketplace/works/new'} icon>{recruits ? mt("发布我的需求") : mt("发布我的作品")}<ArrowUpRight size={17} /></Button></div>
      <div className="pf-market-hero-art" aria-hidden="true"><div className="pf-market-art-orbit" /><div className="pf-market-art-frame pf-market-art-back"><Film size={27} /><span>CREATIVE ASSETS</span></div><div className="pf-market-art-frame pf-market-art-front"><div className="pf-market-art-top"><span>PRINTFILM</span><span>● ● ●</span></div><div className="pf-market-art-play">{recruits ? <UsersRound size={40} strokeWidth={1.3} /> : <Play size={38} strokeWidth={1.2} />}</div><div className="pf-market-art-bottom"><span>{recruits ? mt("灵感与需求，在此相遇") : mt("每一份创作，都有新的可能")}</span><ArrowUpRight size={20} /></div></div><span className="pf-market-art-label"><Handshake size={16} />{mt("连接创作与合作")}</span></div>
    </section>
    <div className="pf-market-principles"><span><ShieldCheck size={17} />{recruits ? mt("招募需求人工审核") : mt("权属材料人工核验")}</span><span><Film size={17} />{recruits ? mt("意向接单 · 先联系客服") : mt("免费完整观看 · 收费先试看")}</span><span><Handshake size={17} />{recruits ? mt("客服撮合 · 线下确认合作") : mt("版权出售 · 平台投放")}</span></div>
    <section className="pf-market-catalog" aria-labelledby="market-catalog-title">
      <header className="pf-market-section-heading"><div><h2 id="market-catalog-title">{recruits ? mt("招募广场") : mt("作品广场")}</h2><p>{recruits ? mt("明确的创作需求，寻找合适的合作伙伴。") : mt("浏览已审核上架的单视频和短剧。")}</p></div><span className="pf-market-count">{loading ? mt("正在更新") : `${listing?.meta.total ?? 0} ${recruits ? mt("个需求") : mt("件作品")}`}</span></header>
      {!recruits && categoryError && <p role="alert">{marketFeedback(categoryError)}</p>}<form ref={formRef} className="pf-market-filter-panel" onSubmit={search}>
        {!recruits && <div className="pf-discover-categories" aria-label={mt("作品分类")}>{['', ...categories].map(value => <button key={value} type="button" aria-pressed={category === value} onClick={() => { setCategory(value); const params = new URLSearchParams(query); if (value) params.set('category_code', value); else params.delete('category_code'); setQuery(params.toString()); setPage(1) }}>{value ? categoryLabel(value) : mt("全部作品")}</button>)}</div>}
        <div className="pf-market-filter-top"><label className="pf-market-search"><Search size={18} aria-hidden /><input name="q" aria-label={mt("关键词")} placeholder={recruits ? mt("搜索需求名称，发现创作机会") : mt("搜索作品名称，发现更多创意")} maxLength={100} /></label><select name="sort" aria-label={mt("排序")}>{!recruits && <option value="recommended">{mt("推荐排序")}</option>}<option value="latest">{mt("最新发布")}</option>{recruits ? <option value="deadline">{mt("最近截止")}</option> : <><option value="price_asc">{mt("价格从低到高")}</option><option value="price_desc">{mt("价格从高到低")}</option></>}</select><Button variant="dark" type="submit"><Search size={16} />{mt("搜索")}</Button></div>
        <div className="pf-market-filter-bottom"><span className="pf-market-filter-label"><SlidersHorizontal size={15} />{mt("筛选")}</span><label className="pf-market-category"><span>{mt("分类")}</span><select name="category_code" value={category} onChange={e => setCategory(e.target.value)} aria-label={mt("分类")}><option value="">{mt("全部分类")}</option>{categories.map(value => <option key={value} value={value}>{categoryLabel(value)}</option>)}</select></label><div className="pf-market-price-filter"><span>{recruits ? mt("单条预算") : mt("参考价")}</span><input name="min" type="number" min="0" step="0.01" aria-label={mt("最低价")} placeholder={mt("¥ 最低")} /><span>—</span><input name="max" type="number" min="0" step="0.01" aria-label={mt("最高价")} placeholder={mt("¥ 最高")} /></div><button type="button" className="pf-market-reset" onClick={reset}>{mt("重置筛选")}</button></div>
      </form>
      {error ? <div className="pf-market-error" role="alert"><p>{marketFeedback(error)}</p><Button variant="outline" onClick={() => setRevision(value => value + 1)}>{mt("重新加载")}</Button></div> : loading ? <div className="pf-market-grid" role="status" aria-label={mt("正在加载作品与需求")}>{[0, 1, 2].map(item => <div key={item} className="pf-market-skeleton"><div /><span /><span /></div>)}</div> : listing?.items.length ? <div className={`pf-market-grid${recruits ? ' is-recruits' : ''}`}>{listing.items.map(item => {
        const href = plazaHref(item, recruits)
        const free = !recruits && freeListing(item)
        return <article className="pf-market-item" key={`${item.kind || (recruits ? 'recruit' : 'work')}-${item.id}`}>
        {recruits ? <><div className="pf-market-item-cover">{item.image_ids?.length ? <Media kind="recruit" id={item.id} purpose="image-0" /> : <span className="pf-market-series-mark"><UsersRound size={36} strokeWidth={1.4} /></span>}<span className="pf-market-badge">{mt("征集中")}</span><Link className="pf-market-cover-play" to={href} aria-label={mt("查看需求：{0}", [item.title])}><ArrowUpRight size={16} /></Link></div>
        <div className="pf-market-item-body"><span className="pf-market-category-tag">{item.category_label || item.category}</span><h3><Link to={href}>{item.title}</Link></h3><p className="pf-market-author"><span>{item.author?.slice(0, 1) || mt("创")}</span>{item.author || mt("创作者")}</p><div className="pf-market-item-price"><div><strong>{money(item.budget_fen)}</strong><span>{mt("/ 条预算")}</span></div><Link to={href} aria-label={mt("查看{0}详情", [item.title])}><ArrowUpRight size={20} /></Link></div><div className="pf-market-item-foot"><Clock3 size={13} /><span>{mt("截止")} {date(item.deadline_at)}  {mt("· 征集")} {item.wanted_count}  {mt("条")}</span></div></div></> : <><div className="pf-market-item-cover">{item.kind === 'series' && !item.cover_asset_id ? <span className="pf-market-series-mark"><Film size={36} /></span> : <Media kind={item.kind === 'series' ? 'series' : 'work'} id={item.id} purpose="cover" />}<Link className="pf-market-cover-play" to={href} aria-label={mt("查看作品：{0}", [item.title])}><Play size={16} /></Link></div>
        <div className="pf-market-item-body"><span className="pf-market-category-tag">{item.kind === 'series' ? mt('短剧') : item.category_label || item.category}</span><ContentBadges item={item} /><h3><Link to={href}>{item.title}</Link></h3><p className="pf-market-author"><span>{item.author?.slice(0, 1) || mt("创")}</span>{item.author || mt("创作者")}</p><div className="pf-market-item-price"><div><strong>{free ? mt("免费") : item.kind === 'series' && item.sale_type === 'platform_unlock' ? mt("按集解锁") : (item.sale_type === 'platform_unlock' ? points(item.unlock_price_fen) : money(item.price_fen))}</strong>{item.kind === 'series' ? <span>{item.episode_count || 0}  {mt("集")}{item.free_episode_count ? mt(" · 前{0}集免费", [item.free_episode_count]) : ''}</span> : (!free) && <span>{item.sale_type === 'platform_unlock' ? mt("解锁价") : mt("参考价")}</span>}</div><Link to={href} aria-label={mt("查看{0}详情", [item.title])}><ArrowUpRight size={20} /></Link></div><div className="pf-market-item-foot"><Check size={14} /><span>{item.kind === 'series' ? mt("短剧 · 权属材料已核验") : mt("权属材料已核验")}</span></div></div></>}
      </article>})}</div> : <EmptyState title={filtered ? mt("暂时没有找到匹配结果") : recruits ? mt("下一个好项目，从你的需求开始") : mt("好作品，值得被更多人看见")} description={filtered ? mt("试试其他关键词，或放宽分类和价格范围。") : recruits ? mt("当前暂无公开招募。写下你的创作需求，寻找合适的创作者。") : mt("当前暂无已审核上架的作品。上传你的作品，完成核验后开启展示。")} action={filtered ? undefined : recruits ? mt("发布第一份需求") : mt("发布我的作品")} to={recruits ? '/marketplace/recruits/new' : '/marketplace/works/new'}>{filtered && <Button variant="outline" onClick={reset}>{mt("清空筛选条件")}</Button>}</EmptyState>}
      <Pager listing={listing} page={page} change={setPage} />
    </section>
    <p className="pf-market-footnote">{recruits ? mt("接单请先联系平台客服，具体合作条件在线下协商确认。") : mt("版权合作参考价以客服洽谈为准；观众解锁价用于购买在线播放权益，不包含版权转让。版权转让手续及相关费用请与客服确认。")}</p>
  </div>
}




