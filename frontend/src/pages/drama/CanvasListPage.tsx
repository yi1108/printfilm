import DramaListPage from './DramaListPage'
import { Navigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { isPrintfilmStudioEnabled } from '../../features/printfilm-studio/featureFlag'

/** 自由画布一级入口；工作区权限与项目管理沿用共享列表。 */
export default function CanvasListPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  useEffect(() => { let active = true; void isPrintfilmStudioEnabled().then((value) => active && setEnabled(value)).catch(() => active && setEnabled(false)); return () => { active = false } }, [])
  if (enabled === false) return <Navigate to="/drama" replace />
  if (enabled === null) return null
  return <DramaListPage workflow="canvas" />
}
