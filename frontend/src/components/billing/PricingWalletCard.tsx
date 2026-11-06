import { points, pointText } from '../../lib/points'
import { ArrowUpRight, Eye, EyeOff, RefreshCw, WalletCards } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { UsageSummary, Wallet } from '../../api'
import { useI18n } from '../../i18n'

type Props = {
  wallet: Wallet | null
  usage: UsageSummary | null
  loggedIn: boolean
  updatedAt: Date | null
  loading: boolean
  error: boolean
  onRetry: () => void
  onHistory: () => void
}

// 账户更新时间使用浏览器本地时区。
function formatUpdated(d: Date | null) {
  if (!d) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 定价页深色余额卡片：余额、本月消耗、冻结、充值记录 */
export default function PricingWalletCard({ wallet, usage, loggedIn, updatedAt, loading, error, onRetry, onHistory }: Props) {
  /* 余额隐私开关与服务端返回的余额、冻结和本次消耗；尚未取得数据时不展示虚假的零余额。 */
  const { t } = useI18n()
  const [balanceVisible, setBalanceVisible] = useState(true)
  const hasBalance = loggedIn && Boolean(wallet || usage)
  const balanceYuan = wallet?.balance_fen ?? usage?.balance_fen ?? 0
  const frozenYuan = wallet?.frozen_fen ?? usage?.frozen_fen ?? 0
  const monthCharge = usage?.charge_fen ?? 0

  return (
    <aside className="pf-pricing-wallet-dark" aria-label={t('pricing.walletBalance')} aria-busy={loading}>
      <div className="pf-pricing-wallet-dark-head">
        <span className="pf-pricing-wallet-dark-label"><WalletCards size={17} aria-hidden />{t('pricing.walletBalance')}</span>
        <div className="pf-pricing-wallet-dark-actions">
          <button
            type="button"
            className="pf-pricing-wallet-eye"
            aria-label={balanceVisible ? t('pricing.hideBalance') : t('pricing.showBalance')}
            aria-pressed={!balanceVisible}
            disabled={!hasBalance}
            onClick={() => setBalanceVisible((v) => !v)}
          >
            {balanceVisible ? <Eye size={16} /> : <EyeOff size={16} />}
          </button>
          <button
            type="button"
            className="pf-pricing-wallet-history"
            disabled={!loggedIn}
            title={loggedIn ? t('pricing.history') : t('pricing.loginFirst')}
            onClick={onHistory}
          >
            {t('pricing.history')}<ArrowUpRight size={13} aria-hidden />
          </button>
        </div>
      </div>

      <strong className={`pf-pricing-wallet-dark-balance${loading && !hasBalance ? ' is-loading' : ''}`} aria-label={loading && !hasBalance ? t('pricing.loadingWallet') : undefined}>
        {hasBalance ? (balanceVisible ? points(balanceYuan) : pointText('**** 积分', '**** Points')) : '—'}
      </strong>

      <dl className="pf-pricing-wallet-dark-meta">
        <div>
          <dt>{t('pricing.monthCharge')}</dt>
          <dd>{loggedIn && usage ? (balanceVisible ? points(monthCharge) : pointText('**** 积分', '**** Points')) : '—'}</dd>
        </div>
        <div>
          <dt>{t('pricing.frozenLabel')}</dt>
          <dd>{hasBalance ? (balanceVisible ? points(frozenYuan) : pointText('**** 积分', '**** Points')) : '—'}</dd>
        </div>
        {wallet?.debt_fen !== undefined && <div><dt>{pointText('欠费', 'Debt')}</dt><dd>{balanceVisible ? points(wallet.debt_fen) : '****'}</dd></div>}
        {wallet?.spendable_fen !== undefined && <div><dt>{pointText('实际可消费', 'Spendable')}</dt><dd>{balanceVisible ? points(wallet.spendable_fen) : '****'}</dd></div>}
      </dl>

      {!loggedIn ? (
        <Link className="pf-pricing-wallet-login" to="/auth?next=%2Fpricing">{t('pricing.walletLogin')}<ArrowUpRight size={14} aria-hidden /></Link>
      ) : error ? (
        <p className="pf-pricing-wallet-error" role="status">{t('pricing.walletFailed')}<button type="button" onClick={onRetry} aria-label={t('pricing.retry')}><RefreshCw size={13} aria-hidden />{t('pricing.retry')}</button></p>
      ) : <p className="pf-pricing-wallet-dark-updated"><span className={loading ? 'is-loading' : ''} aria-hidden />{loading && !hasBalance ? t('pricing.loadingWallet') : t('pricing.updatedAt', { time: formatUpdated(updatedAt) })}</p>}
    </aside>
  )
}
