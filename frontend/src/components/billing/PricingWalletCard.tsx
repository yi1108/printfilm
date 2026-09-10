import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'
import type { UsageSummary, Wallet } from '../../api'

type Props = {
  wallet: Wallet | null
  usage: UsageSummary | null
  loggedIn: boolean
  updatedAt: Date | null
  onHistory: () => void
}

function formatUpdated(d: Date | null) {
  if (!d) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 定价页深色余额卡片：余额、本月消耗、冻结、充值记录 */
export default function PricingWalletCard({ wallet, usage, loggedIn, updatedAt, onHistory }: Props) {
  const [balanceVisible, setBalanceVisible] = useState(true)

  const balanceYuan = wallet?.balance_yuan ?? usage?.balance_yuan ?? 0
  const frozenYuan = wallet?.frozen_yuan ?? usage?.frozen_yuan ?? 0
  const monthCharge = usage?.charge_yuan ?? 0

  return (
    <aside className="pf-pricing-wallet-dark">
      <div className="pf-pricing-wallet-dark-head">
        <span className="pf-pricing-wallet-dark-label">可用余额</span>
        <div className="pf-pricing-wallet-dark-actions">
          <button
            type="button"
            className="pf-pricing-wallet-eye"
            aria-label={balanceVisible ? '隐藏余额' : '显示余额'}
            onClick={() => setBalanceVisible((v) => !v)}
          >
            {balanceVisible ? <Eye size={16} /> : <EyeOff size={16} />}
          </button>
          <button
            type="button"
            className="pf-pricing-wallet-history"
            disabled={!loggedIn}
            title={loggedIn ? '查看充值记录' : '请先登录'}
            onClick={onHistory}
          >
            充值记录
          </button>
        </div>
      </div>

      <strong className="pf-pricing-wallet-dark-balance">
        {balanceVisible ? `¥${balanceYuan.toFixed(2)}` : '¥ ****'}
      </strong>

      <dl className="pf-pricing-wallet-dark-meta">
        <div>
          <dt>本次消耗</dt>
          <dd>{loggedIn ? `¥${monthCharge.toFixed(2)}` : '—'}</dd>
        </div>
        <div>
          <dt>冻结金额</dt>
          <dd>{loggedIn ? `¥${frozenYuan.toFixed(2)}` : '—'}</dd>
        </div>
      </dl>

      <p className="pf-pricing-wallet-dark-updated">更新于 {formatUpdated(updatedAt)}</p>
    </aside>
  )
}
