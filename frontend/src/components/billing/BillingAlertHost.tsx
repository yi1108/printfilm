import { points, pointText } from '../../lib/points'
import { useCallback, useEffect, useRef } from 'react'
import { api } from '../../api'
import { dialog } from '../../lib/dialog'

type BillingAlertItem = {
  id: number
  kind: string
  title: string
  message: string
  milestone_fen: number
  milestone_yuan: number
  created_at?: string | null
}

/** 轮询待展示的用户额度告警并弹窗提示。 */
export default function BillingAlertHost() {
  // 在发起 pending 请求前就上锁，避免 focus/interval/StrictMode 并发重入
  const showingRef = useRef(false)

  const checkAlerts = useCallback(async () => {
    if (!localStorage.getItem('token') || showingRef.current) return
    showingRef.current = true
    try {
      const res = await api.billingAlertsPending()
      const items = (res.items ?? []) as BillingAlertItem[]
      if (!items.length) return
      for (const item of items) {
        await dialog.alert({
          title: item.kind === 'user_milestone' ? pointText('积分消费提醒', 'Points usage reminder') : item.title || '消费提醒',
          message: item.kind === 'user_milestone' && Number.isSafeInteger(item.milestone_fen) ? pointText(`累计消费已达到 ${points(item.milestone_fen)}，请注意账户可用积分。`, `Your spending has reached ${points(item.milestone_fen)}. Please check your available Points.`) : item.message,
          confirmText: '知道了',
        })
        try {
          await api.billingAlertAck(item.id)
        } catch {
          // 已确认或并发 ack 导致 404 时忽略，避免反复重试刷屏
        }
      }
    } catch {
      // 未登录或网络异常时静默跳过
    } finally {
      showingRef.current = false
    }
  }, [])

  useEffect(() => {
    void checkAlerts()
    const timer = window.setInterval(() => void checkAlerts(), 30_000)
    const onFocus = () => void checkAlerts()
    window.addEventListener('focus', onFocus)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
    }
  }, [checkAlerts])

  return null
}
