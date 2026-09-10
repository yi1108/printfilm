import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type UsageSummary } from '../../api'

/** 格式化 token 数量，过大时用 k/M 缩写 */
function formatTokens(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`
  if (n >= 10_000) return `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k`
  return n.toLocaleString('zh-CN')
}

type MonthlyUsageCardProps = {
  /** compact 嵌入定价/设置卡片；panel 独立侧栏样式 */
  variant?: 'panel' | 'compact'
  /** 是否显示「去充值」按钮（定价页已可直接充值时可关闭） */
  showTopup?: boolean
}

/** 本月用量卡片：Token / 费用 / 余额，供定价页与个人中心复用 */
export default function MonthlyUsageCard({
  variant = 'panel',
  showTopup = true,
}: MonthlyUsageCardProps) {
  const [usage, setUsage] = useState<UsageSummary | null>(null)

  useEffect(() => {
    if (!localStorage.getItem('token')) {
      setUsage(null)
      return
    }
    api
      .usageSummary()
      .then(setUsage)
      .catch(() => setUsage(null))
  }, [])

  const tokenPct = Math.min(100, Math.log10((usage?.tokens || 0) + 1) * 18)
  const chargePct = Math.min(100, (usage?.charge_fen || 0) / 20)

  return (
    <div className={`pf-usage-card${variant === 'compact' ? ' is-compact' : ''}`}>
      <header className="pf-usage-card-head">
        <h3>本月使用情况</h3>
        <p>按上游 token 实际用量计费</p>
      </header>

      <div className="pf-usage-row">
        <span>Token 用量</span>
        <span className="pf-usage-val">{formatTokens(usage?.tokens ?? 0)}</span>
      </div>
      <div className="pf-meter">
        <i style={{ width: `${tokenPct}%` }} />
      </div>

      <div className="pf-usage-row">
        <span>本月费用</span>
        <span className="pf-usage-val">¥{(usage?.charge_yuan ?? 0).toFixed(2)}</span>
      </div>
      <div className="pf-meter">
        <i style={{ width: `${chargePct}%` }} />
      </div>

      <div className="pf-usage-row">
        <span>可用余额</span>
        <span className="pf-usage-val">¥{(usage?.balance_yuan ?? 0).toFixed(2)}</span>
      </div>
      {(usage?.frozen_fen ?? 0) > 0 ? (
        <div className="pf-usage-row">
          <span>冻结中</span>
          <span className="pf-muted">¥{(usage?.frozen_yuan ?? 0).toFixed(2)}</span>
        </div>
      ) : null}

      <div className="pf-usage-foot">
        <span className="pf-muted">调用 {usage?.calls ?? 0} 次</span>
        {showTopup ? (
          <Link to="/pricing" className="pf-btn pf-btn-lime pf-btn-sm">
            去充值
          </Link>
        ) : null}
      </div>
    </div>
  )
}
