import { TeamEditingBoundary } from '../../../features/teams/TeamEditingBoundary'
/** 画布工作区：React Flow 与 overlay UI 组合 */
import { useCallback, useEffect } from 'react'
import { ReactFlowProvider, useReactFlow } from '@xyflow/react'
import { CanvasBottomControls } from './CanvasBottomControls'
import { CanvasLeftToolbar } from './CanvasLeftToolbar'
import { CanvasNodeSelector } from './CanvasNodeSelector'
import { CanvasStoreProvider, useCanvasStore } from './CanvasStore'
import { CanvasTopBar } from './CanvasTopBar'
import { getViewportCenterNodePosition } from './canvasNormalize'
import { CANVAS_NODE_SIZE, type CanvasNodeKind } from './canvasTypes'
import { FreeCanvasFlow } from './FreeCanvasFlow'
import { formatGenerationErrorMessage } from '../../../lib/generationError'
import './canvas.css'

type CanvasWorkspaceProps = {
  projectId: number
  /** fullscreen 独立页；embedded 嵌入分集编辑右侧 */
  variant?: 'fullscreen' | 'embedded'
}

/** 渲染画布主体与各区域 overlay */
function CanvasWorkspaceContent({
  projectId,
  variant = 'fullscreen',
}: CanvasWorkspaceProps) {
  const {
    showNodeSelector,
    errorMessage,
    setErrorMessage,
    addNodeOfKind,
    undo,
    redo,
    loading,
    flushSave,
  } = useCanvasStore()
  const { screenToFlowPosition } = useReactFlow()
  const embedded = variant === 'embedded'

  const handleSelectNode = useCallback(
    (kind: CanvasNodeKind) => {
      const size = CANVAS_NODE_SIZE[kind]
      const position = getViewportCenterNodePosition(screenToFlowPosition, size)
      void addNodeOfKind(kind, position)
    },
    [addNodeOfKind, screenToFlowPosition],
  )

  /* Ctrl/Cmd+S 保存；Ctrl/Cmd+Z / Ctrl+Shift+Z / Ctrl+Y 撤销重做 */
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey
      if (!meta) return
      const key = event.key.toLowerCase()
      if (key === 's') {
        event.preventDefault()
        void flushSave()
        return
      }
      if (key === 'z' && !event.shiftKey) {
        event.preventDefault()
        undo()
      } else if ((key === 'z' && event.shiftKey) || key === 'y') {
        event.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [undo, redo, flushSave])

  return (
    <div className={`free-canvas-page${embedded ? ' is-embedded' : ''}`}>
      <FreeCanvasFlow projectId={projectId} />
      <CanvasTopBar variant={variant} />
      <CanvasLeftToolbar onSelectNode={handleSelectNode} />
      <CanvasBottomControls />
      {showNodeSelector ? <CanvasNodeSelector onSelect={handleSelectNode} /> : null}
      {errorMessage ? (
        <p className="fc-error-toast" role="alert" onAnimationEnd={() => setErrorMessage('')}>
          {formatGenerationErrorMessage(errorMessage)}
        </p>
      ) : null}
      {loading ? (
        <p className="fc-error-toast" style={{ background: '#fff', color: '#64748b' }}>
          加载画布…
        </p>
      ) : null}
    </div>
  )
}

/** 提供 React Flow 与画布状态上下文 */
export function CanvasWorkspace({
  projectId,
  variant = 'fullscreen',
}: CanvasWorkspaceProps) {
  return (
    <TeamEditingBoundary projectId={projectId} type="canvas" resourceId={0}><CanvasStoreProvider projectId={projectId}>
      <ReactFlowProvider>
        <CanvasWorkspaceContent projectId={projectId} variant={variant} />
      </ReactFlowProvider>
    </CanvasStoreProvider></TeamEditingBoundary>
  )
}
