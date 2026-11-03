import { useEffect, useRef, useState, type FormEvent } from 'react'
import { CircleAlert, Coins, RefreshCw, Smartphone, Wallet } from 'lucide-react'
import { PaginationBar } from '@/components/PaginationBar'
import { request, type Item, type Listing } from './api'
import { appAmountFen, appMoney, appPanels, appRecordFields, appRecordIds, type AppPanel } from './appPresentation'
import FundingReviewForm from './FundingReviewForm'

const base = '/api/admin/marketplace/app'
const stateOptions: Partial<Record<AppPanel, Array<[string, string]>>> = {
  transactions: [['paid', '已付款'], ['refunded', '已退款']],
  notifications: [['pending', '待处理'], ['running', '处理中'], ['failed', '处理失败'], ['done', '已完成']],
  'unlock-orders': [['paid', '已解锁'], ['revoked', '已撤销']],
  media: [['pending', '排队中'], ['running', '处理中'], ['done', '已就绪'], ['failed', '失败']],
}

/** App独立运营面板；所有余额、统计和财务判断均由服务端返回。 */
export default function AppOperations({ revision = 0 }: { revision?: number }) {
  const [panel, setPanel] = useState<AppPanel>('products')
  const [environment, setEnvironment] = useState('Production')
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [userId, setUserId] = useState('')
  const [listing, setListing] = useState<Listing | null>(null)
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState('')
  const [summaryError, setSummaryError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [editing, setEditing] = useState<Item | null>(null)
  const supportsUserFilter = ['transactions', 'wallets', 'wallet-entries', 'unlock-orders', 'revenue', 'recharge-orders', 'funding-sources', 'debts', 'repayments'].includes(panel)
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setListing(null)
    const params = new URLSearchParams({ page: String(page), page_size: '20', environment })
    if (status) params.set('status', status)
    if (userId && supportsUserFilter) params.set('user_id', userId)
    request<Listing>(`${base}/${panel}?${params}`).then(value => { if (active) setListing(value) })
      .catch(cause => { if (active) setError((cause as Error).message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [panel, page, status, userId, supportsUserFilter, environment, refresh, revision])
  useEffect(() => {
    let active = true
    setSummary(null); setSummaryError('')
    request<Record<string, unknown>>(`${base}/summary?environment=${environment}`).then(value => { if (active) setSummary(value) })
      .catch(cause => { if (active) setSummaryError((cause as Error).message) })
    return () => { active = false }
  }, [environment, refresh, revision])
  function changePanel(next: AppPanel) {
    setPanel(next); setPage(1); setStatus(''); setEditing(null); setError(''); setMessage('')
  }
  async function retryNotification(id: number) {
    if (!window.confirm('重新排队此通知？服务端将重新核验苹果交易状态，不会重复加币。')) return
    setBusy(true); setMessage(''); setError('')
    try { await request(`${base}/notifications/${id}/retry`, 'POST'); setRefresh(value => value + 1); setMessage('通知已重新排队，处理结果请刷新查看。') }
    catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  async function retryMedia(id: number) {
    if (!window.confirm('重新准备此版本的App播放文件？仅重新排队失败任务，不会修改原片和历史发布版本。')) return
    setBusy(true); setMessage(''); setError('')
    try { await request(`${base}/media/${id}/retry`, 'POST'); setRefresh(value => value + 1); setMessage('播放准备任务已重新排队。') }
    catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  const stats = [
    { key: 'wallet_balance_fen', label: '平台可用余额', icon: Wallet },
    { key: 'topup_count', label: '充值交易数', icon: Coins },
    { key: 'pending_notifications', label: '待处理苹果通知', icon: CircleAlert },
    { key: 'payout_due_fen', label: '可结算创作者收益', icon: Smartphone },
  ]
  return <section aria-label="App与苹果内购运营" className="grid gap-5">
    <div className="market-ops-feedback"><strong>统一余额与苹果内购</strong><p className="mt-2">Web与App共用余额和充值套餐，余额可用于AI生成及视频解锁；充值先补齐欠费，消费解锁后才产生创作者收益。苹果渠道费及相关税费由平台承担。</p></div>
    <div className="market-ops-filter"><label>交易环境 <select aria-label="交易环境" value={environment} onChange={event => { setEnvironment(event.target.value); setPage(1); setEditing(null); setMessage('') }}><option value="Production">生产环境</option><option value="Sandbox">沙箱测试环境</option></select></label><button type="button" disabled={loading} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={14} /> 刷新App数据</button></div>
    {environment === 'Sandbox' && <p className="market-ops-feedback">沙箱须使用独立测试部署、数据库和Redis。此处的环境筛选不能创建测试余额，也不能将沙箱充值计入生产账户。</p>}
    <div className="market-ops-stats">{stats.map(card => <div key={card.key} className="market-ops-stat flex min-w-0 items-center gap-4 rounded-xl border border-[var(--ops-line)] bg-white p-5"><span className="market-ops-stat-icon"><card.icon size={20} /></span><span><span className="market-ops-stat-label">{card.label}</span><strong>{summary?.[card.key] === undefined ? '—' : card.key.endsWith('_fen') ? appMoney(summary[card.key]) : String(summary[card.key])}</strong></span></div>)}</div>
    {summaryError && <p role="alert" className="market-ops-feedback is-error">运营统计读取失败：{summaryError}</p>}
    {summary && <p className="market-ops-context">App开放：{summary.app_enabled ? '已开启' : '已关闭'} · 苹果新购：{summary.iap_enabled ? '已开启' : '已关闭'} · 生产配置检查：{summary.production_ready ? '配置完整（仍需真实联调）' : '未就绪'} · 创作者历史退款待抵扣：{appMoney(summary.creator_debt_fen)}</p>}
    <nav className="flex flex-wrap gap-2" aria-label="App运营分类">{Object.entries(appPanels).map(([key, label]) => <button type="button" key={key} aria-pressed={panel === key} className={panel === key ? 'market-ops-approve' : ''} onClick={() => changePanel(key as AppPanel)}>{label}</button>)}</nav>
    {panel === 'products' && <ProductForm key={`${editing?.id ?? 'new'}-${editing?.enabled}`} item={editing} onSaved={() => { setEditing(null); setRefresh(value => value + 1) }} onCancel={() => setEditing(null)} />}
    {panel === 'funding-reviews' && <FundingReviewForm environment={environment} onSaved={() => setRefresh(value => value + 1)} />}
    {panel === 'settlements' && <FinanceForm key={`settlement-${environment}`} kind="settlement" environment={environment} onSaved={() => setRefresh(value => value + 1)} />}
    {panel === 'payouts' && <FinanceForm key={`payout-${environment}`} kind="payout" environment={environment} onSaved={() => setRefresh(value => value + 1)} />}
    {panel === 'revenue' && <p className="market-ops-feedback">登记打款时使用此处的收益记录编号。只有全部来源充值均已对账、且未退款撤销的收益才能结算，后台会扣除历史退款应抵扣金额。</p>}
    {(panel === 'products' || panel === 'media') && <p className="market-ops-context">{panel === 'products' ? '仅配置当前部署的商品映射。同一套餐只启用一个苹果商品；调整到账额度须停用旧商品并新建映射。' : '播放准备按当前部署的内容版本执行；生产与沙箱部署不共用任务和财务数据库。'}</p>}
    <div className="market-ops-filter"><div><h2>{appPanels[panel]}</h2><span>{listing ? `共 ${listing.meta.total} 条记录` : '读取服务端记录'}</span></div>{stateOptions[panel] && <select aria-label="App记录状态" value={status} onChange={event => { setStatus(event.target.value); setPage(1) }}><option value="">全部状态</option>{stateOptions[panel]?.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>}{supportsUserFilter && <label className="text-sm">{panel === 'revenue' ? '创作者编号' : '用户编号'} <input aria-label="筛选用户编号" type="number" min="1" value={userId} onChange={event => { setUserId(event.target.value); setPage(1) }} placeholder={panel === 'revenue' ? '全部创作者' : '全部用户'} /></label>}</div>
    {error && <p role="alert" className="market-ops-feedback is-error">{error}<button type="button" className="ml-3" onClick={() => setRefresh(value => value + 1)}>重新加载</button></p>}
    {message && <p role="status" className="market-ops-feedback">{message}</p>}
    {loading ? <p role="status">正在读取{appPanels[panel]}…</p> : listing?.items.length ? <div>{listing.items.map(item => <article className="market-ops-record" key={item.id}><header className="market-ops-record-head"><div><span className="market-ops-record-id">#{item.id}</span><h3>{String(item.title || item.product_id || item.out_trade_no || appPanels[panel])}</h3></div></header><dl className="market-ops-summary">{appRecordFields(item, panel).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>{panel === 'products' && <button type="button" onClick={() => setEditing(item)}>编辑商品配置</button>}{panel === 'notifications' && item.status === 'failed' && <button type="button" disabled={busy} onClick={() => void retryNotification(item.id)}>核验并重新处理</button>}{panel === 'media' && item.status === 'failed' && <button type="button" disabled={busy} onClick={() => void retryMedia(item.id)}>重新准备播放文件</button>}</article>)}</div> : !error && <div className="market-ops-empty"><h3>暂无{appPanels[panel]}记录</h3><p>请检查交易环境和筛选条件；此处仅显示真实服务端记录。</p></div>}
    {!loading && listing && <PaginationBar page={page} pageSize={listing.meta.page_size} total={listing.meta.total} onPageChange={setPage} />}
  </section>
}

/** 商品只保存苹果编号和固定币数；真实售价由StoreKit展示。 */
function ProductForm({ item, onSaved, onCancel }: { item: Item | null; onSaved: () => void; onCancel: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('')
    const form = new FormData(event.currentTarget)
    try {
      const coins = Number(form.get('coins'))
      const price = appAmountFen(form.get('price'), false)
      if (!Number.isSafeInteger(coins) || coins <= 0) throw new Error('请填写共同套餐的到账额度，包含套餐赠送的额度。')
      await request(`${base}/products`, 'PUT', { product_id: String(form.get('product_id')).trim(), sku_id: String(form.get('sku_id')).trim(), coins, price_fen: price, enabled: form.get('enabled') === 'on' })
      setMessage('商品配置已保存。商品还须在App Store Connect完成配置并可售后，App才能发起真实购买。'); onSaved()
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  return <form className="market-ops-support max-w-none" onSubmit={save}>
    <h3>{item ? '编辑苹果充值商品' : '绑定苹果充值商品'}</h3>
    <p>绑定App Store Connect中的真实消耗型商品及共同充值套餐，到账额度包含套餐赠额。已绑定商品只可启停；实际付款以苹果验签交易为准，参考价不作为到账凭证。</p>
    <div className="grid gap-4 md:grid-cols-4">
      <label>苹果商品编号<input name="product_id" required maxLength={200} readOnly={Boolean(item)} defaultValue={String(item?.product_id || '')} placeholder="填写App Store Connect中的商品编号" /></label>
      <label>共同套餐编号<input name="sku_id" required maxLength={64} readOnly={Boolean(item?.sku_id)} defaultValue={String(item?.sku_id || 'topup_10')} placeholder="例如 topup_10" /></label>
      <label>到账额度（分）<input name="coins" type="number" required min="1" step="1" readOnly={Boolean(item)} defaultValue={typeof item?.coins === 'number' ? item.coins : ''} /></label>
      <label>苹果参考价（元）<input name="price" required type="number" min="0.01" step="0.01" readOnly={Boolean(item)} defaultValue={typeof item?.price_fen === 'number' ? item.price_fen / 100 : ''} /></label>
    </div>
    <label><input type="checkbox" name="enabled" defaultChecked={Boolean(item?.enabled)} /> 允许新购（仍受苹果配置和App开关控制）</label>
    <div className="flex gap-3"><button type="submit" disabled={busy}>{busy ? '保存中…' : '保存商品配置'}</button>{item && <button type="button" onClick={onCancel}>取消编辑</button>}</div>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
  </form>
}

/** 登记已核对的账单与线下打款，金额和可结算余额必须由服务端复核。 */
function FinanceForm({ kind, environment, onSaved }: { kind: 'settlement' | 'payout'; environment: string; onSaved: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const intent = useRef<{ fingerprint: string; key: string } | null>(null)
  const settlement = kind === 'settlement'
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setMessage('')
    const form = new FormData(event.currentTarget)
    try {
      const values = settlement ? { environment, month: form.get('month'), transaction_ids: appRecordIds(form.get('ids')), channel_fee_fen: appAmountFen(form.get('channel_fee')), tax_fen: appAmountFen(form.get('tax')), received_fen: appAmountFen(form.get('received'), true, true), note: form.get('note') }
        : { environment, owner_id: Number(form.get('owner_id')), ledger_ids: appRecordIds(form.get('ids')), amount_fen: appAmountFen(form.get('amount')), note: form.get('note') }
      const fingerprint = JSON.stringify(values)
      if (intent.current?.fingerprint !== fingerprint) intent.current = { fingerprint, key: crypto.randomUUID() }
      const body = { ...values, idempotency_key: intent.current.key }
      if (!window.confirm(settlement ? '确认账单、渠道费、税费和实际到账已核对，并登记本次对账？' : '确认线下打款已完成，并将所选收益明细登记为已打款？此处不会自动转账。')) return
      setBusy(true)
      await request(`${base}/${settlement ? 'settlements' : 'payouts'}`, 'POST', body)
      intent.current = null; setMessage(settlement ? '对账记录已保存。' : '人工打款记录已保存。'); onSaved()
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }
  return <form key={`${kind}-${environment}`} className="market-ops-support max-w-none" onSubmit={save}>
    <h3>{settlement ? '登记苹果月度对账' : '登记创作者人工打款'}</h3>
    <p>{settlement ? '以苹果财务报告核对真实充值记录。手续费和税费由平台承担，不改变创作者已冻结分成；净到账允许为负，须与服务端计算一致。' : '关联已对账的收益明细，只登记已完成的线下打款；退款抵扣和可结算金额由服务端校验。全额抵扣时实际打款可为0元。'}</p>
    <div className="grid gap-4 md:grid-cols-3">
      {settlement ? <>
        <label>对账月份<input name="month" type="month" required /></label>
        <label>苹果渠道费（元）<input name="channel_fee" type="number" min="0" step="0.01" required /></label>
        <label>相关税费（元）<input name="tax" type="number" min="0" step="0.01" required /></label>
        <label>净到账（元，可为负）<input name="received" type="number" step="0.01" required /></label>
      </> : <>
        <label>创作者用户编号<input name="owner_id" type="number" min="1" step="1" required /></label>
        <label>已打款金额（元）<input name="amount" type="number" min="0" step="0.01" required /></label>
      </>}
      <label>{settlement ? '充值记录编号' : '收益账目编号'}<input name="ids" required placeholder="多个编号用逗号分隔" /></label>
    </div>
    <label>核对依据及备注<textarea name="note" required maxLength={3000} rows={3} placeholder={settlement ? '填写苹果报告期间、核对依据及差异说明' : '填写线下打款凭证编号与核对说明'} /></label>
    <button type="submit" disabled={busy || environment === 'Sandbox'}>{busy ? '保存中…' : settlement ? '确认并登记对账' : '确认并登记已打款'}</button>
    {environment === 'Sandbox' && <p>沙箱仅用于交易测试，不进行真实财务对账和打款登记。</p>}
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
  </form>
}
