import { useCallback, useEffect, useState } from 'react'
import { api, type UsageChargeRecord } from '../../api'
import Pagination from '../ui/Pagination'
import { pageCountOf } from '../../lib/pagination'

/** 格式化相对时间展示 */
function formatWhen(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 格式化 token 数量 */
function formatTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 10_000) return `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k`
  return n.toLocaleString('zh-CN')
}

type UsageChargeRecordsProps = {
  /** 嵌入设置页时为 compact */
  variant?: 'panel' | 'compact'
}

/** 使用扣费记录列表：按次展示 LLM / 生图 / 生视频等计费明细 */
export default function UsageChargeRecords({ variant = 'compact' }: UsageChargeRecordsProps) {
  /*
   * items 当前页记录
   * page 当前页码
   * pageSize 每页条数
   * total 总条数
   * loading 加载中
   * error 错误信息
   */
  const [items, setItems] = useState<UsageChargeRecord[]>([])
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(5)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const pageCount = pageCountOf(total, pageSize)

  // 拉取指定页
  const loadPage = useCallback(async (nextPage: number, size: number) => {
    if (!localStorage.getItem('token')) {
      setItems([])
      setTotal(0)
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await api.usageEvents(nextPage, size)
      setTotal(res.meta.total)
      setPage(nextPage)
      setItems(res.items)
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载扣费记录失败')
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadPage(page, pageSize)
  }, [loadPage, page, pageSize])

  function handlePageSizeChange(nextSize: number) {
    setPageSize(nextSize)
    setPage(1)
  }

  return (
    <section className={`pf-usage-records${variant === 'compact' ? ' is-compact' : ''}`}>
      <header className="pf-usage-records-head">
        <h3>使用扣费记录</h3>
        <p className="pf-muted">每次 AI 调用的 token 用量与扣费明细</p>
      </header>

      {loading ? <p className="pf-muted">加载中…</p> : null}
      {error ? <p className="pf-error">{error}</p> : null}

      {!loading && !error && items.length === 0 ? (
        <div className="pf-settings-empty">
          <p>暂无扣费记录</p>
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="pf-settings-list pf-usage-records-list">
          {items.map((item) => (
            <li key={item.id}>
              <div className="pf-settings-list-row pf-usage-record-row">
                <span className="pf-settings-list-main">
                  <strong>{item.billing_label}</strong>
                  <em className="pf-muted">
                    {item.context}
                    {item.total_tokens > 0 ? ` · ${formatTokens(item.total_tokens)} tokens` : ''}
                    {item.estimated ? ' · 估算' : ''}
                  </em>
                </span>
                <span className="pf-settings-list-meta pf-usage-record-meta">
                  <strong className="pf-usage-record-charge">
                    {item.charge_fen > 0 ? `-¥${item.charge_yuan.toFixed(2)}` : '—'}
                  </strong>
                  <em className="pf-muted">{formatWhen(item.created_at)}</em>
                </span>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {!loading && total > 0 ? (
        <Pagination
          page={page}
          pageCount={pageCount}
          total={total}
          pageSize={pageSize}
          onPageSizeChange={handlePageSizeChange}
          onChange={setPage}
          ariaLabel="扣费记录分页"
        />
      ) : null}
    </section>
  )
}
