/** 画布左下角缩放与撤销控制条 */
import { useCallback, useState } from 'react'
import { LocateFixed, Magnet, Map, Minus, Plus, Redo2, Scan, Undo2 } from 'lucide-react'
import { useOnViewportChange, useReactFlow } from '@xyflow/react'
import { useCanvasStore } from './CanvasStore'

/** 渲染画布左下角控制条 */
export function CanvasBottomControls() {
  const {
    snapToGrid,
    showMinimap,
    canUndo,
    canRedo,
    toggleSnapToGrid,
    toggleMinimap,
    undo,
    redo,
  } = useCanvasStore()
  const { zoomIn, zoomOut, fitView, setViewport, getViewport } = useReactFlow()
  const [zoomPercent, setZoomPercent] = useState(100)

  useOnViewportChange({
    onChange: (viewport) => {
      setZoomPercent(Math.round(viewport.zoom * 100))
    },
  })

  const handleResetZoom = useCallback(() => {
    const viewport = getViewport()
    void setViewport({ ...viewport, zoom: 1 }, { duration: 200 })
  }, [getViewport, setViewport])

  return (
    <div className="fc-overlay fc-bottom-controls">
      <div className="fc-bottom-bar">
        <button
          type="button"
          className="fc-icon-btn is-sm"
          aria-label="撤销"
          title="撤销"
          disabled={!canUndo}
          onClick={undo}
        >
          <Undo2 size={16} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="fc-icon-btn is-sm"
          aria-label="重做"
          title="重做"
          disabled={!canRedo}
          onClick={redo}
        >
          <Redo2 size={16} strokeWidth={1.8} />
        </button>

        <span className="fc-bottom-sep" />

        <button
          type="button"
          className="fc-icon-btn is-sm"
          aria-label="定位到内容"
          title="定位到内容"
          onClick={() => void fitView({ duration: 200 })}
        >
          <LocateFixed size={16} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="fc-icon-btn is-sm"
          aria-label="适应画布"
          title="适应画布"
          onClick={() => void fitView({ duration: 200, padding: 0.2 })}
        >
          <Scan size={16} strokeWidth={1.8} />
        </button>

        <span className="fc-bottom-sep" />

        <button
          type="button"
          className={`fc-icon-btn is-sm${snapToGrid ? ' is-active' : ''}`}
          aria-label={snapToGrid ? '关闭网格吸附' : '开启网格吸附'}
          title={snapToGrid ? '关闭网格吸附' : '开启网格吸附'}
          aria-pressed={snapToGrid}
          onClick={toggleSnapToGrid}
        >
          <Magnet size={16} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className={`fc-icon-btn is-sm${showMinimap ? ' is-active' : ''}`}
          aria-label={showMinimap ? '关闭小地图' : '开启小地图'}
          title={showMinimap ? '关闭小地图' : '开启小地图'}
          aria-pressed={showMinimap}
          onClick={toggleMinimap}
        >
          <Map size={16} strokeWidth={1.8} />
        </button>

        <span className="fc-bottom-sep" />

        <button
          type="button"
          className="fc-icon-btn is-sm"
          aria-label="缩小"
          title="缩小"
          onClick={() => zoomOut({ duration: 150 })}
        >
          <Minus size={16} strokeWidth={1.8} />
        </button>
        <button
          type="button"
          className="fc-zoom-label"
          aria-label="重置缩放"
          title="重置缩放"
          onClick={handleResetZoom}
        >
          {zoomPercent}%
        </button>
        <button
          type="button"
          className="fc-icon-btn is-sm"
          aria-label="放大"
          title="放大"
          onClick={() => zoomIn({ duration: 150 })}
        >
          <Plus size={16} strokeWidth={1.8} />
        </button>
      </div>
    </div>
  )
}
