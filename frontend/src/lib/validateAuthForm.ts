/** 登录/注册表单校验：跨浏览器统一提示，不依赖原生 email bubble。 */
export function isValidEmailInput(value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed.includes('@')) return false
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)
}

export function isValidAuthPassword(value: string): boolean {
  return value.length >= 6 && value.length <= 64
}
