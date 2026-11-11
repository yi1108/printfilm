import { useEffect, useId, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Box, Brush, ChevronRight, Clapperboard, Expand, Film, FolderOpen, Frame, History, Image as ImageIcon, Layers, Mic, Move, Plus, Scissors, Sparkles, Upload, Workflow, FileText, X } from 'lucide-react'
import { NODE_CATALOG, type NodeCatalogItem } from './nodeCatalog'
import { focusMenuItem, useMenuKeyboard } from './useMenuKeyboard'
import './menuKeyboard.css'

type Props = {
  onAdd: (item: NodeCatalogItem) => void
  onClose: () => void
}

/** 按节点类型选择菜单图标，保持与 Paba 添加节点列表一致。 */
function itemIcon(item: NodeCatalogItem) {
  const key = item.type || item.action || item.id
  if (key === 'image' || key === 'upscale') return <ImageIcon size={15} />
  if (key === 'video' || key === 'storyboard' || key === 'fill_frames') return <Film size={15} />
  if (key === 'audio') return <Mic size={15} />
  if (key === 'compose') return <Scissors size={15} />
  if (key === 'motion' || key === 'control_video') return <Move size={15} />
  if (key === 'inpaint') return <Brush size={15} />
  if (key === 'outpaint') return <Expand size={15} />
  if (key === 'director3d') return <Box size={15} />
  if (key === 'director_flow' || key === 'task_flow') return <Workflow size={15} />
  if (key === 'recipe') return <Sparkles size={15} />
  if (key === 'interpolate') return <Frame size={15} />
  if (key === 'script' || key === 'text' || key === 'script_main') return <FileText size={15} />
  if (key === 'assets' || key === 'library' || key === 'library_assets') return <FolderOpen size={15} />
  if (key === 'history' || key === 'library_history') return <History size={15} />
  if (key === 'upload' || key === 'library_upload') return <Upload size={15} />
  if (key === 'task') return <Clapperboard size={15} />
  return <Layers size={15} />
}

/** Paba 风格的添加节点菜单：白色圆角浮层、主列表、子菜单、上传与生成历史入口。 */
export function AddNodeMenu({ onAdd, onClose, floating }: Props & { floating?: boolean }) {
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const keyboard = useMenuKeyboard(onClose)
  const menuId = useId()
  useEffect(() => {
    if (openGroup) focusMenuItem(keyboard.ref.current?.querySelector<HTMLButtonElement>('.pf-add-children button') || undefined)
  }, [openGroup, keyboard.ref])
  const closeGroup = () => {
    const button = keyboard.ref.current?.querySelector<HTMLButtonElement>(`[data-menu-group="${openGroup}"]`)
    setOpenGroup(null)
    focusMenuItem(button || undefined)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const target = event.target as HTMLElement
    const group = target.closest<HTMLButtonElement>('[data-menu-group]')
    if (event.key === 'ArrowRight' && group) {
      event.preventDefault(); event.stopPropagation()
      setOpenGroup(group.dataset.menuGroup || null)
      focusMenuItem(group.parentElement?.querySelector<HTMLButtonElement>('.pf-add-children button') || undefined)
      return
    }
    if ((event.key === 'ArrowLeft' || event.key === 'Escape') && openGroup) {
      event.preventDefault(); event.stopPropagation(); closeGroup(); return
    }
    keyboard.onKeyDown(event)
  }
  return <div {...keyboard} onKeyDown={onKeyDown} onMouseDown={(event) => event.stopPropagation()} role="menu" aria-label="添加节点菜单" className={`pf-add-menu${floating ? ' is-floating' : ''}`}>
    <header><b>添加节点</b><button type="button" aria-label="关闭" onClick={onClose}><X size={15} /></button></header>
    <div className="pf-add-list">
      {NODE_CATALOG.map((item) => {
        if (item.children?.length) {
          return <div className="pf-add-group" key={item.id}>
            <button type="button" role="menuitem" tabIndex={-1} data-menu-group={item.id} aria-haspopup="menu" aria-expanded={openGroup === item.id} aria-controls={`${menuId}-${item.id}`} className={openGroup === item.id ? 'is-open' : ''} onClick={() => setOpenGroup((value) => value === item.id ? null : item.id)}>
              <span className="pf-add-icon">{itemIcon(item)}</span>
              <span>{item.label}</span>
              <ChevronRight size={14} />
            </button>
            {openGroup === item.id && <div id={`${menuId}-${item.id}`} className="pf-add-children" role="menu" aria-label={item.label}>{item.children.map((child) => <button type="button" role="menuitem" tabIndex={-1} key={child.id} onClick={() => onAdd(child)}><span className="pf-add-icon">{itemIcon(child)}</span>{child.label}<Plus size={13} /></button>)}</div>}
          </div>
        }
        return <button type="button" role="menuitem" tabIndex={-1} className="pf-add-item" key={item.id} onClick={() => onAdd(item)}>
          <span className="pf-add-icon">{itemIcon(item)}</span>
          <span className="pf-add-copy"><b>{item.label}</b>{item.hint ? <small>{item.hint}</small> : null}</span>
          <Plus size={13} />
        </button>
      })}
    </div>
    <footer>
      <button type="button" role="menuitem" tabIndex={-1} onClick={() => onAdd({ id: 'upload', label: '上传', action: 'upload' })}><Upload size={14} /> 上传</button>
      <button type="button" role="menuitem" tabIndex={-1} onClick={() => onAdd({ id: 'history', label: '从生成历史选择', action: 'history' })}><History size={14} /> 从生成历史选择</button>
    </footer>
  </div>
}
