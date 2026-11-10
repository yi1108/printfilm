import ContentBadges from './ContentBadges'
import ShareButton from './ShareButton'
import { points } from '../../lib/points'
import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { date, labels, money, request, type Row } from './api'
import { Contact, Media, NeedLogin, ReportForm } from './shared'
import { PageHeading } from './ui'
import WorkPublishingSteps from './WorkPublishingSteps'
import { dialog } from '../../lib/dialog'
import { isFreeWork } from './playbackPolicy'

// 公开详情与作者管理分离，招募统一由客服协调接单。
export default function Detail({ recruit = false, manage = false }: { recruit?: boolean; manage?: boolean }) {
  const locale = useMarketplaceLocale()
  const loadedPath = useRef('')
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const [item, setItem] = useState<Row | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [preview, setPreview] = useState(false)
  const [retryingPreview, setRetryingPreview] = useState(false)
  const previewActive = Boolean(item && !isFreeWork(item) && (item.preview_status === 'pending' || item.preview_status === 'running'))
  useEffect(() => { let active = true; const path = `${recruit ? 'recruits' : 'works'}/${id}`; if (loadedPath.current !== path) { setItem(null); loadedPath.current = path }; setError(''); request<Row>(`/${recruit ? 'recruits' : 'works'}/${id}`).then(value => { if (active) setItem(value) }).catch(e => { if (active) setError(e.message) }); return () => { active = false } }, [id, recruit, refresh, locale])
  // 状态操作只发意图；重复和过期版本由后端处理。
  async function action(path: string, body?: unknown) {
    setError(''); setMessage('')
    try { await request(path, 'POST', body); setMessage(mt("操作成功")); setRefresh(v => v + 1) }
    catch (err) { setError((err as Error).message) }
  }
  useEffect(() => {
    if (!manage || recruit || (item?.audit_status !== 'processing' && !previewActive)) return
    let active = true
    const timer = window.setInterval(() => {
      request<Row>(`/works/${id}`).then(fresh => { if (active) setItem(fresh) }).catch(err => { if (active) setError(err.message) })
    }, 5000)
    return () => { active = false; window.clearInterval(timer) }
  }, [id, manage, recruit, item?.audit_status, previewActive])
  if (!item) return <p role={error ? 'alert' : 'status'}>{error || mt("正在加载…")}</p>
  const privateView = manage && item.version !== undefined
  const submitIssues = [
    !item.asset_id ? mt("请先上传并保存作品视频。") : item.media_status !== 'ready' ? mt("作品视频尚未就绪，请检查上传状态。") : '',
    !item.rights_complete ? mt("请补齐版权材料（PRINTFILM 授权函或其他平台版权证明）。") : '',
    !item.license_scope?.trim() ? mt("请在“编辑草稿 → 收益与授权”中填写“拟授权用途及限制”。") : '',
    item.blocked ? mt("作品已被限制，请联系客服处理。") : '',
  ].filter(Boolean)
  const canSubmitWork = submitIssues.length === 0
  async function refreshProgress() {
    try { setItem(await request<Row>(`/works/${id}`)) } catch (e) { setError((e as Error).message) }
  }
  async function retryPreview() {
    if (!item || retryingPreview || previewActive) return
    setRetryingPreview(true); setError(''); setMessage('')
    try {
      setItem(await request<Row>(`/works/${id}/preview/retry`, 'POST', { version: item.version }))
      setMessage(mt("已重新排队生成短试看，可在此查看处理进度。"))
    } catch (err) { setError((err as Error).message) } finally { setRetryingPreview(false) }
  }
  async function removeWork() {
    const ok = await dialog.confirm({ title: mt("删除作品"), message: mt("删除后作品会从我的作品和作品广场撤下。文件和审核记录会保留，但不能再展示。"), confirmText: mt("删除"), tone: 'danger' })
    if (!ok) return
    try { await request(`/works/${id}`, 'DELETE'); navigate('/marketplace/mine') } catch (err) { setError((err as Error).message) }
  }
  if (manage && !privateView) return <p role="alert">{mt("无权管理此记录，请从广场查看公开详情。")}</p>
  // 广场详情面向浏览与购买；作者管理仅从独立管理路由进入。
  if (!recruit && !manage) return <>
    <PageHeading title={item.title || mt("作品详情")} description={`${item.author || mt("创作者")} · ${item.category_label || item.category || mt('其他')}`} back="/marketplace" />
    <div className="pf-market-buyer-layout">
      <section className="pf-market-buyer-player" aria-label={mt("作品视频预览")}><Media kind="work" id={id} purpose="preview" video /></section>
      <aside className="pf-market-buyer-info"><span className="pf-market-badge">{mt("视频作品")}</span><ContentBadges item={item} /><h2>{item.title}</h2><p>{mt("创作者 ·")} {item.author || mt("创作者")}</p><div className="pf-market-buyer-price"><span>{isFreeWork(item) ? mt("免费公开") : item.sale_type === 'platform_unlock' ? mt("观众解锁价") : mt("参考价")}</span><strong>{isFreeWork(item) ? mt("免费") : (item.sale_type === 'platform_unlock' ? points(item.unlock_price_fen) : money(item.price_fen))}</strong></div>{item.sale_type === 'copyright_contact' && <Contact kind="work" id={id} />}<small>{isFreeWork(item) ? mt("免费作品可看完整时长，播放原片。使用仍须遵守作者授权范围。") : item.sale_type === 'platform_unlock' ? mt("购买后可永久在线播放所购版本，不包含版权转让。当前网页仅提供短试看。") : mt("当前为无水印短试看，最长15秒且不超过原片时长的30%。版权合作请联系客服，确认价格、授权或转让范围及交付方式。")}</small>{item.sale_type !== 'copyright_contact' && <ShareButton kind="work" id={id} />}<ReportForm kind="work" id={id} /></aside>
    </div>
    <section className="pf-market-detail-section"><h2>{mt("作品介绍")}</h2><p className="pf-market-text">{item.description || mt("暂未填写详细介绍")}</p><h2>{mt("用途及授权意向")}</h2><p className="pf-market-text">{item.license_scope || mt("具体授权范围请联系客服确认")}</p><p>{mt("内容审核已通过，版权材料已核验。")}{item.sale_type === 'copyright_contact' ? mt("具体授权或版权转让以双方另行签订的协议为准。") : mt("观看权益不等于取得版权，使用仍须遵守作者授权范围。")}</p></section>
  </>
  if (recruit && !manage) return <>
    <PageHeading title={item.title || mt("招募详情")} description={`${item.author || mt("需求发布者")} · ${item.category_label || item.category || mt('其他')} · ${date(item.created_at)}`} back="/marketplace/recruits" />
    <div className="pf-market-detail-intro">
      <div><span className="pf-market-category-tag">{mt("创作需求")}</span><p className="pf-market-text">{item.description || mt("暂未填写详细介绍")}</p></div>
      <div className="pf-market-detail-price"><span>{mt("单条预算")}</span><strong>{money(item.budget_fen)}</strong><small>{mt("具体合作条件由客服协助线下确认")}</small></div>
    </div>
    <section className="pf-market-detail-section"><h2>{mt("需求与交付要求")}</h2><p>{mt("需求数量")} {item.wanted_count}  {mt("条 · 截止")} {date(item.deadline_at)}</p><p className="pf-market-text">{item.requirements}</p><h2>{mt("用途及授权意向")}</h2><p className="pf-market-text">{item.license_scope || mt("具体授权要求请联系客服确认")}</p>{Boolean(item.image_ids?.length) && <><h2>{mt("参考图片")}</h2>{item.image_ids?.map((image, index) => <Media key={image} kind="recruit" id={id} purpose={`image-${index}`} />)}</>}</section>
    <section className="pf-market-detail-section"><h2>{item.is_owner ? mt("你的招募需求") : mt("想接下这个项目？")}</h2>
      {item.is_owner ? <p>{mt("创作者通过平台客服沟通接单，客服协助你确认合作。")}<Link to={`/marketplace/recruits/${id}/manage`}>{mt("管理我的招募")}</Link></p> : !item.is_open ? <p className="pf-market-notice">{mt("该招募已结束，暂不接受新的接单咨询。")}</p> : <><p>{mt("先联系平台客服，提供这条招募的编号及你的创作意向。客服将协助确认需求、预算、授权和交付安排。")}</p><div className="pf-market-actions"><NeedLogin><Contact kind="recruit" id={id} /></NeedLogin></div><small>{mt("具体合作在线下协商，联系客服不代表已接单或成交。")}</small></>}
    </section>
    <ReportForm kind="recruit" id={id} />
  </>
  return <><PageHeading title={item.title || (recruit ? mt("招募详情") : mt("作品详情"))} description={`${item.author || mt("创作者")} · ${item.category_label || item.category || mt('其他')} · ${date(item.created_at)}`} back={manage ? '/marketplace/mine' : recruit ? '/marketplace/recruits' : '/marketplace'} /><div className="pf-market-detail-intro"><div><span className="pf-market-category-tag">{recruit ? mt("创作需求") : mt("视频作品")}</span><p className="pf-market-text">{item.description || mt("暂未填写详细介绍")}</p></div><div className="pf-market-detail-price"><span>{recruit ? mt("单条预算") : isFreeWork(item) ? mt("免费公开") : item.sale_type === 'platform_unlock' ? mt("观众解锁价") : mt("参考价")}</span><strong>{!recruit && isFreeWork(item) ? mt("免费") : (recruit ? money(item.budget_fen) : item.sale_type === 'platform_unlock' ? points(item.unlock_price_fen) : money(item.price_fen))}</strong><small>{recruit || item.sale_type === 'copyright_contact' ? mt("具体合作与授权由客服协助线下确认") : item.sale_type === 'platform_unlock' ? mt("购买所购版本的永久在线播放权益，不包含版权转让") : mt("免费完整观看，使用仍须遵守作者授权范围")}</small></div></div><section className="pf-market-detail-section"><h2>{mt("用途及授权意向")}</h2><p className="pf-market-text">{item.license_scope || mt("请联系发布者补充授权说明")}</p>
    {recruit ? <><p>{mt("征集")} {item.wanted_count}  {mt("条 · 截止")} {date(item.deadline_at)}</p><p className="pf-market-text">{item.requirements}</p>{item.image_ids?.map((_, index) => <Media key={index} kind="recruit" id={id} purpose={`image-${index}`} />)}</> : <><p>{mt("作品与版权材料一并提交，由管理员统一审核；通过后由您主动上架。")}</p><button type="button" disabled={privateView && (!item.asset_id || item.media_status !== 'ready')} onClick={() => setPreview(!preview)}>{mt("播放／关闭作品预览")}</button>{preview && <Media kind={privateView ? 'asset' : 'work'} id={privateView ? item.asset_id ?? 0 : id} purpose="preview" video />}</>}
    </section>{privateView && !recruit && <WorkPublishingSteps item={item} onUpdated={() => { void refreshProgress() }} />}{privateView && <section><h2>{mt("发布管理")}</h2>{!recruit && submitIssues.length > 0 && <div className="pf-market-notice" role="status"><strong>{mt("提交前还需完成：")}</strong><ul>{submitIssues.map(issue => <li key={issue}>{issue}</li>)}</ul><Link to={`/marketplace/works/${id}/edit`}>{mt("前往编辑草稿")}</Link></div>}{item.audit_status === 'processing' && <p role="status">{mt("正在生成短试看，完成后自动进入待审核。可以关闭页面，稍后在我的发布中查看。")}</p>}<p>{recruit ? mt("招募审核") : mt("作品审核")}：{labels[item.audit_status ?? ''] || item.audit_status} · {recruit ? labels[item.state ?? ''] : item.listed ? mt("已上架") : mt("未上架")}{item.blocked ? mt(" · 已封禁") : ''}</p><p>{item.reason}</p><div className="pf-market-actions"><Link to={`/marketplace/${recruit ? 'recruits' : 'works'}/${id}/edit`}>{mt("编辑草稿")}</Link><button type="button" disabled={!recruit && (!canSubmitWork || item.audit_status === 'processing' || item.audit_status === 'pending' || item.audit_status === 'approved')} onClick={() => action(`/${recruit ? 'recruits' : 'works'}/${id}/submit`, { version: item.version })}>{item.audit_status === 'processing' ? mt("正在生成短试看…") : item.audit_status === 'preview_failed' ? mt("重试生成短试看并提交") : mt("提交审核")}</button>{recruit ? <button type="button" onClick={() => { if (window.confirm(mt("关闭后将退出招募广场，停止新的接单咨询。确认关闭？"))) void action(`/recruits/${id}/close`) }}>{mt("关闭招募")}</button> : <><button type="button" disabled={!item.listed && (!canSubmitWork || item.audit_status !== 'approved')} onClick={() => action(`/works/${id}/listing?listed=${!item.listed}`, { version: item.version })}>{item.listed ? mt("下架") : mt("上架")}</button>{item.asset_id && <Link to={`/marketplace/assets/${item.asset_id}/rights?source=${item.source || 'external'}&return=${encodeURIComponent(`/marketplace/works/${id}/edit`)}`}>{mt("确认版权信息")}</Link>}<button type="button" onClick={() => void removeWork()}>{mt("删除作品")}</button></>}</div></section>}
    {privateView && !recruit && item.audit_status === 'approved' && !isFreeWork(item) && (item.preview_status === 'failed' || previewActive) && <section aria-label={mt("短试看修复")}><p role="status">{previewActive ? mt("正在生成短试看，可以关闭页面，稍后回来查看。") : mt("短试看生成失败，可直接重试。")}</p><button type="button" disabled={retryingPreview || previewActive || item.blocked} onClick={() => void retryPreview()}>{retryingPreview || previewActive ? mt("正在生成短试看…") : mt("重试生成短试看")}</button></section>}
    {recruit && <p className="pf-market-notice">{mt("审核通过后，创作者通过平台客服沟通接单。具体合作、合同与交付在线下确认。")}</p>}
    <div className="pf-market-actions">{(recruit || (item.sale_type === 'copyright_contact')) && <Contact kind={recruit ? 'recruit' : 'work'} id={id} label={recruit ? mt("联系客服") : undefined} />}<ReportForm kind={recruit ? 'recruit' : 'work'} id={id} /></div>
    {message && <p role="status">{marketFeedback(message)}</p>}{error && <p role="alert">{marketFeedback(error)}</p>}</>
}








