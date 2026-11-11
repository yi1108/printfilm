import { useState } from 'react'
import { useReactFlow, useViewport } from '@xyflow/react'
import { Focus, Magnet, Map, Spline } from 'lucide-react'

type StudioCanvasControlsProps = {
  showMap: boolean
  snap: boolean
  showEdges: boolean
  onShowMap: (value: boolean) => void
  onSnap: (value: boolean) => void
  onShowEdges: (value: boolean) => void
}

/** 左下角画布控制：小地图、吸附、连线显隐和缩放菜单。 */
export function StudioCanvasControls({ showMap, snap, showEdges, onShowMap, onSnap, onShowEdges }: StudioCanvasControlsProps) {
  const { fitView, zoomIn, zoomOut, zoomTo } = useReactFlow()
  const { zoom } = useViewport()
  const [menuOpen, setMenuOpen] = useState(false)
  const percent = Math.round(zoom * 100)

  /** 把百分比限制在和参考工作台接近的缩放范围内。 */
  function applyZoom(value: number) {
    const next = Math.min(400, Math.max(20, value))
    void zoomTo(next / 100, { duration: 150 })
  }

  return (
    <div className="pf-studio-controls" role="toolbar" aria-label="视图控制">
      <button type="button" aria-pressed={showMap} aria-label={showMap ? '隐藏地图' : '显示地图'} onClick={() => onShowMap(!showMap)}><Map size={16} /></button>
      <button type="button" aria-pressed={snap} aria-label={snap ? '关闭网格吸附' : '开启网格吸附'} onClick={() => onSnap(!snap)}><Magnet size={16} /></button>
      <button type="button" aria-pressed={showEdges} aria-label={showEdges ? '隐藏连线' : '显示连线'} onClick={() => onShowEdges(!showEdges)}><Spline size={16} /></button>
      <button type="button" aria-label="适应视图" onClick={() => { void fitView({ duration: 200 }) }}><Focus size={16} /></button>
      <div className="pf-studio-zoom-menu">
        <button type="button" aria-expanded={menuOpen} aria-label="缩放菜单" onClick={() => setMenuOpen((open) => !open)}>{percent}%</button>
        {menuOpen ? (
          <div role="menu">
            <label>缩放<input type="number" min={20} max={400} value={percent} aria-label="缩放百分比" onChange={(event) => applyZoom(Number(event.target.value))} />%</label>
            <button type="button" onClick={() => { void zoomIn({ duration: 150 }) }}>放大</button>
            <button type="button" onClick={() => { void zoomOut({ duration: 150 }) }}>缩小</button>
            <button type="button" onClick={() => { void fitView({ duration: 200 }); setMenuOpen(false) }}>适合屏幕</button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
