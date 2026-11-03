import { useRef, useState, type FormEvent } from 'react'
import { request } from './api'
import { appAmountFen } from './appPresentation'

/** 以真实Web收款报告核对资金来源，页面不具备伪造充值或修改余额的能力。 */
export default function FundingReviewForm({ environment, onSaved }: { environment: string; onSaved: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null)
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setMessage('')
    const form = new FormData(event.currentTarget)
    try {
      const lotId = Number(form.get('lot_id'))
      if (!Number.isSafeInteger(lotId) || lotId <= 0) throw new Error('请填写资金来源中的有效编号。')
      const values = { lot_id: lotId, channel_fee_fen: appAmountFen(form.get('fee')),
        tax_fen: appAmountFen(form.get('tax')), received_fen: appAmountFen(form.get('received'), true, true),
        note: String(form.get('note')).trim() }
      const fingerprint = JSON.stringify(values)
      if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: crypto.randomUUID() }
      if (!window.confirm('确认已根据真实Web支付账单核对本笔实收？这将允许对应创作者收益进入结算，不会修改用户余额。')) return
      setBusy(true)
      await request('/api/admin/marketplace/app/funding-reviews', 'POST', { ...values, idempotency_key: attempt.current.key })
      attempt.current = null; setMessage('Web资金来源核对已记录。'); onSaved()
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  return <form className="market-ops-support max-w-none" onSubmit={save}>
    <h3>登记Web充值实收核对</h3><p>从“资金来源”找到Web充值编号，并核对支付宝或微信渠道的真实账单；苹果交易使用“月度对账”。</p>
    <div className="grid gap-4 md:grid-cols-4">
      <label>资金来源编号<input name="lot_id" type="number" min="1" step="1" required /></label>
      <label>渠道费（元）<input name="fee" type="number" min="0" step="0.01" required /></label>
      <label>税费（元）<input name="tax" type="number" min="0" step="0.01" required /></label>
      <label>净到账（元）<input name="received" type="number" step="0.01" required /></label>
    </div>
    <label>核对依据<textarea name="note" required maxLength={3000} rows={3} placeholder="填写支付报告、账单或收款凭证编号" /></label>
    <button type="submit" disabled={busy || environment !== 'Production'}>{busy ? '保存中…' : '确认并登记对账'}</button>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
  </form>
}
