import type { PromptReference } from './promptMentions'
import { lazy, Suspense, type ReactNode } from 'react'
import { useMenuKeyboard } from './useMenuKeyboard'
import { Copy, Group, Pencil, Play, Scissors, Share2, Sparkles, Trash2, Workflow } from 'lucide-react'
import './menuKeyboard.css'

const TextNodeEditor = lazy(() => import('./TextNodeEditor').then((module) => ({ default: module.TextNodeEditor })))

export type InspectorDraft = {
  label: string
  text: string
  prompt: string
  clipStart: string
  clipEnd: string
}

export type MenuAction = {
  id: string
  label: string
  shortcut?: string
  disabled?: boolean
  danger?: boolean
  icon?: ReactNode
}

const MENU_ICONS: Record<string, ReactNode> = {
  run_here: <Play size={14} />,
  recipe: <Workflow size={14} />,
  share: <Share2 size={14} />,
  rename: <Pencil size={14} />,
  copy: <Copy size={14} />,
  cut: <Scissors size={14} />,
  duplicate: <Copy size={14} />,
  group: <Group size={14} />,
  ask_agent: <Sparkles size={14} />,
  remove: <Trash2 size={14} />,
}

/** 节点右键菜单（对照 Paba：运行 / 配方 / 复制剪切 / Agent / 删除）。 */
export function StudioContextMenu({ menu, actions, onSelect, onClose }: {
  menu: { left: number; top: number }
  actions: MenuAction[]
  onSelect: (id: string) => void
  onClose: () => void
}) {
  const keyboard = useMenuKeyboard(onClose)
  return <div {...keyboard} className="pf-context-menu" style={{ left: Math.max(8, Math.min(menu.left, window.innerWidth - 250)), top: Math.max(8, Math.min(menu.top, window.innerHeight - Math.min(actions.length * 36 + 16, window.innerHeight - 16))), maxHeight: 'calc(100vh - 16px)', overflowY: 'auto' }} role="menu" aria-label="画布操作菜单" onMouseDown={(event) => event.stopPropagation()}>
    {actions.map((action) => (
      <button
        type="button"
        role="menuitem"
        tabIndex={-1}
        key={action.id}
        disabled={action.disabled}
        className={action.danger ? 'is-danger' : undefined}
        onClick={() => { if (!action.disabled) onSelect(action.id) }}
      >
        <span className="pf-context-icon">{action.icon || MENU_ICONS[action.id] || null}</span>
        <span className="pf-context-label">{action.label}</span>
        {action.shortcut ? <kbd>{action.shortcut}</kbd> : null}
      </button>
    ))}
  </div>
}

/** 节点检查器：改名称、正文、提示词和音视频裁剪点。 */
export function StudioInspector({ draft, kind, writable, onChange, onSave, onClose, references }: {
  references?: PromptReference[]
  draft: InspectorDraft
  kind: 'image' | 'video' | 'audio' | 'text' | 'group'
  writable: boolean
  onChange: (draft: InspectorDraft) => void
  onSave: () => void
  onClose: () => void
}) {
  if (kind === 'text') return <Suspense fallback={<div role="status" style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'grid', placeItems: 'center', background: '#0008', color: '#fff' }}>正在打开文本…</div>}><TextNodeEditor references={references} draft={draft} writable={writable} onChange={onChange} onSave={onSave} onClose={onClose} /></Suspense>
  const field = (key: keyof InspectorDraft, label: string, multiline = false) => (
    <label>{label}{multiline
      ? <textarea readOnly={!writable} value={draft[key]} onChange={(event) => onChange({ ...draft, [key]: event.target.value })} />
      : <input readOnly={!writable} value={draft[key]} onChange={(event) => onChange({ ...draft, [key]: event.target.value })} />}</label>
  )
  return <aside className="pf-inspector" role="dialog" aria-label={kind === 'group' ? '编辑分类框' : '编辑媒体节点'}>
    <header><b>{kind === 'group' ? '编辑分类框' : '编辑节点'}</b><button type="button" onClick={onClose}>关闭</button></header>
    {field('label', '名称')}
    {kind !== 'group' && field('text', '说明', true)}
    {kind !== 'group' && field('prompt', '生成提示词', true)}
    {(kind === 'video' || kind === 'audio') && <>{field('clipStart', '开始秒')}{field('clipEnd', '结束秒')}</>}
    <footer><button type="button" disabled={!writable} onClick={onSave}>保存到节点</button></footer>
  </aside>
}
