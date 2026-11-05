import { pointText, points } from './points'
import { dialog } from './dialog'
import { workspaceScope } from '../features/teams/workspaceScope'

export const PRICING_PATH = '/pricing'

/** 是否为余额不足 / 计费拦截类错误 */
export function isBillingError(message: string) {
  return /余额不足|积分不足|insufficient points|请先充值|402|insufficient_balance/i.test(message)
}

/** 跳转定价页充值 */
export function goToTopup() {
  if (typeof window !== 'undefined') {
    window.location.assign(workspaceScope.teamId === null ? PRICING_PATH : `/teams/${workspaceScope.teamId}?tab=billing`)
  }
}

/**
 * 弹出余额不足提示；若用户选择去充值则跳转定价页。
 * @returns 是否已按计费错误处理
 */
export async function handleBillingError(
  err: unknown,
  navigate?: (path: string) => void,
): Promise<boolean> {
  const message = err instanceof Error ? err.message : String(err || '')
  if (!isBillingError(message)) return false
  if (workspaceScope.teamId !== null) {
    await dialog.alert({ title: '团队消费受限', message: `${message}。请在团队钱包查看本人额度；团队余额与充值由所有者管理。`, confirmText: '知道了' })
    return true
  }
  const go = await dialog.confirm({
    title: pointText('积分不足', 'Insufficient Points'),
    message: pointText('当前积分不足以开始生成，请先充值。', 'You do not have enough Points. Please top up to continue.'),
    confirmText: pointText('去充值', 'Top up'),
    cancelText: pointText('知道了', 'OK'),
    tone: 'danger',
  })
  if (go) {
    if (navigate) navigate(PRICING_PATH)
    else goToTopup()
  }
  return true
}

/**
 * API 层全局拦截：402 / 余额不足时弹出充值引导（不吞掉原错误）。
 */
export function notifyBillingErrorIfNeeded(status: number, message: string) {
  if (status === 402 || isBillingError(message)) {
    void handleBillingError(new Error(message))
  }
}

/** Only recognized system templates are converted; unknown text is retained. */
export function billingPointsMessage(message: string): string {
  const match = message.match(/^余额不足：需要 ¥(\d+\.\d{2})，当前 ¥(\d+\.\d{2})，请先充值$/)
  if (!match) return message
  const units = (value: string) => Number(value.replace('.', ''))
  return pointText(`积分不足：需要 ${points(units(match[1]))}，当前 ${points(units(match[2]))}，请先充值`, `Insufficient Points: required ${points(units(match[1]))}, available ${points(units(match[2]))}. Please top up.`)
}
