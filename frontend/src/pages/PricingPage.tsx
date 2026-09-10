import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Building2,
  Check,
  CreditCard,
  Infinity,
  ShieldCheck,
  Zap,
} from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import PaymentBrandIcon from '../components/billing/PaymentBrandIcon'
import PaymentModal, { type PayCheckout } from '../components/billing/PaymentModal'
import PricingWalletCard from '../components/billing/PricingWalletCard'
import TopupHistoryModal from '../components/billing/TopupHistoryModal'
import { api, type BillingSku, type UsageSummary, type Wallet } from '../api'
import { useI18n } from '../i18n'

type PayType = 'alipay' | 'wxpay'

type SkuView = BillingSku & { recommended?: boolean }

const HERO_FEATURE_KEYS = ['featInstant', 'featSafe', 'featForever'] as const

function yuan(fen: number) {
  return (fen / 100).toFixed(2)
}

function yuanShort(fen: number) {
  const v = fen / 100
  return Number.isInteger(v) ? String(v) : v.toFixed(2)
}

/** 定价与充值页 */
export default function PricingPage() {
  const nav = useNavigate()
  const { t, m } = useI18n()
  const [params] = useSearchParams()
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [skus, setSkus] = useState<SkuView[]>([])
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

  async function refresh() {
    if (!loggedIn) {
      setWallet(null)
      setUsage(null)
      setUpdatedAt(null)
      return
    }
    try {
      const [w, u] = await Promise.all([api.wallet(), api.usageSummary()])
      setWallet(w)
      setUsage(u)
      setUpdatedAt(new Date())
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    api.billingSkus().then((r) => setSkus((r.skus || []) as SkuView[]))
    refresh()
    if (params.get('paid') === '1') {
      setHint(t('pricing.paidHint'))
      const timerId = window.setInterval(() => refresh(), 2500)
      return () => window.clearInterval(timerId)
    }
  }, [])

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

  function pickPay(type: PayType) {
    setPayType(type)
    setPayTip('')
  }

  function pickUnavailable(label: string) {
    setPayTip(t('pricing.unavailable', { label }))
  }

  async function onPaid() {
    setHint(t('pricing.paidOk'))
    setCheckout(null)
    await refresh()
  }

  return (
    <AppShell active="pricing" hideFooter wide>
      <div className="pf-pricing-page">
        <section className="pf-pricing-hero-band">
          <div className="pf-pricing-hero-inner">
            <div className="pf-pricing-hero-copy">
              <h1>{t('pricing.title')}</h1>
              <p>{t('pricing.lead')}</p>
              <ul className="pf-pricing-hero-features">
                {HERO_FEATURE_KEYS.map((key, i) => {
                  const icons = [Zap, ShieldCheck, Infinity] as const
                  const Icon = icons[i]
                  return (
                  <li key={key}>
                    <span className="pf-pricing-hero-feature-icon" aria-hidden>
                      <Icon size={15} strokeWidth={2.2} />
                    </span>
                    {t(`pricing.${key}`)}
                  </li>
                  )
                })}
              </ul>
              {!loggedIn ? (
                <p className="pf-pricing-guest-tip">
                  {t('pricing.guestPrefix')}
                  <Link to="/auth?next=%2Fpricing">{t('pricing.guestLogin')}</Link>
                  {t('pricing.guestSuffix')}
                </p>
              ) : null}
            </div>
            <PricingWalletCard
              wallet={wallet}
              usage={usage}
              loggedIn={loggedIn}
              updatedAt={updatedAt}
              onHistory={() => setHistoryOpen(true)}
            />
          </div>
        </section>

        <div className="pf-pricing-body">
          {hint ? <p className="pf-pricing-hint">{hint}</p> : null}
          {error ? <p className="pf-error pf-pricing-error">{error}</p> : null}

          <section className="pf-pricing-pay-section" aria-label={t('pricing.payMethods')}>
            <header className="pf-pricing-section-head is-row">
              <h2>{t('pricing.payMethods')}</h2>
              <div className="pf-pricing-pay-trust">
                <ShieldCheck size={16} aria-hidden />
                <span>{t('pricing.paySafe')}</span>
              </div>
            </header>

            {payTip ? <p className="pf-pricing-pay-tip">{payTip}</p> : null}

            <div className="pf-pricing-pay-grid">
              <button
                type="button"
                className={`pf-pricing-pay-tile${payType === 'alipay' ? ' is-active' : ''}`}
                onClick={() => pickPay('alipay')}
                aria-pressed={payType === 'alipay'}
              >
                <PaymentBrandIcon brand="alipay" size="md" />
                <span className="pf-pricing-pay-tile-label">{t('pricing.alipay')}</span>
                <span className="pf-pricing-pay-tile-badge">{t('pricing.recommended')}</span>
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

          <section className="pf-pricing-skus" id="pricing-skus">
            <header className="pf-pricing-section-head">
              <h2>{t('pricing.chooseAmount')}</h2>
            </header>

            <div className="pf-pricing-sku-grid">
              {displaySkus.map((sku) => {
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
                    {recommended ? <span className="pf-pricing-rec-badge">{t('pricing.recommended')}</span> : null}
                    <p className="pf-pricing-sku-tier">{label}</p>
                    <p className="pf-pricing-sku-hint">{tierHint}</p>
                    <div className="pf-pricing-sku-price">
                      <span className="yen">¥</span>
                      <strong>{(sku.amount_fen / 100).toFixed(0)}</strong>
                    </div>
                    <p className="pf-pricing-sku-credit">
                      {t('pricing.credit')} <em>¥{yuan(sku.credit_fen)}</em>
                    </p>
                    {bonus > 0 ? (
                      <p className="pf-pricing-sku-bonus">{t('pricing.bonus', { amount: yuanShort(bonus) })}</p>
                    ) : (
                      <p className="pf-pricing-sku-bonus is-empty">&nbsp;</p>
                    )}
                    <button
                      type="button"
                      className={`pf-pricing-sku-cta${recommended ? ' is-primary' : ''}`}
                      disabled={Boolean(busy)}
                      onClick={() => pay(sku)}
                    >
                      {busy === sku.id ? t('pricing.ordering') : t('pricing.payNow')}
                    </button>
                  </article>
                )
              })}
            </div>
          </section>

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
              <Link to="/terms">{t('footer.terms')}</Link>
              <Link to="/privacy">{t('footer.privacy')}</Link>
              <Link to="/contact">{t('footer.contact')}</Link>
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
