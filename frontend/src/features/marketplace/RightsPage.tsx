import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { request, type RightsRecord } from './api'
import AssetPicker from './AssetPicker'
import { PageHeading } from './ui'
import AuthorizationPanel from './AuthorizationPanel'
import AssetPreview from './AssetPreview'

function safeDraftReturn(value: string | null) {
  if (!value) return ''
  try {
    const url = new URL(value, window.location.origin)
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/marketplace/')) return ''
    return url.pathname + url.search
  } catch { return '' }
}

export default function RightsPage({ assetId: suppliedAssetId, sourceHint, embedded = false, onUpdated }: { assetId?: number; sourceHint?: string; embedded?: boolean; onUpdated?: () => void } = {}) {
  useMarketplaceLocale()
  const params = useParams()
  const assetId = suppliedAssetId ?? Number(params.id)
  const [query] = useSearchParams()
  const backTo = safeDraftReturn(query.get('return'))
  const [source, setSource] = useState('external')
  const [item, setItem] = useState<RightsRecord | null>(null)
  const [certificate, setCertificate] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [support, setSupport] = useState<{ available: boolean; name?: string; wechat?: string; hours?: string; message?: string } | null>(null)
  const [qr, setQr] = useState('')
  useEffect(() => { let active = true; request<RightsRecord>(`/assets/${assetId}/rights`).then(value => { if (active) { setItem(value); setSource(sourceHint ?? (value.id ? value.details?.source : query.get('source')) ?? 'external'); setCertificate(value.certificate_asset_id ?? null) } }).catch(e => { if (active) setError(e.message) }); return () => { active = false } }, [assetId, revision, query, sourceHint])
  async function save(e?: FormEvent<HTMLFormElement>) {
    e?.preventDefault()
    const form = e ? new FormData(e.currentTarget) : null
    setBusy(true); setError(''); setMessage('')
    try {
      await request(`/assets/${assetId}/rights`, 'PUT', { version: item?.version ?? 0, details: { source, certificate_number: String(form?.get('certificate_number') ?? ''), dispute_ack: form?.get('dispute_ack') === 'on' }, certificate_asset_id: source === 'printfilm' ? null : certificate, evidence_ids: [] })
      setMessage(backTo ? mt("版权材料已保存。可以返回草稿页继续编辑或提交审核。") : mt("版权材料已保存。请回到草稿页点击“提交审核”。"))
      setRevision(v => v + 1); onUpdated?.()
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  async function contact() {
    setError('')
    try {
      const result = await request<{ available: boolean; name?: string; wechat?: string; hours?: string; message?: string }>('/support')
      setSupport(result)
      if (result.available) setQr((await request<{ url: string }>('/media/support/1/qr')).url)
    } catch (err) { setError((err as Error).message) }
  }
  if (!item) return <p role={error ? 'alert' : 'status'}>{error || mt("正在加载版权信息…")}</p>
  return <>{!embedded && <PageHeading title={mt("确认版权信息")} description={mt("版权信息与作品一次提交、一次审核。标有必填的项目需要填完才能保存。")} back={backTo || '/marketplace/mine'} backLabel={backTo ? mt("返回继续编辑草稿") : mt("返回我的发布")} />}
    <section className="pf-market-rights-route"><h2>{mt("确认作品来源")}</h2><label>{mt("视频生成平台")}<select value={source} disabled={Boolean(sourceHint)} onChange={e => setSource(e.target.value)}><option value="printfilm">{mt("PRINTFILM 生成")}</option><option value="external">{mt("其他平台生成")}</option></select></label><details><summary>{mt("查看当前视频")}</summary><AssetPreview id={assetId} /></details>
      {source === 'printfilm' ? <><AuthorizationPanel onSigned={() => { void save() }} /><button type="button" disabled={busy} onClick={() => { void save() }}>{mt("使用已签署授权函")}</button><p>{mt("账号按当前条款签署一次即可，后续 PRINTFILM 作品可引用有效授权函，无需逐件签署或上传版权证书。")}</p></> : <><form className="pf-market-form" key={`${item.version}-${source}`} onSubmit={save}><label>{mt("版权证书编号")}<span className="pf-req-mark">{mt("必填")}</span><input name="certificate_number" required maxLength={200} defaultValue={item.details?.certificate_number} /></label><AssetPicker kind="image" required value={certificate} onChange={setCertificate} title={mt("版权证书截图或照片")} /><label><input type="checkbox" name="dispute_ack" required defaultChecked={Boolean(item.details?.dispute_ack)} />{mt("我确认材料真实，版权纠纷与平台无关")}<span className="pf-req-mark">{mt("必填")}</span></label><button type="submit" disabled={busy || !certificate}>{mt("保存版权信息")}</button></form><p>{mt("暂缺版权证明材料？联系客服了解协办流程，材料齐备后再提交审核。")}</p><button type="button" onClick={() => { void contact() }}>{mt("联系客服协办")}</button></>}
      {support && <div role="status">{support.available ? <><p>{support.name} · {support.wechat} · {support.hours}</p>{qr && <img src={qr} alt={mt("平台客服二维码")} style={{ maxWidth: 240 }} />}</> : <p>{support.message || mt("客服暂不可用")}</p>}</div>}
    </section>{message && <p role="status">{marketFeedback(message)}{backTo && <> <Link to={backTo}>{mt("返回继续编辑草稿")}</Link></>}</p>}{error && <p role="alert">{marketFeedback(error)}</p>}</>
}
