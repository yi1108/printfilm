import { useEffect, useState, type FormEvent } from 'react'
import { request } from './api'

type Rate = { id: number; cny_per_unit: string; source: string }
const base = '/api/admin/marketplace/app'

export default function AppleValuationForm({ onSaved }: { onSaved: () => void }) {
  const [rates, setRates] = useState<Rate[]>([])
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    let active = true
    request<{items: Rate[]}>(`${base}/exchange-rates`).then(data => { if (active) setRates(data.items) }).catch(error => { if (active) setMessage(error.message) })
    return () => { active = false }
  }, [revision])
  async function save(event: FormEvent<HTMLFormElement>, valuation: boolean) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setBusy(true); setMessage('')
    try {
      if (valuation) {
        await request(`${base}/transactions/${Number(data.get('transaction_id'))}/valuation`, 'POST', { rate_id: Number(data.get('rate_id')) })
        setMessage('待核算交易及关联收益已补齐；用户到账额度不变。')
      } else {
        await request(`${base}/exchange-rates`, 'POST', { cny_per_unit: String(data.get('rate')), source: String(data.get('source')).trim() })
        setMessage('已保存新的美元财务汇率版本，新交易将使用此版本。')
      }
      setRevision(value => value + 1); onSaved()
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(false) }
  }
  return <section className="market-ops-support">
    <h3>美元实收核算</h3>
    <p>此汇率只用于收入核算，不改变美元售价或用户额度。已有核算快照不可覆盖；待核算交易须按其实际账期选择汇率版本。</p>
    <form onSubmit={event => void save(event, false)} className="grid gap-3 md:grid-cols-3">
      <label>1 USD 对应人民币<input name="rate" required type="number" min="0.000001" max="1000000" step="0.000001" /></label>
      <label>汇率来源及账期<input name="source" required maxLength={500} /></label>
      <button disabled={busy}>新增汇率版本</button>
    </form>
    <form onSubmit={event => void save(event, true)} className="grid gap-3 md:grid-cols-3">
      <label>待核算交易记录编号<input name="transaction_id" required type="number" min="1" step="1" /></label>
      <label>核算汇率版本<select name="rate_id" required>{rates.map(rate => <option key={rate.id} value={rate.id}>#{rate.id} · {rate.cny_per_unit} · {rate.source}</option>)}</select></label>
      <button disabled={busy || !rates.length}>补齐该笔核算</button>
    </form>
    {message && <p role="status">{message}</p>}
  </section>
}
