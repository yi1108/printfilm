import { useState, type FormEvent } from 'react'
import { request, type Item } from './api'

export default function ContentRevenueForm({ item, kind }: { item: Item; kind: 'work' | 'series' | 'series_episode' }) {
  const [saved, setSaved] = useState<number | null>(typeof item.share_bps === 'number' ? item.share_bps : null)
  const [value, setValue] = useState(saved === null ? '' : String(saved))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  async function save(event: FormEvent) {
    event.preventDefault()
    if (value !== '' && (!/^\d+$/.test(value) || Number(value) > 10000)) { setMessage('请输入 0～10000 的整数，或留空恢复继承比例。'); return }
    if (!reason.trim()) { setMessage('请填写修改原因。'); return }
    setBusy(true); setMessage('')
    try {
      const result = await request<{ share_bps: number | null }>(`/api/admin/marketplace/content-revenue/${kind}/${item.id}`, 'PATCH', {
        version: item.version, previous_share_bps: saved, share_bps: value === '' ? null : Number(value), reason: reason.trim(),
      })
      setSaved(result.share_bps); setReason(''); setMessage('已保存，仅在后续提交发布时采用；现有发布版本及历史收益保持不变。')
    } catch (error) { setMessage((error as Error).message) } finally { setBusy(false) }
  }
  return <form className="market-ops-inline-form" onSubmit={save}>
    <h3>{kind === 'series_episode' ? '当前分集分成' : kind === 'series' ? '系列默认分成' : '作品分成'}（仅后台运营可修改）</h3>
    <p>留空继承{kind === 'series_episode' ? '系列及平台' : '平台'}比例。仅用于后续提交的发布版本，不追溯已发布版本及历史订单。</p>
    <label>平台抽成（万分比）<input type="text" inputMode="numeric" value={value} onChange={event => setValue(event.target.value)} placeholder="留空继承" /></label>
    {value !== '' && /^\d+$/.test(value) && Number(value) <= 10000 && <p>平台 {Number(value) / 100}% / 创作者 {(10000 - Number(value)) / 100}%</p>}
    <label>修改原因<input value={reason} onChange={event => setReason(event.target.value)} required maxLength={2000} /></label>
    <button type="submit" disabled={busy}>{busy ? '保存中…' : '保存分成'}</button>
    {message && <p role="status">{message}</p>}
  </form>
}
