import { points } from '../lib/points'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowUpRight,
  Check,
  CreditCard,
  Infinity as InfinityIcon,
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
import {
  availableBillingPayTypes,
  billingPaymentReturn,
  billingReturnHint, skuPriceDisplay,
  stripeCheckoutUrl,
  stripeSkuQuote,
  type BillingPayType,
} from '../lib/billingPayments'
import './pricing.css'

type SkuView = BillingSku & { recommended?: boolean }

// 展示充值权益时复用现有计费说明，不引入额外套餐或价格。
const HERO_FEATURES = [
  { key: 'featInstant', Icon: Zap },
  { key: 'featSafe', Icon: ShieldCheck },
  { key: 'featForever', Icon: InfinityIcon },
] as const

/** 定价与充值页 */
export default function PricingPage() {
  /* 路由与语言、账户数据、充值配置及支付弹窗的展示状态。 */
  const nav = useNavigate()
  const { t, m, locale } = useI18n()
  const [params] = useSearchParams()
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [skus, setSkus] = useState<SkuView[]>([])
  const [skusLoading, setSkusLoading] = useState(true)
  const [skusError, setSkusError] = useState(false)
  const [stripeUnavailable, setStripeUnavailable] = useState(false)
  const [skuLocale, setSkuLocale] = useState<string | null>(null)
  const skuRequest = useRef(0)
  const [walletLoading, setWalletLoading] = useState(Boolean(localStorage.getItem('token')))
  const [walletError, setWalletError] = useState(false)
  const [payType, setPayType] = useState<BillingPayType>('alipay')
  const [payTypes, setPayTypes] = useState<BillingPayType[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')
  const [checkout, setCheckout] = useState<PayCheckout | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const loggedIn = Boolean(localStorage.getItem('token'))
  const paymentReturn = useMemo(() => billingPaymentReturn(params), [params])

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
    const requestId = ++skuRequest.current
    setSkusLoading(true)
    setSkusError(false)
    setStripeUnavailable(false)
    try {
      const result = await api.billingSkus(locale)
      if (requestId !== skuRequest.current) return
      setStripeUnavailable(result.stripe_unavailable_reason === 'usd_rate_missing')
      setSkuLocale(locale)
      setSkus((result.skus || []) as SkuView[])
      const offered = availableBillingPayTypes(result.pay_types || [])
      setPayTypes(offered)
      setPayType((current) => offered.includes(current) ? current : offered[0] || 'alipay')
    } catch {
      if (requestId === skuRequest.current) {
        setSkusError(true)
        setSkuLocale(locale)
      }
    } finally {
      if (requestId === skuRequest.current) setSkusLoading(false)
    }
  }, [locale])

  useEffect(() => {
    void loadSkus()
    void refresh()
    if (params.get('paid') === '1') {
      setHint(t('pricing.paidHint'))
      const timerId = window.setInterval(() => refresh(), 2500)
      return () => window.clearInterval(timerId)
    }
  }, [loadSkus, refresh, params, t])

  // Checkout redirects can arrive before the webhook. Only the authenticated order confirms arrival.
  useEffect(() => {
    if (!loggedIn || !paymentReturn) return
    let stopped = false
    let timer: number | undefined
    let attempts = 0
    setError('')
    setHint(t('pricing.paymentChecking'))
    const checkOrder = async () => {
      try {
        const order = await api.getBillingOrder(paymentReturn.order)
        if (stopped) return
        setHint(t(billingReturnHint(order.status, paymentReturn.outcome)))
        setError('')
        if (order.status === 'paid') {
          await refresh()
          return
        }
        if (order.status === 'closed') return
      } catch {
        if (stopped) return
        setHint('')
        setError(t('pricing.paymentCheckFailed'))
      }
      if (!stopped && ++attempts < 48) timer = window.setTimeout(() => void checkOrder(), 2500)
    }
    void checkOrder()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [loggedIn, paymentReturn, refresh, t])

  // 保持服务端下单、支付渠道、订单字段和登录回跳行为。
  async function pay(sku: BillingSku) {
    if (skuLocale !== locale || skusLoading) return
    if (!loggedIn) {
      nav(`/auth?next=${encodeURIComponent(`/pricing#sku-${sku.id}`)}`)
      return
    }
    if (!payTypes.includes(payType)) return
    if (payType === 'stripe' && !stripeSkuQuote(sku.stripe_quote)) {
      setError(t('pricing.stripeQuoteUnavailable'))
      return
    }
    setBusy(sku.id)
    setError('')
    try {
      const order = await api.createBillingOrder(sku.id, payType, locale)
      if (order.pay_type === 'stripe') {
        const url = stripeCheckoutUrl(order.payurl)
        if (!url) throw new Error(t('pricing.paymentLinkFailed'))
        window.location.assign(url)
        return
      }
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
  function pickPay(type: BillingPayType) {
    setPayType(type)
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

              {!skusLoading && !skusError && payTypes.length === 0 ? (
                <p className="pf-pricing-pay-tip" role="status">{t('pricing.noPayMethods')}</p>
              ) : null}

              <div className="pf-pricing-pay-grid">
                {payTypes.map((type) => <button
                  type="button"
                  key={type}
                  className={`pf-pricing-pay-tile${payType === type ? ' is-active' : ''}`}
                  onClick={() => pickPay(type)}
                  aria-pressed={payType === type}
                >
                  {type === 'stripe' ? (
                    <span className="pf-pricing-pay-tile-icon" aria-hidden><CreditCard size={24} /></span>
                  ) : <PaymentBrandIcon brand={type} size="md" />}
                  <span className="pf-pricing-pay-tile-label">{t(`pricing.${type === 'wxpay' ? 'wechat' : type}`)}</span>
                  {payType === type ? (
                    <span className="pf-pricing-pay-tile-check" aria-hidden>
                      <Check size={14} strokeWidth={3} />
                    </span>
                  ) : null}
                </button>)}
              </div>
              {stripeUnavailable && skuLocale === locale && <p className="pf-muted" role="status">{t('pricing.stripeUsdUnavailable')}</p>}
            </section>

            <section className="pf-pricing-skus" id="pricing-skus" aria-labelledby="pricing-skus-title" aria-busy={skusLoading}>
              <header className="pf-pricing-section-head is-row">
                <h2 id="pricing-skus-title"><span className="pf-pricing-step" aria-hidden>02</span>{t('pricing.chooseAmount')}</h2>
                <p>{t('pricing.why1')}</p>
              </header>

              {skusLoading || skuLocale !== locale ? (
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
                  const stripeSelected = payType === 'stripe'
                  const quote = stripeSelected ? stripeSkuQuote(sku.stripe_quote) : null
                  const missingStripeQuote = stripeSelected && !quote
                  // 各支付方式统一「货币代码 + 两位小数」；Stripe 报价缺失时价格区显示占位并禁止下单。
                  const price = skuPriceDisplay({ stripeSelected, quote, amountFen: sku.amount_fen })
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
                        <span className="yen">{price?.currency ?? '—'}</span>
                        <strong>{price?.amount ?? '—'}</strong>
                      </div>
                      <p className="pf-pricing-sku-credit">
                        <span>{t('pricing.credit')}</span><em>{points(sku.credit_fen)}</em>
                      </p>
                      {missingStripeQuote ? <p className="pf-pricing-sku-exchange" role="status">{t('pricing.stripeQuoteUnavailable')}</p> : quote && quote.payment_currency !== 'cny' ? (
                        <p className="pf-pricing-sku-exchange">{t('pricing.stripeExchange', { currency: quote.payment_currency.toUpperCase(), rate: quote.payment_exchange_rate })}</p>
                      ) : null}
                      {bonus > 0 ? (
                        <p className="pf-pricing-sku-bonus"><Zap size={12} aria-hidden />{t('pricing.bonus', { amount: points(bonus) })}</p>
                      ) : (
                        <p className="pf-pricing-sku-bonus is-empty">&nbsp;</p>
                      )}
                      <button
                        type="button"
                        className={`pf-pricing-sku-cta${recommended ? ' is-primary' : ''}`}
                        disabled={Boolean(busy) || payTypes.length === 0 || missingStripeQuote}
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
