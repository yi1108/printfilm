import { parsePoints } from '../../lib/points'
import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useCategories } from './useCategories'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import SeriesEditor from './SeriesEditor'
import AssetPicker from './AssetPicker'
import AppEditionPicker, { type AppEdition } from './AppEditionPicker'
import { request, type Handoff, type Row } from './api'
import { Save } from 'lucide-react'
import Button from '../../components/ui/Button'
import { FormSection, PageHeading, PublishGuide } from './ui'
import { explainMarketplaceError } from './messages'



function PublishKindChooser({ choose }: { choose: (kind: 'video' | 'series') => void }) {
  useMarketplaceLocale()
  const navigate = useNavigate()
  return <>
    <PageHeading title={mt("发布作品")} description={mt("单条视频和短剧都会出现在作品广场。也可以直接选择已经在 PrintFilm 生成的成片。")} back="/marketplace" />
    <div className="pf-market-kind-choice">
      <button type="button" onClick={() => choose('video')}><strong>{mt("单条视频")}</strong><span>{mt("上传视频与封面，补充版权信息后统一提交审核。")}</span></button>
      <button type="button" onClick={() => choose('series')}><strong>{mt("短剧")}</strong><span>{mt("在同一页继续添加分集，每集一个视频和封面。")}</span></button>
      <button type="button" onClick={() => navigate('/marketplace/from-printfilm')}><strong>{mt("从我的成片选择")}</strong><span>{mt("同步 PrintFilm 已生成的科普成片或漫剧分集，补充资料后提交审核。有效授权函会自动关联。")}</span></button>
    </div>
  </>
}

// 发布草稿独立于上游创作项目，未配置文件服务仍可保存文字。
export default function WorkEditor() {
  useMarketplaceLocale()
  /* item 编辑快照；assetId 视频；coverId 自定义封面；error/busy 保存反馈。 */
  const { id } = useParams(); const navigate = useNavigate(); const [search] = useSearchParams()
  const [publishKind, setPublishKind] = useState<'video' | 'series' | ''>(search.get('type') === 'series' ? 'series' : '')
  const { names: categories, label: categoryLabel, error: categoryError } = useCategories()
  const [category, setCategory] = useState('')
  useEffect(() => { if (!id && !category && categories.length) setCategory(categories.includes('other') ? 'other' : categories[0]) }, [id, category, categories])
  const [item, setItem] = useState<Row | null>(null)
  const [assetId, setAssetId] = useState<number | null>(null)
  const [coverId, setCoverId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [saleType, setSaleType] = useState<'free' | 'copyright_contact' | 'platform_unlock'>('copyright_contact')
  const [appEditions, setAppEditions] = useState<AppEdition[]>(['domestic'])
  const [source, setSource] = useState('external')
  const [handoff, setHandoff] = useState<Handoff | null>(null)
  const handoffQuery = search.get('handoff')
  const syncing = handoff?.status === 'pending' || handoff?.status === 'running'
  useEffect(() => {
    if (!id && !handoffQuery) return
    let stop = false
    let timer = 0
    async function tick() {
      try {
        const value = handoffQuery
          ? await request<Handoff>(`/handoffs/${handoffQuery}`)
          : (await request<{ items: Handoff[] }>(`/handoffs?target_kind=work&target_id=${id}`)).items[0]
        if (stop || !value) return
        setHandoff(value)
        if (value.status === 'ready' && value.work_id) {
          const work = await request<Row>(`/works/${value.work_id}`)
          if (stop) return
          setAssetId(work.asset_id ?? null)
          setCoverId(work.cover_asset_id ?? null)
        }
        if (value.status === 'pending' || value.status === 'running') timer = window.setTimeout(tick, 3000)
      } catch (err) { if (!stop) setError((err as Error).message) }
    }
    void tick()
    return () => { stop = true; window.clearTimeout(timer) }
  }, [id, handoffQuery, handoff?.status])
  useEffect(() => { if (id) request<Row>(`/works/${id}`).then(value => { setItem(value); setCategory(value.category_code || value.category || 'other'); setSaleType((value.sale_type as typeof saleType) || 'copyright_contact'); setSource(value.source || 'external'); setAppEditions(value.app_editions || ['domestic']); setAssetId(value.asset_id ?? null); setCoverId(value.cover_asset_id ?? null) }).catch(e => setError(e.message)) }, [id])
  // 完整表单更新携带版本，服务器决定是否重审。
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setError(''); const form = new FormData(e.currentTarget)
    const unlockPoints = parsePoints(String(form.get('unlock_price') || ''), 100000000)
    if (saleType === 'platform_unlock' && !appEditions.length) { setError(mt('请至少选择一个App投放版本')); setBusy(false); return }
    if (saleType === 'platform_unlock' && (!unlockPoints)) { setError(mt('请输入有效的整数积分')); setBusy(false); return }
    const body = { title: form.get('title'), description: form.get('description'), ...(/^[a-z][a-z0-9_]*$/.test(String(form.get('category'))) ? { category_code: form.get('category') } : { category: form.get('category') }), tags: String(form.get('tags')).split(/[,，]/).map(v => v.trim()).filter(Boolean), price_fen: saleType === 'free' ? 0 : Math.round(Number(form.get('price')) * 100), unlock_price_fen: saleType === 'platform_unlock' ? unlockPoints : 0, sale_type: saleType, app_editions: appEditions.length ? appEditions : ["domestic"], source, license_scope: form.get('license_scope'), asset_id: assetId, cover_asset_id: coverId, ...(id ? { version: item?.version } : {}) }
    try { const result = await request<Row>(id ? `/works/${id}` : '/works', id ? 'PUT' : 'POST', body); navigate(`/marketplace/works/${result.id}/manage`) }
    catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }
  if (!id && publishKind === 'series') return <SeriesEditor />
  if (!id && !publishKind) return <PublishKindChooser choose={setPublishKind} />
  if (id && !item) return <p role={error ? 'alert' : 'status'}>{error || mt("正在加载作品…")}</p>
  return <><PageHeading title={id ? mt("编辑作品") : mt("发布作品")} description={mt("为作品建立一份清晰的介绍。资料可以先保存为草稿，提交时一次确认版权并交由管理员审核，通过后再上架。")} back="/marketplace" /><div className="pf-market-editor-layout"><div className="pf-market-editor-main"><form className="pf-market-form" onSubmit={save}>
    <p className="pf-market-notice">{mt("先保存作品草稿，提交审核前再统一确认版权信息。")}</p>
    {handoff && <p className={handoff.status === 'failed' ? '' : 'pf-market-notice'} role={handoff.status === 'failed' ? 'alert' : 'status'}>{marketFeedback(handoff.label)}{handoff.error ? `：${explainMarketplaceError(handoff.error)}` : ''}。{handoff.status === 'ready' && !handoff.authorization_ready ? <button type="button" onClick={() => navigate('/marketplace/authorization')}>{mt("去签署授权函")}</button> : null}{handoff.status === 'failed' && handoff.retryable !== false ? <button type="button" onClick={() => void request<Handoff>(`/handoffs/${handoff.id}/retry`, 'POST').then(setHandoff).catch(err => setError((err as Error).message))}>{mt("重新同步")}</button> : handoff.status === 'failed' ? <span>{mt("请返回成片选择页，重新选择最新版本后同步。")}</span> : null}</p>}    <FormSection step="01" title={mt("作品文件")} description={mt("视频和封面在提交审核前必填。保存草稿可以先只写文字。")}>
      <AssetPicker kind="video" required value={assetId} onChange={setAssetId} title={mt("作品视频")} /><AssetPicker kind="image" required value={coverId} onChange={setCoverId} title={mt("作品封面")} />
    </FormSection>
    <FormSection step="02" title={mt("介绍你的作品")} description={mt("清晰的标题和简介，帮助感兴趣的人找到你。")}><label>{mt("标题")}<span className="pf-req-mark">{mt("必填")}</span><input name="title" required maxLength={200} placeholder={mt("给作品一个简洁、有辨识度的名字")} defaultValue={item?.title} /></label><label>{mt("简介")}<textarea name="description" maxLength={5000} placeholder={mt("介绍作品内容、创作想法与适用场景")} defaultValue={item?.description} /></label><div className="pf-market-field-row"><label>{mt("作品分类")}<span className="pf-req-mark">{mt("必填")}</span><select name="category" required value={category} onChange={e => setCategory(e.target.value)} disabled={!categories.length && !category}><option value="" disabled>{mt("请选择作品分类")}</option>{category && !categories.includes(category) && <option value={category}>{categoryLabel(category, item)}{mt("（历史分类）")}</option>}{categories.map(name => <option key={name} value={name}>{categoryLabel(name)}</option>)}</select>{categoryError && <span role="alert">{marketFeedback(categoryError)}</span>}</label><label>{mt("内容来源")}<select name="source" value={source} onChange={e => setSource(e.target.value)}><option value="printfilm">{mt("PrintFilm 生成")}</option><option value="external">{mt("其他平台生成")}</option>{!['printfilm', 'external'].includes(source) && <option value={source}>{mt("历史来源：")}{source}</option>}</select></label></div><label>{mt("标签（逗号分隔，最多10个）")}<input name="tags" placeholder={mt("例如：城市，航拍，生活")} defaultValue={item?.tags?.join('，')} /></label></FormSection>
    <FormSection step="03" title={mt("收益与授权")} description={mt("选择作品的收益方式，并分别设置版权合作参考价与观众解锁价。")}><label>{mt("收益方式")}<select value={saleType} onChange={e => { const next = e.target.value as typeof saleType; setSaleType(next); }}><option value="free">{mt("免费公开")}</option><option value="copyright_contact">{mt("版权出售收益")}</option><option value="platform_unlock">{mt("平台投放收益")}</option></select></label>{saleType === 'platform_unlock' && <AppEditionPicker value={appEditions} onChange={setAppEditions} />}{saleType === 'free' ? <p className="pf-market-notice">{mt("免费作品审核通过并上架后，可完整观看原片，无需生成试看。免费不代表可任意商用，仍须遵守作者授权范围。")}</p> : <><p className="pf-market-notice">{saleType === 'platform_unlock' ? mt("提交审核时生成无水印短试看，最长15秒且不超过原片时长的30%。审核通过后准备完整在线播放版本。观众购买后可永久在线播放所购版本，不包含版权转让；需在平台启用分成后才能提交审核。") : mt("提交审核时生成无水印短试看，最长15秒且不超过原片时长的30%。版权合作通过客服线下洽谈，最终价格、授权或转让范围及额外手续费用请与客服确认。")}</p><label>{mt("参考价（元）")}<input name="price" type="number" min="0" max="1000000" step="0.01" placeholder="0.00" defaultValue={item?.price_fen ? item.price_fen / 100 : ''} /><small>{mt("供版权合作洽谈参考；不代表已包含版权转让手续、登记或服务等费用。")}</small></label>{saleType === 'platform_unlock' && <><label>{mt("观众解锁价（积分）")}<span className="pf-req-mark">{mt("必填")}</span><input name="unlock_price" type="number" required min="1" max="100000000" step="1" defaultValue={item?.unlock_price_fen ? item.unlock_price_fen : ''} /></label></>}</>}<label>{mt("拟授权用途及限制")}<span className="pf-req-mark">{mt("提交审核前必填")}</span><textarea name="license_scope" maxLength={3000} placeholder={mt("请说明允许的用途、范围和期限及禁止事项；保存草稿可暂不填，提交审核前必须补充")} defaultValue={item?.license_scope} /></label></FormSection>
    {error && <p role="alert">{marketFeedback(error)}</p>}<div className="pf-market-form-actions"><p>{id ? mt("保存修改后，作品将退出公开展示并重新审核。") : mt("保存草稿不会公开发布，封面请自行上传。")}</p><Button variant="lime" type="submit" disabled={busy || syncing || !category} icon><Save size={17} />{busy ? mt("保存中…") : syncing ? mt("正在同步成片…") : mt("保存草稿")}</Button></div>
  </form></div><PublishGuide saleType={saleType} /></div></>
}











