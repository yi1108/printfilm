import { notifyBillingErrorIfNeeded } from './billingError'

/** 解析 FastAPI detail 并抛出；402 / 余额不足时弹出充值引导 */
export function throwApiError(status: number, detail: unknown, fallback = '请求失败'): never {
  const message =
    typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
        : fallback
  const finalMessage = message || fallback
  notifyBillingErrorIfNeeded(status, finalMessage)
  throw new Error(finalMessage)
}
