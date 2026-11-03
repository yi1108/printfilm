import { useCategories } from './useCategories'
import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import AssetPicker from './AssetPicker'
import { localDate, request, type Row } from './api'
import { Save } from 'lucide-react'
import Button from '../../components/ui/Button'
import { FormSection, PageHeading, PublishGuide } from './ui'

// 需求可以无附件发布；实质条款锁定由服务端最终校验。
export default function RecruitEditor() {
  useMarketplaceLocale()
  const { names: categories, label: categoryLabel } = useCategories()
  const [category, setCategory] = useState('')
  /* item 需求快照；images 参考图；error/busy 保存反馈。 */
  const { id } = useParams(); const navigate = useNavigate()
  const [item, setItem] = useState<Row | null>(null)
  const [images, setImages] = useState<number[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (id) request<Row>(`/recruits/${id}`).then(value => { setItem(value); setCategory(value.category_code || value.category || 'other'); setImages(value.image_ids ?? []) }).catch(e => setError(e.message)) }, [id])
  // 保留服务器版本，避免旧表单覆盖最新需求及审核结果。
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = new FormData(e.currentTarget); setBusy(true); setError('')
    const body = { title: form.get('title'), description: form.get('description'), ...(/^[a-z][a-z0-9_]*$/.test(String(form.get('category'))) ? { category_code: form.get('category') } : { category: form.get('category') }), budget_fen: Math.round(Number(form.get('budget')) * 100), wanted_count: Number(form.get('count')), requirements: form.get('requirements'), license_scope: form.get('license_scope'), deadline_at: new Date(String(form.get('deadline'))).toISOString(), image_ids: images, ...(id ? { version: item?.version } : {}) }
    try { const result = await request<Row>(id ? `/recruits/${id}` : '/recruits', id ? 'PUT' : 'POST', body); navigate(`/marketplace/recruits/${result.id}/manage`) }
    catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }
  if (id && !item) return <p role={error ? 'alert' : 'status'}>{error || mt("正在加载…")}</p>
  return <><PageHeading title={id ? mt("编辑招募") : mt("发布招募")} description={mt("描述创作需求，审核通过后由平台客服协助对接创作者。")} back="/marketplace/recruits" />{Boolean(item?.submission_count) && <p className="pf-market-notice">{mt("这条需求存在旧版合作记录，为保留原约定，预算、用途、授权、交付和截止条件不可修改。重大变更请关闭后重新发布。")}</p>}<div className="pf-market-editor-layout"><form className="pf-market-form" onSubmit={save}>
    <FormSection step="01" title={mt("描述创作需求")} description={mt("写清你想做什么，以及作品将用于什么场景。")}><label>{mt("标题")}<input name="title" required maxLength={200} placeholder={mt("例如：为城市文旅项目征集一支短片")} defaultValue={item?.title} /></label><label>{mt("需求说明")}<textarea name="description" required maxLength={5000} placeholder={mt("介绍项目背景、目标受众与期待的内容方向")} defaultValue={item?.description} /></label><label>{mt("分类")}<select name="category" required value={category || item?.category_code || categories[0] || ''} onChange={e => setCategory(e.target.value)}><option value="" disabled>{mt('请选择作品分类')}</option>{category && !categories.includes(category) && <option value={category}>{categoryLabel(category, item)}</option>}{categories.map(code => <option key={code} value={code}>{categoryLabel(code)}</option>)}</select></label></FormSection>
    <FormSection step="02" title={mt("预算与交付")} description={mt("填写预期预算及交付要求，具体合作条件由客服协助线下确认。")}><div className="pf-market-field-row"><label>{mt("单条预算（元）")}<input name="budget" required type="number" min="0.01" max="1000000" step="0.01" placeholder="0.00" defaultValue={item?.budget_fen ? item.budget_fen / 100 : ''} /></label><label>{mt("征集数量")}<input name="count" required type="number" min="1" max="10000" defaultValue={item?.wanted_count ?? 1} /></label></div><label>{mt("规格和交付要求（时长、画幅、用途等）")}<textarea name="requirements" required maxLength={3000} placeholder={mt("例如：30秒、16:9横屏、用于品牌宣传；写清交付格式")} defaultValue={item?.requirements} /></label><label>{mt("授权意向及限制")}<textarea name="license_scope" required maxLength={3000} placeholder={mt("说明使用渠道、期限、地域与是否需要独家授权")} defaultValue={item?.license_scope} /></label><label>{mt("截止时间（本机时区）")}<input name="deadline" type="datetime-local" required defaultValue={localDate(item?.deadline_at ?? new Date(Date.now() + 30 * 86400000).toISOString())} /></label></FormSection>
    <FormSection step="03" title={mt("参考与确认")} description={mt("参考图片为选填，最多6张；没有附件也可以发布需求。")}>{images.length > 0 && <div className="pf-market-actions">{images.map(image => <button key={image} type="button" onClick={() => setImages(images.filter(i => i !== image))}>{mt("移除参考图 #")}{image}</button>)}</div>}{images.length < 6 && <AssetPicker kind="image" value={null} onChange={image => setImages(previous => [...new Set([...previous, image])].slice(0, 6))} title={mt("添加参考图片（最多6张）")} />}<label><input type="checkbox" required />{mt("确认有权展示参考材料，理解发布需求及客服咨询不代表已达成合作。")}</label></FormSection>
    {error && <p role="alert">{marketFeedback(error)}</p>}<div className="pf-market-form-actions"><p>{mt("先保存草稿，确认内容后提交审核。审核通过后展示在招募广场。")}</p><Button type="submit" variant="lime" disabled={busy} icon><Save size={17} />{busy ? mt("保存中…") : mt("保存草稿")}</Button></div>
  </form><PublishGuide recruit /></div></>
}

