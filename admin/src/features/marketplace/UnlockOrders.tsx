import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { PaginationBar } from '@/components/PaginationBar'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { points } from '@/lib/points'
import { request, type Listing } from './api'

/** 平台订单查询：购买者扣除的积分，不是创作者个人钱包。 */
export default function UnlockOrders({ revision = 0 }: { revision?: number }) {
  const [environment, setEnvironment] = useState('Production')
  const [status, setStatus] = useState('')
  const [userId, setUserId] = useState('')
  const [page, setPage] = useState(1)
  const [refresh, setRefresh] = useState(0)
  const [listing, setListing] = useState<Listing | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setListing(null)
    const params = new URLSearchParams({ environment, page: String(page), page_size: '20' })
    if (status) params.set('status', status)
    if (userId) params.set('user_id', userId)
    request<Listing>(`/api/admin/marketplace/app/unlock-orders?${params}`)
      .then(value => { if (active) setListing(value) })
      .catch(cause => { if (active) setError((cause as Error).message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [environment, status, userId, page, refresh, revision])
  return <section aria-label="视频解锁订单" className="grid gap-4">
    <div><h2>视频解锁订单</h2><p className="market-ops-context">查询全平台用户用积分购买视频的订单。扣除积分属于购买用户；创作者收益请在收益账本中查看。</p></div>
    <div className="market-ops-filter">
      <label>订单环境<select aria-label="订单环境" value={environment} onChange={event => { setEnvironment(event.target.value); setPage(1) }}><option value="Production">生产环境</option><option value="Sandbox">沙箱测试环境</option></select></label>
      <label>订单状态<select aria-label="订单状态" value={status} onChange={event => { setStatus(event.target.value); setPage(1) }}><option value="">全部状态</option><option value="paid">已解锁</option><option value="revoked">已撤销</option></select></label>
      <label>购买用户编号<input aria-label="购买用户编号" type="text" inputMode="numeric" value={userId} onChange={event => { if (/^\d*$/.test(event.target.value)) { setUserId(event.target.value); setPage(1) } }} placeholder="全部购买用户" /></label>
      <button type="button" disabled={loading} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={14} /> 刷新订单</button>
    </div>
    {environment === 'Sandbox' && <p className="market-ops-context">当前显示沙箱测试订单，不计入生产交易。</p>}
    {error && <p role="alert" className="market-ops-feedback is-error">订单读取失败：{error}<button type="button" onClick={() => setRefresh(value => value + 1)}>重试</button></p>}
    {loading ? <p role="status">正在读取解锁订单…</p> : listing && <>
      <p>共 {listing.meta.total} 条订单</p>
      <Table><TableHeader><TableRow>{['解锁订单编号', '内容订单编号', '购买用户编号', '视频发布版本', '扣除积分', '状态', '解锁时间'].map(label => <TableHead key={label}>{label}</TableHead>)}</TableRow></TableHeader>
        <TableBody>{listing.items.length ? listing.items.map(item => <TableRow key={item.id}>
          <TableCell>#{item.id}</TableCell><TableCell>#{String(item.order_id)}</TableCell><TableCell>#{String(item.user_id)}</TableCell><TableCell>#{String(item.publication_id)}</TableCell>
          <TableCell>{points(item.coins)}</TableCell><TableCell>{item.status === 'paid' ? '已解锁' : item.status === 'revoked' ? '已撤销' : String(item.status)}</TableCell>
          <TableCell>{item.created_at ? new Date(String(item.created_at)).toLocaleString('zh-CN', { hour12: false }) : '—'}</TableCell>
        </TableRow>) : <TableRow><TableCell colSpan={7}>暂无订单，请检查环境和筛选条件。</TableCell></TableRow>}</TableBody>
      </Table>
      <PaginationBar page={page} pageSize={listing.meta.page_size} total={listing.meta.total} onPageChange={setPage} />
    </>}
  </section>
}
