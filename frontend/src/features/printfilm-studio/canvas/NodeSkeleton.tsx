import { useRef, useState, type ReactNode } from 'react'
import { Handle, NodeResizeControl, Position } from '@xyflow/react'
import { Download, Eye, MoreHorizontal, MoveDiagonal2, Trash2 } from 'lucide-react'
import { cleanNodeTitle } from './nodePresentation'

type Props = {
  selected?: boolean
  busy?: boolean
  title: string
  icon: ReactNode
  badge?: string
  topVisible?: boolean
  bottomVisible?: boolean
  keepBottomMounted?: boolean
  topActions?: ReactNode
  topRightActions?: ReactNode
  bottom?: ReactNode
  children: ReactNode
  onMenu?: (event: React.MouseEvent) => void
  onPreview?: () => void
  onDownload?: () => void
  onRemove?: () => void
  canPreview?: boolean
  canDownload?: boolean
  width?: number | string
  height?: number
  writable?: boolean
  onRename?: (value: string) => void
  onResize?: (width: number, height: number) => void
  onResizeStart?: () => void
  mediaKind?: string
  /** 空态小卡 / 有媒体时加宽。 */
  empty?: boolean
  hasMedia?: boolean
  /** 选中展开生成面板时再加宽。 */
  hasComposer?: boolean
  output?: boolean
}

/** 对照 Toonflow nodeSkeleton：标题栏 + 内容卡 + 选中时上下浮层槽位。 */
export function NodeSkeleton({
  selected, busy, title, icon, badge, topVisible, bottomVisible, keepBottomMounted, topActions, topRightActions, bottom, children,
  onMenu, onPreview, onDownload, onRemove, canPreview, canDownload, width, height, writable, onRename, onResize, onResizeStart, mediaKind, empty, hasMedia, hasComposer, output = true,
}: Props) {
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(title)
  const cancelRename = useRef(false)
  const rename = () => { if (writable && onRename) { cancelRename.current = false; setDraft(title); setRenaming(true) } }
  const finishRename = () => { if (!cancelRename.current) onRename?.(cleanNodeTitle(draft, title)); setRenaming(false) }
  const cls = `pf-skel${selected ? ' is-selected' : ''}${busy ? ' is-busy' : ''}${empty ? ' is-empty' : ''}${hasMedia ? ' has-media' : ''}${hasComposer ? ' has-composer' : ''}`
  // React Flow reports 0 before its first measurement. Applying that value as
  // a fixed height prevents measurement and leaves the entire node hidden.
  return <div className={cls} style={{ width, height: height && height > 0 ? height : undefined }} data-media-kind={mediaKind} data-sized={height && height > 0 ? 'true' : undefined}>
    {topVisible && <div className="pf-skel-slot is-top nodrag nopan nowheel" onMouseDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
      <div className="pf-skel-toolbar">
        {topActions}
        {(topRightActions || onDownload || onPreview) && <span className="pf-skel-divider" />}
        {topRightActions}
        {onDownload && <button type="button" className="pf-skel-icon-btn" disabled={!canDownload} aria-label="下载" onClick={onDownload}><Download size={15} /></button>}
        {onPreview && <button type="button" className="pf-skel-icon-btn" disabled={!canPreview} aria-label="预览" onClick={onPreview}><Eye size={15} /></button>}
      </div>
    </div>}
    <header className="pf-skel-title">
      <span className="pf-skel-icon">{icon}</span>
      {renaming ? <input autoFocus className="pf-skel-rename nodrag nopan" aria-label="节点名称" value={draft} maxLength={200} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setDraft(event.target.value)} onBlur={finishRename} onKeyDown={(event) => { event.stopPropagation(); if (event.key === 'Enter') event.currentTarget.blur(); if (event.key === 'Escape') { cancelRename.current = true; setRenaming(false) } }} /> : <span className="pf-skel-label" tabIndex={writable ? 0 : undefined} title={`${title}${writable ? '（双击改名）' : ''}`} onDoubleClick={(event) => { event.stopPropagation(); rename() }} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); rename() } }}>{title}</span>}
      <span className="pf-skel-actions nodrag nopan">
        {badge ? <em className="pf-skel-badge">{badge}</em> : null}
        {onRemove && <button type="button" aria-label="删除节点" onClick={onRemove}><Trash2 size={13} /></button>}
        {onMenu && <button type="button" aria-label="节点操作" onClick={onMenu}><MoreHorizontal size={15} /></button>}
      </span>
    </header>
    <div className="pf-skel-card">
      <Handle type="target" position={Position.Left} className="pf-skel-handle" title="连接输入" isConnectable={writable} />
      <div className="pf-skel-body">{children}</div>
      {output && <Handle type="source" position={Position.Right} className="pf-skel-handle" title={`${mediaKind || '节点'}输出`} isConnectable={writable} />}
    </div>
    {(bottomVisible || keepBottomMounted) && bottom ? <div style={bottomVisible ? undefined : { display: 'none' }} className="pf-skel-slot is-bottom nodrag nopan nowheel" onMouseDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>{bottom}</div> : null}
    {selected && writable && onResize && <NodeResizeControl minWidth={160} minHeight={128} position="bottom-right" className="pf-skel-resize" onResizeStart={onResizeStart} onResizeEnd={(_, size) => onResize(size.width, size.height)}><span tabIndex={0} role="button" aria-label="调整节点大小，使用方向键" onKeyDown={(event) => { if (!event.key.startsWith('Arrow')) return; event.preventDefault(); event.stopPropagation(); onResizeStart?.(); onResize(Math.max(160, Number(width) + (event.key === 'ArrowRight' ? 10 : event.key === 'ArrowLeft' ? -10 : 0)), Math.max(128, (height || 240) + (event.key === 'ArrowDown' ? 10 : event.key === 'ArrowUp' ? -10 : 0))) }}><MoveDiagonal2 size={14} /></span></NodeResizeControl>}
  </div>
}
