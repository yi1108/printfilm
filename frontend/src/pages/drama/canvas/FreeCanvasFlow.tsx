/** React Flow 无限画布核心 */
import { useCallback, useEffect, useMemo, useRef } from 'react'
import {
  Background,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Connection,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { CanvasAssetNode } from './CanvasAssetNode'
import { useCanvasStore } from './CanvasStore'
import { CANVAS_SNAP_GRID } from './canvasTypes'

type FreeCanvasFlowProps = {
  projectId: number
}

/** 渲染 React Flow 无限画布 */
export function FreeCanvasFlow({ projectId }: FreeCanvasFlowProps) {
  const nodeTypes = useMemo(() => ({ asset: CanvasAssetNode }), [])
  const {
    nodes,
    edges,
    snapToGrid,
    showMinimap,
    onNodesChange,
    onEdgesChange,
    onConnect,
    pushSnapshot,
    focusNodeId,
    clearFocusNode,
  } = useCanvasStore()
  const { fitView, setCenter, getNode } = useReactFlow()
  const wrapperRef = useRef<HTMLDivElement>(null)
  const dragSnapshotPushed = useRef(false)

  /* 聚焦文件夹选中的节点 */
  useEffect(() => {
    if (!focusNodeId) return
    const node = getNode(focusNodeId)
    if (!node) {
      clearFocusNode()
      return
    }
    const w = 200
    const h = 240
    void setCenter(node.position.x + w / 2, node.position.y + h / 2, {
      zoom: 1,
      duration: 280,
    })
    clearFocusNode()
  }, [focusNodeId, getNode, setCenter, clearFocusNode])

  const isValidConnection = useCallback((connection: Connection | Edge) => {
    return connection.source !== connection.target
  }, [])

  const handlePaneClick = useCallback(() => {
    wrapperRef.current?.focus()
  }, [])

  /* 拖拽开始时压入历史快照（同一拖拽只压一次） */
  const handleNodeDragStart = useCallback(() => {
    if (!dragSnapshotPushed.current) {
      pushSnapshot()
      dragSnapshotPushed.current = true
    }
  }, [pushSnapshot])

  const handleNodeDragStop = useCallback(() => {
    dragSnapshotPushed.current = false
  }, [])

  /* 保证容器可聚焦；加载后有节点时适应视图 */
  useEffect(() => {
    wrapperRef.current?.focus()
  }, [projectId])

  const fittedRef = useRef(false)
  useEffect(() => {
    fittedRef.current = false
  }, [projectId])

  useEffect(() => {
    if (fittedRef.current || nodes.length === 0) return
    fittedRef.current = true
    void fitView({ padding: 0.2 })
  }, [nodes.length, fitView])

  return (
    <div
      ref={wrapperRef}
      tabIndex={0}
      className="free-canvas-flow"
      style={{ width: '100%', height: '100%', outline: 'none' }}
      data-project-id={projectId}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeDragStart={handleNodeDragStart}
        onNodeDragStop={handleNodeDragStop}
        isValidConnection={isValidConnection}
        onPaneClick={handlePaneClick}
        deleteKeyCode={['Backspace', 'Delete']}
        snapToGrid={snapToGrid}
        snapGrid={CANVAS_SNAP_GRID}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: 'default' }}
      >
        <Background gap={CANVAS_SNAP_GRID[0]} size={1.2} color="#cbd5e1" />
        {showMinimap ? (
          <MiniMap
            pannable
            zoomable
            style={{ bottom: 20, right: 20, borderRadius: 12, overflow: 'hidden' }}
          />
        ) : null}
      </ReactFlow>
    </div>
  )
}
