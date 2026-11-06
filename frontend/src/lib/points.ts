/** Wallet quantities already use integer hundredths of CNY: 1 stored unit = 1 point. */
export function pointLocale(): 'zh' | 'en' {
  return typeof document !== 'undefined' && document.documentElement.lang.startsWith('en') ? 'en' : 'zh'
}

export function pointText(zh: string, en: string): string {
  return pointLocale() === 'en' ? en : zh
}

export function points(value: unknown, locale: 'zh' | 'en' = pointLocale()): string {
  return typeof value === 'number' && Number.isSafeInteger(value)
    ? `${value.toLocaleString(locale === 'en' ? 'en-US' : 'zh-CN')} ${locale === 'en' ? 'Points' : '积分'}` : '—'
}

/** No rounding, exponent notation, fractions or yuan conversion for account inputs. */
export function parsePoints(value: string, max = Number.MAX_SAFE_INTEGER): number | null {
  const text = value.trim()
  if (!/^\d+$/.test(text)) return null
  const amount = Number(text)
  return Number.isSafeInteger(amount) && amount <= max ? amount : null
}

/** Display sub-point unit rates exactly; final quotes retain the existing rounding. */
export function pointUnitRate(yuan: string): string {
  if (!/^\d+(\.\d{1,4})?$/.test(yuan)) return '—'
  const [whole, fraction = ''] = yuan.split('.')
  const units = BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
  const decimals = (units % 100n).toString().padStart(2, '0').replace(/0+$/, '')
  return `${units / 100n}${decimals ? '.' + decimals : ''}`
}
