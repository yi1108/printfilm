import { useEffect, useState, type FormEvent } from 'react'
import { request } from './api'

type Category = { code: string; name_zh: string; name_en: string; enabled: boolean }
type Config = { version: number; items: Category[] }

export default function CategoryForm() {
  const [config, setConfig] = useState<Config | null>(null)
  const [items, setItems] = useState<Category[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true; setError(''); setConfig(null)
    request<Config>('/api/admin/marketplace/categories').then(value => {
      if (active) { setConfig(value); setItems(value.items) }
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [revision])
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!config) return
    setBusy(true); setError(''); setMessage('')
    try {
      const value = await request<Config>('/api/admin/marketplace/categories', 'PUT', { version: config.version, items: items.map(({ code, name_zh, name_en, enabled }) => ({ code, name_zh: name_zh.trim(), name_en: name_en.trim(), enabled })) })
      setConfig(value); setItems(value.items); setMessage('双语分类已保存。固定编码和历史归属不变，Web 与 App 共用此配置。')
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  function change(index: number, patch: Partial<Category>) { setItems(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row)) }
  function move(index: number, delta: number) { setItems(rows => { const next = [...rows]; [next[index], next[index + delta]] = [next[index + delta], next[index]]; return next }) }
  return <form className="market-ops-support" onSubmit={save}><h2>作品分类配置</h2><p>固定编码用于筛选和归属，保存后不可修改。中英文名称可修改；停用保留历史关联。按下方顺序展示，须启用 1 至 30 项。</p>
    {items.map((item, index) => <fieldset key={item.code} disabled={busy} className="rounded border p-4 space-y-3"><legend>分类 {index + 1}</legend><p>固定编码：<code>{item.code}</code></p><div className="grid gap-3 md:grid-cols-2"><label>中文名称<input required maxLength={60} value={item.name_zh} onChange={e => change(index, { name_zh: e.target.value })} /></label><label>英文名称<input required={!config?.items.some(old => old.code === item.code && !old.name_en)} maxLength={100} value={item.name_en} onChange={e => change(index, { name_en: e.target.value })} /></label></div>{!item.name_en && <p role="status">待补齐英文；缺少译文时显示原名称。</p>}<div className="flex flex-wrap gap-3"><label><input type="checkbox" checked={item.enabled} onChange={e => change(index, { enabled: e.target.checked })} /> 启用</label><button type="button" disabled={index === 0} onClick={() => move(index, -1)}>上移</button><button type="button" disabled={index === items.length - 1} onClick={() => move(index, 1)}>下移</button></div></fieldset>)}
    <div className="flex flex-wrap gap-3"><button type="button" disabled={busy || !config || items.length >= 100} onClick={() => setItems(rows => [...rows, { code: `category_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`, name_zh: '', name_en: '', enabled: true }])}>新增分类</button><button type="submit" disabled={!config || busy}>{busy ? '保存中…' : '保存分类'}</button><button type="button" disabled={busy} onClick={() => { if (window.confirm('重新加载将丢弃未保存修改，继续吗？')) { setMessage(''); setRevision(v => v + 1) } }}>重新加载</button></div>{error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}</form>
}
