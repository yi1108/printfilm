export type BillingPayType = 'alipay' | 'wxpay' | 'stripe'
export type PaymentCurrency = 'cny' | 'usd' | 'hkd'
export type StripePaymentQuote = {
  payment_currency: PaymentCurrency
  payment_amount_minor: number
  payment_exchange_rate: string
}

function paymentCurrency(value: string | null | undefined): PaymentCurrency | null {
  return value === 'cny' || value === 'usd' || value === 'hkd' ? value : null
}

/** Foreign amounts are quoted by the server; the browser never computes an exchange rate. */
export function stripeSkuQuote(quote: StripePaymentQuote | null | undefined): StripePaymentQuote | null {
  if (!quote || !paymentCurrency(quote.payment_currency)
    || !Number.isSafeInteger(quote.payment_amount_minor) || quote.payment_amount_minor <= 0) return null
  return quote
}

export function paymentAmount(amountMinor: number): string {
  return (amountMinor / 100).toFixed(2)
}

/** Legacy orders without a payment snapshot used CNY. Invalid new snapshots stay unavailable. */
export function billingOrderCharge(order: {
  amount_fen: number
  payment_currency?: string | null
  payment_amount_minor?: number | null
}): { currency: PaymentCurrency; amountMinor: number } | null {
  const legacy = order.payment_currency == null && order.payment_amount_minor == null
  const currency = legacy ? 'cny' : paymentCurrency(order.payment_currency)
  const amountMinor = legacy ? order.amount_fen : order.payment_amount_minor
  if (!currency || !Number.isSafeInteger(amountMinor) || amountMinor == null || amountMinor < 0) return null
  return { currency, amountMinor }
}

export function billingOrderChargeLabel(order: Parameters<typeof billingOrderCharge>[0]): string {
  const charge = billingOrderCharge(order)
  return charge ? `${charge.currency.toUpperCase()} ${paymentAmount(charge.amountMinor)}` : '—'
}

/** Display only payment providers the server currently offers. */
export function availableBillingPayTypes(types: readonly string[]): BillingPayType[] {
  return [...new Set(types)].filter((type): type is BillingPayType =>
    type === 'alipay' || type === 'wxpay' || type === 'stripe',
  )
}

/** The return URL identifies an order to check; it never proves payment. */
export function billingPaymentReturn(params: URLSearchParams) {
  const outcome = params.get('payment')
  const order = params.get('order')?.trim()
  if (!order || !/^[A-Za-z0-9_-]{1,128}$/.test(order) || (outcome !== 'success' && outcome !== 'cancelled')) return null
  return { order, outcome }
}

export function billingReturnHint(status: string, outcome: string): string {
  if (status === 'paid') return 'pricing.paidOk'
  if (status === 'closed') return 'pricing.paymentClosed'
  return outcome === 'cancelled' ? 'pricing.paymentCancelled' : 'pricing.paymentPending'
}

/** Hosted Stripe Checkout URLs are HTTPS and stay on Stripe's checkout host. */
export function stripeCheckoutUrl(value: string | undefined): string | null {
  try {
    const url = new URL(value || '')
    return url.protocol === 'https:' && url.hostname === 'checkout.stripe.com' && !url.username && !url.password && !url.port
      ? url.href
      : null
  } catch {
    return null
  }
}
