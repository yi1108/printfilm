import { useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { Background, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { STUDIO_ADDABLE_TYPES, STUDIO_NODE_LABELS } from './flowAdapter'
import { StudioCanvasControls } from './StudioCanvasControls'
import { StudioChrome } from './StudioChrome'
import { StudioNode, StudioNodeEditContext } from './StudioNode'
import { useStudioCanvas, type StudioSaveStatus } from './useStudioCanvas'

const NODE_TYPES = {
  text: StudioNode,
  image: StudioNode,
  video: StudioNode,
  audio: StudioNode,
  script: StudioNode,
  asset: StudioNode,
  task: StudioNode,
  group: StudioNode,
}

type StudioCanvasProps = {
  projectId: number
  title: string
  statusText: string
  lockError: string
  writable: boolean
  teamLocked: boolean
  refreshToken: number
  agentOpen: boolean
  onStatus: (status: StudioSaveStatus) => void
  onRetryLock: () => void
  onTakeOver: () => void
  onToggleAgent: () => void
}

/** 铺满工作区的浅色画布，工具浮在画面上。 */
export function StudioCanvas(props: StudioCanvasProps) {
  return (
    <ReactFlowProvider>
      <StudioCanvasBody {...props} />
    </ReactFlowProvider>
  )
}

/** 画布主体，依赖 React Flow 上下文。 */
function StudioCanvasBody({ projectId, title, statusText, lockError, writable, teamLocked, refreshToken, agentOpen, onStatus, onRetryLock, onTakeOver, onToggleAgent }: StudioCanvasProps) {
  const canvas = useStudioCanvas({ projectId, writable, teamLocked, refreshToken })
  const { screenToFlowPosition } = useReactFlow()
  const nodeTypes = useMemo(() => NODE_TYPES, [])
  const surfaceRef = useRef<HTMLElement>(null)
  /*
   * tool 移动或抓手
   * showMap 小地图
   * snap 网格吸附
   * showEdges 连线可见
   * paneMenu 双击画布后的添加菜单位置
   */
  const [tool, setTool] = useState<'move' | 'hand'>('move')
  const [showMap, setShowMap] = useState(false)
  const [snap, setSnap] = useState(false)
  const [showEdges, setShowEdges] = useState(true)
  const [paneMenu, setPaneMenu] = useState<{ left: number; top: number; x: number; y: number } | null>(null)
  useEffect(() => { onStatus(canvas.status) }, [canvas.status, onStatus])
  const moving = tool === 'move'
  const selectedCount = canvas.nodes.filter((node) => node.selected).length

  /** 双击空白处在指针位置打开添加菜单，单击则关掉菜单。 */
  function openPaneMenu(event: MouseEvent) {
    if (event.detail !== 2 || !writable) {
      setPaneMenu(null)
      return
    }
    const bounds = surfaceRef.current?.getBoundingClientRect()
    const flow = screenToFlowPosition({ x: event.clientX, y: event.clientY })
    setPaneMenu({ left: event.clientX - (bounds?.left ?? 0), top: event.clientY - (bounds?.top ?? 0), x: flow.x, y: flow.y })
  }

  return (
    <StudioNodeEditContext.Provider value={canvas.updateNodeText}>
      <section ref={surfaceRef} className={`pf-studio-canvas${showEdges ? '' : ' is-edges-hidden'}`} aria-label="工作室画布">
        {canvas.status !== 'loading' ? (
          <ReactFlow
            key={canvas.flowKey}
            nodes={canvas.nodes}
            edges={canvas.edges}
            nodeTypes={nodeTypes}
            defaultViewport={canvas.viewport}
            defaultEdgeOptions={{ style: { stroke: '#111318', strokeWidth: 1.5 } }}
            onNodesChange={canvas.handleNodesChange}
            onEdgesChange={canvas.handleEdgesChange}
            onConnect={canvas.handleConnect}
            onMoveEnd={canvas.handleMoveEnd}
            onPaneClick={openPaneMenu}
            onInit={canvas.markReady}
            nodesDraggable={writable && moving}
            nodesConnectable={writable && moving}
            elementsSelectable={moving}
            selectionOnDrag={moving}
            panOnDrag={moving ? [1, 2] : true}
            snapToGrid={snap}
            snapGrid={[16, 16]}
            deleteKeyCode={writable ? ['Backspace', 'Delete'] : null}
            fitView={(canvas.nodes.length > 0 && canvas.viewport.x === 0 && canvas.viewport.y === 0 && canvas.viewport.zoom === 1)}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={18} color="rgba(17, 19, 24, 0.16)" />
            {showMap ? <MiniMap pannable zoomable position="bottom-left" maskColor="rgba(247,248,250,0.72)" nodeColor="#d9dde3" style={{ left: 12, bottom: 62 }} /> : null}
            <StudioCanvasControls showMap={showMap} snap={snap} showEdges={showEdges} onShowMap={setShowMap} onSnap={setSnap} onShowEdges={setShowEdges} />
          </ReactFlow>
        ) : <p className="pf-studio-canvas-state">正在加载画布…</p>}
        {canvas.status !== 'loading' && canvas.nodes.length === 0 ? (
          <div className="pf-studio-empty">
            <strong>从这里开始创作</strong>
            <p>双击画布，或选择一种节点。</p>
            <div>
              {STUDIO_ADDABLE_TYPES.map((type) => (
                <button key={type} type="button" disabled={!writable} onClick={() => canvas.addNode(type)}>{STUDIO_NODE_LABELS[type]}</button>
              ))}
            </div>
          </div>
        ) : null}
        {paneMenu ? (
          <div className="pf-studio-pane-menu" style={{ left: paneMenu.left, top: paneMenu.top }} role="menu">
            {STUDIO_ADDABLE_TYPES.map((type) => (
              <button key={type} type="button" role="menuitem" onClick={() => { canvas.addNode(type, paneMenu); setPaneMenu(null) }}>{STUDIO_NODE_LABELS[type]}</button>
            ))}
          </div>
        ) : null}
        {selectedCount > 0 ? (
          <div className="pf-studio-selection" role="toolbar" aria-label="选中节点">
            <span>已选 {selectedCount}</span>
            <button type="button" disabled={!writable} onClick={canvas.duplicateSelected}>复制</button>
            <button type="button" disabled={!writable} onClick={canvas.removeSelected}>删除</button>
          </div>
        ) : null}
        {canvas.error ? <p className="pf-studio-canvas-state is-error" role="alert">{canvas.error}</p> : null}
        <StudioChrome
          title={title}
          statusText={statusText}
          lockError={lockError}
          writable={writable}
          loading={canvas.status === 'loading'}
          tool={tool}
          agentOpen={agentOpen}
          onTool={setTool}
          onAdd={canvas.addNode}
          onRetryLock={onRetryLock}
          onTakeOver={onTakeOver}
          onToggleAgent={onToggleAgent}
        />
      </section>
    </StudioNodeEditContext.Provider>
  )
}
