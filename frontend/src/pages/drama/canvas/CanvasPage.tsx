/** 自由画布页：全屏 React Flow 无限画布（无应用壳布局） */
import { useParams } from 'react-router-dom'
import RequireAuth from '../RequireAuth'
import { CanvasWorkspace } from './CanvasWorkspace'

/** 鉴权后渲染全屏自由画布 */
export default function CanvasPage() {
  return (
    <RequireAuth>
      <CanvasPageInner />
    </RequireAuth>
  )
}

/** 从路由读取 projectId 并挂载工作区 */
function CanvasPageInner() {
  const { projectId } = useParams()
  const id = Number(projectId)

  if (!Number.isFinite(id) || id <= 0) {
    return (
      <div className="free-canvas-page" style={{ display: 'grid', placeItems: 'center' }}>
        <p style={{ color: '#64748b' }}>无效的项目 ID</p>
      </div>
    )
  }

  return <CanvasWorkspace projectId={id} />
}
