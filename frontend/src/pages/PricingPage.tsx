import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Building2,
  ArrowUpRight,
  Check,
  CreditCard,
  Infinity,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  WalletCards,
  Zap,
} from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import PaymentBrandIcon from '../components/billing/PaymentBrandIcon'
import PaymentModal, { type PayCheckout } from '../components/billing/PaymentModal'
import PricingWalletCard from '../components/billing/PricingWalletCard'
import TopupHistoryModal from '../components/billing/TopupHistoryModal'
import { api, type BillingSku, type UsageSummary, type Wallet } from '../api'
import { useI18n } from '../i18n'
import { GITHUB_REPO_URL } from '../lib/siteLinks'
import './pricing.css'

type PayType = 'alipay' | 'wxpay'

type SkuView = BillingSku & { recommended?: boolean }

// 展示充值权益时复用现有计费说明，不引入额外套餐或价格。
const HERO_FEATURES = [
  { key: 'featInstant', Icon: Zap },
  { key: 'featSafe', Icon: ShieldCheck },
  { key: 'featForever', Icon: Infinity },
] as const

// 分转元，到账金额固定展示两位小数。
function yuan(fen: number) {
  return (fen / 100).toFixed(2)
}

// 充值价格与赠送金额保留真实小数，整数金额省略小数位。
function yuanShort(fen: number) {
  const v = fen / 100
  return Number.isInteger(v) ? String(v) : v.toFixed(2)
}

/** 定价与充值页 */
export default function PricingPage() {
  /* 路由与语言、账户数据、充值配置及支付弹窗的展示状态。 */
  const nav = useNavigate()
  const { t, m } = useI18n()
  const [params] = useSearchParams()
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [skus, setSkus] = useState<SkuView[]>([])
  const [skusLoading, setSkusLoading] = useState(true)
  const [skusError, setSkusError] = useState(false)
  const [walletLoading, setWalletLoading] = useState(Boolean(localStorage.getItem('token')))
  const [walletError, setWalletError] = useState(false)
  const [payType, setPayType] = useState<PayType>('alipay')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')
  const [payTip, setPayTip] = useState('')
  const [checkout, setCheckout] = useState<PayCheckout | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const loggedIn = Boolean(localStorage.getItem('token'))

  const displaySkus = useMemo(() => {
    return skus.map((s) => ({
      ...s,
      recommended: s.id === 'topup_99' || Boolean((s as SkuView).recommended),
    }))
  }, [skus])

  // 加载余额与本次消耗，失败时保留已经取得的数据并提供重试。
  const refresh = useCallback(async () => {
    if (!loggedIn) {
      setWallet(null)
      setUsage(null)
      setUpdatedAt(null)
      setWalletLoading(false)
      setWalletError(false)
      return
    }
    setWalletLoading(true)
    setWalletError(false)
    try {
      const [w, u] = await Promise.all([api.wallet(), api.usageSummary()])
      setWallet(w)
      setUsage(u)
      setUpdatedAt(new Date())
    } catch {
      setWalletError(true)
    } finally {
      setWalletLoading(false)
    }
  }, [loggedIn])

  // 独立加载服务端 SKU，重试时不影响账户余额或当前支付方式。
  const loadSkus = useCallback(async () => {
    setSkusLoading(true)
    setSkusError(false)
    try {
      const result = await api.billingSkus()
      setSkus((result.skus || []) as SkuView[])
    } catch {
      setSkusError(true)
    } finally {
      setSkusLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadSkus()
    void refresh()
    if (params.get('paid') === '1') {
      setHint(t('pricing.paidHint'))
      const timerId = window.setInterval(() => refresh(), 2500)
      return () => window.clearInterval(timerId)
    }
  }, [loadSkus, refresh])

  // 保持服务端下单、支付渠道、订单字段和登录回跳行为。
  async function pay(sku: BillingSku) {
    if (!loggedIn) {
      nav(`/auth?next=${encodeURIComponent(`/pricing#sku-${sku.id}`)}`)
      return
    }
    setBusy(sku.id)
    setError('')
    try {
      const order = await api.createBillingOrder(sku.id, payType)
      const label = m.pricing.skus[sku.id as keyof typeof m.pricing.skus] || sku.name
      setCheckout({
        out_trade_no: order.out_trade_no,
        sku_id: order.sku_id || sku.id,
        sku_name: label,
        pay_type: order.pay_type,
        amount_fen: order.amount_fen,
        credit_fen: order.credit_fen,
        pay_mode: order.pay_mode || (order.qr_payload || order.qrcode ? 'qr' : 'redirect'),
        qr_payload: order.qr_payload || order.qrcode || order.img || '',
        payurl: order.payurl || order.submit_url || '',
        img: order.img,
        expire_seconds: order.expire_seconds ?? 300,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : t('pricing.orderFailed'))
    } finally {
      setBusy(null)
    }
  }

  // 选择已经开放的支付渠道。
  function pickPay(type: PayType) {
    setPayType(type)
    setPayTip('')
  }

  // 未开放渠道仅显示提示，不创建订单。
  function pickUnavailable(label: string) {
    setPayTip(t('pricing.unavailable', { label }))
  }

  // 支付成功后关闭结算弹窗并刷新账户数据。
  async function onPaid() {
    setHint(t('pricing.paidOk'))
    setCheckout(null)
    await refresh()
  }

  return (
    <AppShell active="pricing" hideFooter wide>
      <div className="pf-pricing-page">
        <section className="pf-pricing-hero-band" aria-labelledby="pricing-title">
          <div className="pf-pricing-hero-inner">
            <div className="pf-pricing-hero-copy">
              <p className="pf-pricing-eyebrow"><span aria-hidden />{t('pricing.eyebrow')}</p>
              <h1 id="pricing-title">{t('pricing.title')}</h1>
              <p className="pf-pricing-lead">{t('pricing.lead')}</p>
              <ul className="pf-pricing-hero-features">
                {HERO_FEATURES.map(({ key, Icon }) => (
                  <li key={key}>
                    <span className="pf-pricing-hero-feature-icon" aria-hidden>
                      <Icon size={15} strokeWidth={2.2} />
                    </span>
                    {t(`pricing.${key}`)}
                  </li>
                ))}
              </ul>
              {!loggedIn ? (
                <p className="pf-pricing-guest-tip">
                  {t('pricing.guestPrefix')}
                  <Link to="/auth?next=%2Fpricing">{t('pricing.guestLogin')}</Link>
                  {t('pricing.guestSuffix')}
                  <ArrowUpRight size={14} aria-hidden />
                </p>
              ) : null}
            </div>
            <PricingWalletCard
              wallet={wallet}
              usage={usage}
              loggedIn={loggedIn}
              updatedAt={updatedAt}
              loading={walletLoading}
              error={walletError}
              onRetry={() => void refresh()}
              onHistory={() => setHistoryOpen(true)}
            />
          </div>
        </section>

        <div className="pf-pricing-body">
          {hint ? <p className="pf-pricing-hint" role="status"><Check size={18} aria-hidden />{hint}</p> : null}
          {error ? <p className="pf-error pf-pricing-error" role="alert">{error}</p> : null}

          <div className="pf-pricing-topup-panel">
            <section className="pf-pricing-pay-section" aria-label={t('pricing.payMethods')}>
              <header className="pf-pricing-section-head is-row">
                <h2><span className="pf-pricing-step" aria-hidden>01</span>{t('pricing.payMethods')}</h2>
                <div className="pf-pricing-pay-trust">
                  <ShieldCheck size={16} aria-hidden />
                  <span>{t('pricing.paySafe')}</span>
                </div>
              </header>

              {payTip ? <p className="pf-pricing-pay-tip" role="status">{payTip}</p> : null}

              <div className="pf-pricing-pay-grid">
                <button
                  type="button"
                  className={`pf-pricing-pay-tile${payType === 'alipay' ? ' is-active' : ''}`}
                  onClick={() => pickPay('alipay')}
                  aria-pressed={payType === 'alipay'}
                >
                  <PaymentBrandIcon brand="alipay" size="md" />
                  <span className="pf-pricing-pay-tile-label">{t('pricing.alipay')}</span>
                  {payType === 'alipay' ? (
                    <span className="pf-pricing-pay-tile-check" aria-hidden>
                      <Check size={14} strokeWidth={3} />
                    </span>
                  ) : null}
                </button>

                <button
                  type="button"
                  className={`pf-pricing-pay-tile${payType === 'wxpay' ? ' is-active' : ''}`}
                  onClick={() => pickPay('wxpay')}
                  aria-pressed={payType === 'wxpay'}
                >
                  <PaymentBrandIcon brand="wxpay" size="md" />
                  <span className="pf-pricing-pay-tile-label">{t('pricing.wechat')}</span>
                  {payType === 'wxpay' ? (
                    <span className="pf-pricing-pay-tile-check" aria-hidden>
                      <Check size={14} strokeWidth={3} />
                    </span>
                  ) : null}
                </button>

                <button
                  type="button"
                  className="pf-pricing-pay-tile is-disabled"
                  title={t('pricing.soonTitle')}
                  onClick={() => pickUnavailable(t('pricing.unionpay'))}
                >
                  <PaymentBrandIcon brand="unionpay" size="md" />
                  <span className="pf-pricing-pay-tile-label">{t('pricing.unionpay')}</span>
                  <span className="pf-pricing-pay-tile-soon">{t('common.comingSoon')}</span>
                </button>

                <button
                  type="button"
                  className="pf-pricing-pay-tile is-disabled"
                  title={t('pricing.transferTitle')}
                  onClick={() => pickUnavailable(t('pricing.transfer'))}
                >
                  <span className="pf-pricing-pay-tile-icon" aria-hidden>
                    <Building2 size={22} strokeWidth={1.8} />
                  </span>
                  <span className="pf-pricing-pay-tile-label">{t('pricing.transfer')}</span>
                  <span className="pf-pricing-pay-tile-sub">{t('pricing.enterprise')}</span>
                </button>
              </div>
            </section>

            <section className="pf-pricing-skus" id="pricing-skus" aria-labelledby="pricing-skus-title" aria-busy={skusLoading}>
              <header className="pf-pricing-section-head is-row">
                <h2 id="pricing-skus-title"><span className="pf-pricing-step" aria-hidden>02</span>{t('pricing.chooseAmount')}</h2>
                <p>{t('pricing.why1')}</p>
              </header>

              {skusLoading ? (
                <div className="pf-pricing-sku-grid" role="status" aria-label={t('pricing.loadingSkus')}>
                  {[0, 1, 2, 3].map((index) => <div className="pf-pricing-sku-skeleton" key={index} aria-hidden><i /><i /><i /><i /></div>)}
                  <span className="pf-pricing-sr-only">{t('pricing.loadingSkus')}</span>
                </div>
              ) : skusError ? (
                <div className="pf-pricing-state" role="alert">
                  <RefreshCw size={26} aria-hidden />
                  <h3>{t('pricing.skusFailed')}</h3>
                  <p>{t('pricing.skusFailedHint')}</p>
                  <button className="pf-pricing-retry" type="button" onClick={() => void loadSkus()}>{t('pricing.retry')}</button>
                </div>
              ) : displaySkus.length === 0 ? (
                <div className="pf-pricing-state" role="status">
                  <WalletCards size={28} aria-hidden />
                  <h3>{t('pricing.noSkus')}</h3>
                  <p>{t('pricing.noSkusHint')}</p>
                  <Link to="/contact">{t('footer.contact')}<ArrowUpRight size={15} aria-hidden /></Link>
                </div>
              ) : <div className="pf-pricing-sku-grid">
                {displaySkus.map((sku) => {
                  // 金额与赠送余额全部取自服务端 SKU。
                  const bonus = sku.credit_fen - sku.amount_fen
                  const recommended = Boolean(sku.recommended)
                  const label = m.pricing.skus[sku.id as keyof typeof m.pricing.skus] || sku.name
                  const tierHint =
                    m.pricing.skuHints[sku.id as keyof typeof m.pricing.skuHints] || t('pricing.foreverHint')
                  return (
                    <article
                      key={sku.id}
                      id={`sku-${sku.id}`}
                      className={`pf-pricing-sku-card${recommended ? ' is-recommended' : ''}`}
                    >
                      <div className="pf-pricing-sku-card-head">
                        <p className="pf-pricing-sku-tier">{label}</p>
                        {recommended ? <span className="pf-pricing-rec-badge">{t('pricing.recommended')}</span> : null}
                      </div>
                      <p className="pf-pricing-sku-hint">{tierHint}</p>
                      <div className="pf-pricing-sku-price">
                        <span className="yen">¥</span>
                        <strong>{yuanShort(sku.amount_fen)}</strong>
                      </div>
                      <p className="pf-pricing-sku-credit">
                        <span>{t('pricing.credit')}</span><em>¥{yuan(sku.credit_fen)}</em>
                      </p>
                      {bonus > 0 ? (
                        <p className="pf-pricing-sku-bonus"><Zap size={12} aria-hidden />{t('pricing.bonus', { amount: yuanShort(bonus) })}</p>
                      ) : (
                        <p className="pf-pricing-sku-bonus is-empty">&nbsp;</p>
                      )}
                      <button
                        type="button"
                        className={`pf-pricing-sku-cta${recommended ? ' is-primary' : ''}`}
                        disabled={Boolean(busy)}
                        onClick={() => pay(sku)}
                        aria-busy={busy === sku.id}
                      >
                        {busy === sku.id ? <LoaderCircle className="pf-pricing-spinner" size={16} aria-hidden /> : null}
                        {busy === sku.id ? t('pricing.ordering') : t('pricing.payNow')}
                        {!busy ? <ArrowUpRight size={16} aria-hidden /> : null}
                      </button>
                    </article>
                  )
                })}
              </div>}
            </section>
          </div>

          <section className="pf-pricing-info">
            <article className="pf-pricing-info-card">
              <div className="pf-pricing-info-visual is-billing" aria-hidden>
                <CreditCard size={28} strokeWidth={1.6} />
              </div>
              <div>
                <h3>{t('pricing.billingTitle')}</h3>
                <ul>
                  <li>{t('pricing.billing1')}</li>
                  <li>{t('pricing.billing2')}</li>
                  <li>{t('pricing.billing3')}</li>
                </ul>
              </div>
            </article>
            <article className="pf-pricing-info-card">
              <div className="pf-pricing-info-visual is-value" aria-hidden>
                <Check size={28} strokeWidth={2.5} />
              </div>
              <div>
                <h3>{t('pricing.whyTitle')}</h3>
                <ul className="pf-pricing-checks">
                  <li>{t('pricing.why1')}</li>
                  <li>{t('pricing.why2')}</li>
                  <li>{t('pricing.why3')}</li>
                </ul>
              </div>
            </article>
          </section>

          <footer className="pf-pricing-site-foot">
            <p className="pf-pricing-site-brand">
              <Link to="/">PRINTFILM</Link>
              <span> · {t('pricing.footBrand')}</span>
            </p>
            <nav className="pf-pricing-site-links" aria-label={t('footer.links')}>
              <a href="/terms">{t('footer.terms')}</a>
              <a href="/privacy">{t('footer.privacy')}</a>
              <Link to="/contact">{t('footer.contact')}</Link>
              <a href={GITHUB_REPO_URL} target="_blank" rel="noopener noreferrer">
                {t('footer.github')}
              </a>
            </nav>
            <p className="pf-pricing-site-copy">© {new Date().getFullYear()} PRINTFILM. All rights reserved.</p>
          </footer>
        </div>
      </div>

      <PaymentModal
        open={Boolean(checkout)}
        checkout={checkout}
        onClose={() => setCheckout(null)}
        onPaid={() => void onPaid()}
      />
      <TopupHistoryModal open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </AppShell>
  )
}
