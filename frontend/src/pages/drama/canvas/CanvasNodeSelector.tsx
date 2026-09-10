/** 空画布居中展示的默认节点选择器 */
import { MousePointer2 } from 'lucide-react'
import { CANVAS_NODE_OPTIONS, type CanvasNodeKind } from './canvasTypes'

type CanvasNodeSelectorProps = {
  onSelect: (kind: CanvasNodeKind) => void
}

/** 渲染快速新建节点类型选择器 */
export function CanvasNodeSelector({ onSelect }: CanvasNodeSelectorProps) {
  return (
    <div className="fc-overlay fc-node-selector">
      <div className="fc-node-selector-inner">
        <div className="fc-node-selector-row">
          {CANVAS_NODE_OPTIONS.map((option) => {
            const Icon = option.icon
            return (
              <button
                key={option.id}
                type="button"
                className="fc-node-chip"
                onClick={() => onSelect(option.id)}
              >
                <span className="fc-node-chip-icon">
                  <Icon size={16} strokeWidth={1.8} />
                </span>
                <span>{option.label}</span>
              </button>
            )
          })}
        </div>
        <p className="fc-node-hint">
          <MousePointer2 size={16} strokeWidth={1.8} />
          点击快速添加
        </p>
      </div>
    </div>
  )
}
