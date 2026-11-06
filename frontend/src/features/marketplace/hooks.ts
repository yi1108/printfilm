import { marketText as mt } from './translate'
import { useEffect, useState } from 'react'
import { request, type Capabilities } from './api'

// 菜单和页面以服务端开关为准，失败时不展示下游入口。
export function useMarketplace() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    request<Capabilities>('/capabilities').then(value => { if (active) setCapabilities(value) }).catch(() => { if (active) setError(mt("无法读取下游业务状态，请稍后重试")) })
    return () => { active = false }
  }, [])
  return { capabilities, error }
}
