/** Operational quantities use whole counts; never silently round input. */
export function operationInteger(value: unknown, max = 1_000_000_000): number {
  const text = String(value ?? '').trim()
  if (!/^\d+$/.test(text)) throw new Error('请输入有效的非负整数')
  const number = Number(text)
  if (!Number.isSafeInteger(number) || number > max) throw new Error(`数量不能超过 ${max.toLocaleString('zh-CN')}`)
  return number
}

export function displayMetricsInput(values: Record<string, unknown>, real: Record<string, number>) {
  return Object.fromEntries(['like_count', 'favorite_count', 'share_count'].map(key => {
    const value = operationInteger(values[key])
    if (value < (real[key] || 0)) throw new Error('展示数量不能小于真实数量；如需恢复真实数量，请清零初始值')
    return [key, value]
  })) as Record<'like_count' | 'favorite_count' | 'share_count', number>
}
