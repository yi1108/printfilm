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
  const showingRef = useRef(false)

  const checkAlerts = useCallback(async () => {
    if (!localStorage.getItem('token') || showingRef.current) return
    try {
      const res = await api.billingAlertsPending()
      const items = (res.items ?? []) as BillingAlertItem[]
      if (!items.length) return
      showingRef.current = true
      for (const item of items) {
        await dialog.alert({
          title: item.title || '消费提醒',
          message: item.message,
          confirmText: '知道了',
        })
        await api.billingAlertAck(item.id)
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
