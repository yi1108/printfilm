/** Retired selections fall forward without rewriting any saved canvas content. */
export function currentTextModel(value: string, fallback = '') {
  return /^(kimi(?:-|$)|gpt-5\.5$)/i.test(value) ? fallback || 'gpt-6.1-sol' : value || fallback
}
export function currentImageModel(value: string) {
  if (/^seedream-5[.-]0-(pro|flash)$/i.test(value)) return 'seedream-5.0'
  return value === 'gpt-image-2' ? 'gpt-image-2.5' : value
}
