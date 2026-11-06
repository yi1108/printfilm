import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { ChevronLeft, ChevronRight, CircleUserRound, Grid2X2, Info, LockKeyhole, Plus, Store, UsersRound } from 'lucide-react'
import Button from '../../components/ui/Button'
import { EmptyState } from './ui'
import { request, media, money, type Listing } from './api'
import { useMarketplace } from './hooks'
import AssetPicker from './AssetPicker'

// 提供加载、错误和关闭状态，避免关闭模块仍展示业务表单。
export function Gate({ children }: { children: ReactNode }) {
  useMarketplaceLocale()
  const { capabilities, error } = useMarketplace()
  if (error) return <p role="alert">{marketFeedback(error)}</p>
  if (!capabilities) return <p role="status">{mt("正在读取服务状态…")}</p>
  if (!capabilities.enabled) return <p>{mt("数字资产市场尚未启用。")}</p>
  return <><MarketNav />{!capabilities.storage_configured && <div className="pf-market-storage-note" role="note"><Info size={17} aria-hidden /><p><strong>{mt("文件服务暂未配置")}</strong><span>{mt("可保存文字草稿和无附件需求，上传及媒体发布暂不可用。")}</span></p></div>}{children}</>
}

// 登录保持原有登录页与回跳约定。
export function NeedLogin({ children }: { children: ReactNode }) {
  useMarketplaceLocale()
  if (!localStorage.getItem('token')) return <EmptyState title={mt("登录，开启你的创作机会")} description={mt("管理作品、发布需求，与更多创作者建立合作。")} action={mt("登录 / 注册")} to={`/auth?next=${encodeURIComponent(window.location.pathname + window.location.search)}`} />
  return children
}

// 统一下游页内导航，不接管原个人中心逻辑。
export function MarketNav() {
  useMarketplaceLocale()
  return <><header className="pf-market-top"><div className="pf-market-brand"><span className="pf-market-brand-icon"><Store size={22} strokeWidth={1.7} /></span><div><p className="pf-market-eyebrow">PRINTFILM MARKETPLACE</p><p className="pf-market-title">{mt("数字资产市场")}</p></div></div><div className="pf-market-publish-actions"><Button to="/marketplace/recruits/new" variant="outline" size="sm" icon><Plus size={16} />{mt("发布招募")}</Button><Button to="/marketplace/works/new" variant="lime" size="sm" icon><Plus size={16} />{mt("发布作品")}</Button></div></header><div className="pf-market-nav-row"><nav className="pf-market-nav" aria-label={mt("数字资产市场导航")}><NavLink to="/marketplace" end><Grid2X2 size={17} />{mt("作品广场")}</NavLink><NavLink to="/marketplace/recruits" end><UsersRound size={18} />{mt("招募广场")}</NavLink><NavLink to="/marketplace/mine"><CircleUserRound size={17} />{mt("我的发布与通知")}</NavLink></nav><span className="pf-market-nav-hint"><LockKeyhole size={13} />{mt("版权材料 · 统一审核")}</span></div></>
}

// 列表均请求服务端分页，搜索时由调用方重置页码。
export function Pager({ listing, page, change }: { listing: Listing | null; page: number; change: (value: number) => void }) {
  useMarketplaceLocale()
  const pages = listing ? Math.max(1, Math.ceil(listing.meta.total / listing.meta.page_size)) : 1
  return <div className="pf-market-pagination"><span>{mt("共")} {listing?.meta.total ?? 0}  {mt("条")}</span><div><button type="button" disabled={page <= 1} onClick={() => change(page - 1)}><ChevronLeft size={15} />{mt("上一页")}</button><span>{page} / {pages}</span><button type="button" disabled={!listing || page >= pages} onClick={() => change(page + 1)}>{mt("下一页")}<ChevronRight size={15} /></button></div></div>
}

// 有权访问后才签名；缩略图无权访问时不显示伪造封面。
export function Media({ kind, id, purpose, video = false, autoPlay = false, onEnded }: { kind: string; id: number; purpose: string; video?: boolean; autoPlay?: boolean; onEnded?: () => void }) {
  useMarketplaceLocale()
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => { let active = true; setUrl(''); setError(''); media(kind, id, purpose).then(value => { if (active) setUrl(value) }).catch(e => { if (active) setError(e.message) }); return () => { active = false } }, [kind, id, purpose, reload])
  if (error) return <p role="alert">{marketFeedback(error)}<button type="button" onClick={() => setReload(reload + 1)}>{mt("重试")}</button></p>
  if (!url) return <p role="status">{mt("正在获取媒体…")}</p>
  return video ? <video className="pf-market-video" src={url} controls controlsList="nodownload" preload="metadata" autoPlay={autoPlay} onEnded={onEnded} onError={() => setError(mt("视频链接可能已过期，请重试"))} /> : <img className="pf-market-cover" src={url} alt={mt("作品或业务附件")} onError={() => setError(mt("图片链接可能已过期，请重试"))} />
}

// 购买咨询只展示真实客服；不创建交易或自动授予权益。
export function Contact({ kind, id, disabled = false, label }: { kind: string; id: number; disabled?: boolean; label?: string }) {
  useMarketplaceLocale()
  const locale = useMarketplaceLocale()
  const [detail, setDetail] = useState<{ reference: string; title: string; price_fen: number | null; name: string; wechat: string; hours: string; name_zh?: string; name_en?: string; hours_zh?: string; hours_en?: string; notice_labels?: { zh: string; en: string }; notice: string } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [copyMessage, setCopyMessage] = useState('')
  // 用户主动咨询才记录业务意向。
  async function open() {
    setBusy(true); setError('')
    try { setDetail(await request('/consultations', 'POST', { target_type: kind, target_id: id })) }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  // 剪贴板不可用时保留可手动选择的咨询文本。
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setCopyMessage(mt("已复制")) }
    catch { setCopyMessage(mt("复制失败，请选中下方文字手动复制")) }
  }
  const text = detail ? `${detail.reference}｜${detail.title}｜${detail.price_fen === null ? '' : money(detail.price_fen)}｜${window.location.href}` : ''
  return <><button type="button" className="pf-market-buy" disabled={disabled || busy} onClick={open}>{disabled ? mt("版权材料待核验") : busy ? mt("正在获取客服…") : label ? label : kind === 'case' ? mt("联系客服协办") : kind === 'recruit' ? mt("联系客服接单") : mt("联系客服购买")}</button>{error && <p role="alert">{marketFeedback(error)}</p>}{detail && <div className="pf-market-modal" role="dialog" aria-modal="true" aria-label={mt("联系客服")} onKeyDown={e => { if (e.key === 'Escape') setDetail(null) }}><section><button type="button" autoFocus onClick={() => setDetail(null)}>{mt("关闭")}</button><h2>{locale === 'en' ? detail.name_en || detail.name_zh || detail.name : detail.name_zh || detail.name}</h2><Media kind="support" id={1} purpose="qr" /><p>{mt("微信：")}{detail.wechat} · {locale === 'en' ? detail.hours_en || detail.hours_zh || detail.hours : detail.hours_zh || detail.hours}</p><p>{detail.notice_labels?.[locale] || marketFeedback(detail.notice)}</p>{(kind === 'work' || kind === 'submission' || kind === 'series_episode') && <div className="pf-market-purchase-notice"><strong>{mt("版权购买须知")}</strong><p>{mt("如需购买作品版权（著作财产权转让），须另行签订书面转让合同，并按约定办理版权转让及相关手续，可能产生转让办理、登记或服务等费用。具体流程、费用项目及承担方请先与客服确认。")}</p><p>{mt("页面参考价不代表已包含上述费用。仅购买使用授权不等于取得作品版权。")}</p></div>}<p className="pf-market-copy">{text}</p><button type="button" onClick={() => copy(text)}>{mt("复制咨询信息")}</button><p role="status">{marketFeedback(copyMessage)}</p><p>{mt("可在二维码上右键或长按保存图片。")}</p></section></div>}</>
}

// 举报证据可后续由平台要求补充，联系方式不公开。
export function ReportForm({ kind, id }: { kind: string; id: number }) {
  useMarketplaceLocale()
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [evidence, setEvidence] = useState<number[]>([])
  return <><button type="button" onClick={() => setOpen(!open)}>{mt("举报")}</button>{open && <NeedLogin><form className="pf-market-form" onSubmit={async e => { e.preventDefault(); const form = new FormData(e.currentTarget); try { await request('/reports', 'POST', { target_type: kind, target_id: id, statement: form.get('statement'), contact: form.get('contact'), evidence_ids: evidence }); setMessage(mt("已提交，平台会核查并发送站内通知")) } catch (error) { setMessage((error as Error).message) } }}><label>{mt("举报说明（至少10字）")}<textarea name="statement" required minLength={10} maxLength={5000} /></label><label>{mt("联系渠道（不会公开）")}<input name="contact" required maxLength={200} /></label><p>{mt("证明材料：")}{evidence.map(value => <button type="button" key={value} onClick={() => setEvidence(evidence.filter(item => item !== value))}>{mt("移除 #")}{value}</button>)}</p>{evidence.length < 10 && <AssetPicker kind="document" value={null} onChange={value => setEvidence(previous => [...new Set([...previous, value])].slice(0, 10))} title={mt("添加举报证明（可选）")} />}<button type="submit">{mt("提交举报")}</button><p role="status">{marketFeedback(message)}</p></form></NeedLogin>}</>
}


