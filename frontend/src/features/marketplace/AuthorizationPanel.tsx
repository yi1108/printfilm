import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { Download, Eye, FileCheck2, ShieldCheck } from 'lucide-react'
import { date, letterFile, request } from './api'
import Modal from '../../components/ui/Modal'

type Signed = { id: number; signer_name: string; created_at: string; template_version: string }
type Status = { template: { version: string; title: string; notices: string[]; body: string }; reading_reference?: { version: string; title: string; notices: string[]; body: string; disclaimer: string } | null; current: Signed | null }
type Point = [number, number]
type Preview = { url: string; image: boolean }

/** 账号签署一次。条款在页面内阅读，已签署文件默认在线预览，点下载才保存。 */
export default function AuthorizationPanel({ onSigned }: { onSigned?: () => void }) {
  const locale = useMarketplaceLocale()
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [name, setName] = useState('')
  const [adult, setAdult] = useState(false)
  const [readAll, setReadAll] = useState(false)
  const [acceptKey, setAcceptKey] = useState(false)
  const canvas = useRef<HTMLCanvasElement>(null)
  const strokes = useRef<Point[][]>([])
  const drawing = useRef<number | null>(null)
  const ready = adult && readAll && acceptKey && name.trim().length >= 2
  useEffect(() => { let active = true; request<Status>('/authorization').then(value => { if (active) setStatus(value) }).catch(e => { if (active) setError(e.message) }); return () => { active = false } }, [])
  const previewUrl = useRef('')
  useEffect(() => {
    setPreview(null)
    setPreviewOpen(false)
    if (previewUrl.current) {
      URL.revokeObjectURL(previewUrl.current)
      previewUrl.current = ''
    }
    return () => {
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current)
      previewUrl.current = ''
    }
  }, [status?.current?.id])
  function point(e: PointerEvent<HTMLCanvasElement>): Point {
    const rect = e.currentTarget.getBoundingClientRect()
    return [Math.max(0, Math.min(800, (e.clientX - rect.left) / rect.width * 800)), Math.max(0, Math.min(240, (e.clientY - rect.top) / rect.height * 240))]
  }
  function move(e: PointerEvent<HTMLCanvasElement>) {
    if (drawing.current !== e.pointerId) return
    const stroke = strokes.current[strokes.current.length - 1]
    if (stroke.length >= 1000) return
    const next = point(e), previous = stroke[stroke.length - 1]
    const ctx = canvas.current?.getContext('2d')
    if (ctx) { ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(...previous); ctx.lineTo(...next); ctx.stroke() }
    stroke.push(next)
  }
  async function loadPreview() {
    if (preview) return preview
    const id = status?.current?.id
    if (!id) return null
    setPreviewBusy(true)
    setError('')
    try {
      const blob = await letterFile(id)
      const url = URL.createObjectURL(blob)
      previewUrl.current = url
      const value = { url, image: blob.type.startsWith('image/') }
      setPreview(value)
      return value
    } catch (e) {
      setError((e as Error).message)
      return null
    } finally {
      setPreviewBusy(false)
    }
  }
  async function openPreview() {
    const value = await loadPreview()
    if (value) setPreviewOpen(true)
  }
  async function downloadLetter() {
    const value = await loadPreview()
    if (!value) return
    const link = document.createElement('a')
    link.href = value.url
    link.download = value.image ? mt("授权函.png") : mt("授权函.pdf")
    link.click()
    link.remove()
  }
  async function sign() {
    if (!status || !ready) return
    const valid = strokes.current.filter(stroke => stroke.length >= 2)
    if (valid.flat().length < 12) { setError(mt("请在签名区完整手写签名，再确认签署。")); return }
    setBusy(true); setError('')
    try {
      const result = await request<Signed>('/authorization', 'POST', { template_version: status.template.version, signer_name: name.trim(), accepted_terms: true, adult: true, read_all: true, accept_key: true, strokes: valid })
      setStatus({ ...status, current: result }); onSigned?.()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  return <section className="pf-market-authorization"><h2>{mt("PrintFilm 作品授权函")}</h2><p>{mt("按现行条款签署一次，本账号后续 PrintFilm 作品可引用。本函是许可使用，不是著作权转让。")}</p>
    {status && <>
      <h3>{locale === 'en' && status.reading_reference ? status.reading_reference.title : status.template.title}</h3>
      <p>{mt("版本")} {status.template.version}</p>
      {locale === 'en' && status.reading_reference && <div className="pf-market-letter-reference" lang="en"><p role="note">{status.reading_reference.disclaimer}</p><ol className="pf-market-letter-notices">{status.reading_reference.notices.map(item => <li key={item}>{item}</li>)}</ol><div className="pf-market-letter">{status.reading_reference.body}</div></div>}
      <details open={locale !== 'en'}><summary>{locale === 'en' ? 'Chinese original (authoritative signed text)' : '中文签署原文'}</summary><ol lang="zh-CN" className="pf-market-letter-notices">{status.template.notices.map(item => <li key={item}>{item}</li>)}</ol><div lang="zh-CN" className="pf-market-letter">{status.template.body}</div></details>
      {status.current ? <>
        <p className="pf-market-notice">{mt("已签署：")}{status.current.signer_name} · {date(status.current.created_at)}{mt("。可点击预览或下载已签署授权函。")}</p>
        <div className="pf-market-letter-actions"><button type="button" onClick={() => { void openPreview() }} disabled={previewBusy}>{previewBusy ? mt("正在打开…") : mt("预览授权函")}</button><button type="button" onClick={() => { void downloadLetter() }} disabled={previewBusy}>{previewBusy ? mt("处理中…") : mt("下载授权函")}</button></div>
        <Modal open={previewOpen} onClose={() => setPreviewOpen(false)} title={mt("授权函预览")} size="xl" className="pf-market-letter-modal">
          <div className="pf-market-letter-modal-summary">
            <div className="pf-market-letter-modal-summary-top">
              <span className="pf-market-letter-modal-eyebrow"><ShieldCheck size={14} />  {mt("PRINTFILM · 数字资产市场")}</span>
              <span className="pf-market-letter-modal-status"><FileCheck2 size={13} />  {mt("已签署")}</span>
            </div>
            <strong>{mt("账号授权函")}</strong>
            <span className="pf-market-letter-modal-meta">{mt("签署人：")}{status.current.signer_name} · {date(status.current.created_at)}  {mt("· 条款")} {status.current.template_version}</span>
            <p>{mt("此处展示已签署的授权协议，具体授权范围以协议正文为准。在线预览不会自动下载文件。")}</p>
          </div>
          <div className="pf-market-letter-preview-surface">
            <div className="pf-market-letter-preview-label"><Eye size={14} />  {mt("文档预览")}</div>
            {preview && (preview.image ? <img className="pf-market-letter-image" src={preview.url} alt={mt("已签署授权函")} /> : <iframe className="pf-market-letter-frame" src={preview.url} title={mt("授权函预览")} />)}
          </div>
          <div className="pf-market-letter-modal-actions"><button type="button" className="pf-market-letter-modal-secondary" onClick={() => setPreviewOpen(false)}>{mt("关闭")}</button><button type="button" className="pf-market-letter-modal-primary" onClick={() => { void downloadLetter() }} disabled={previewBusy}><Download size={14} /> {previewBusy ? mt("处理中…") : mt("下载授权函")}</button></div>
        </Modal>
      </> : <div className="pf-market-fields">
        <label>{mt("签署人真实姓名")}<input value={name} minLength={2} maxLength={80} onChange={e => setName(e.target.value)} disabled={busy} /></label>
        <p>{mt("在下方手写签名（支持鼠标或触屏）")}</p>
        <canvas aria-label={mt("手写签名区域")} ref={canvas} width={800} height={240} className="pf-market-signature" onPointerDown={e => { if (busy || drawing.current !== null || strokes.current.length >= 40) return; try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* 当前指针无法捕获时仍记录笔画 */ } drawing.current = e.pointerId; strokes.current.push([point(e)]) }} onPointerMove={move} onPointerUp={e => { if (drawing.current === e.pointerId) drawing.current = null }} onPointerCancel={() => { drawing.current = null }} />
        <button type="button" disabled={busy} onClick={() => { strokes.current = []; canvas.current?.getContext('2d')?.clearRect(0, 0, 800, 240) }}>{mt("清除签名")}</button>
        <label><input type="checkbox" checked={adult} disabled={busy} onChange={e => setAdult(e.target.checked)} />{mt("我已年满十八周岁，具有完全民事行为能力，所填姓名真实。")}</label>
        <label><input type="checkbox" checked={readAll} disabled={busy} onChange={e => setReadAll(e.target.checked)} />{mt("我已完整阅读本协议全文。")}</label>
        <label><input type="checkbox" checked={acceptKey} disabled={busy} onChange={e => setAcceptKey(e.target.checked)} />{mt("我已特别阅读并同意第7、8、10、11、13、15条。")}</label>
        <button type="button" disabled={busy || !ready} onClick={sign}>{busy ? mt("正在存档…") : mt("确认签署并保存授权函")}</button>
      </div>}
    </>}
    {!status && !error && <p role="status">{mt("正在读取授权条款…")}</p>}{error && <p role="alert">{marketFeedback(error)}</p>}
  </section>
}
