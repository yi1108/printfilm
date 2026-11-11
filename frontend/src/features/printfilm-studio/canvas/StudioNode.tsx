import { createContext, useContext, useState } from 'react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { STUDIO_NODE_LABELS } from './flowAdapter'

export type StudioNodeData = { label?: string; text?: string }
export const StudioNodeEditContext = createContext<(id: string, text: string) => void>(() => {})

/** 节点卡片：默认预览正文，点编辑后再修改。 */
export function StudioNode({ id, data, type }: NodeProps<Node<StudioNodeData>>) {
  const updateText = useContext(StudioNodeEditContext)
  const [editing, setEditing] = useState(false)
  const label = String(data?.label || STUDIO_NODE_LABELS[type || ''] || '节点')
  const text = String(data?.text || '')
  return (
    <article className={`pf-studio-node is-${type || 'text'}${editing ? ' is-editing' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <header><strong>{label}</strong></header>
      {editing ? (
        <textarea className="nodrag nopan nowheel" defaultValue={text} placeholder="写下这一镜的内容" autoFocus onBlur={(event) => { if (event.target.value !== text) updateText(id, event.target.value); setEditing(false) }} />
      ) : (
        <div className="pf-studio-node-preview">{text || '还没有内容'}</div>
      )}
      <footer>
        <span>{STUDIO_NODE_LABELS[type || ''] || '节点'}</span>
        <button type="button" className="nodrag nopan" onClick={() => setEditing(true)}>编辑</button>
      </footer>
      <Handle type="source" position={Position.Right} />
    </article>
  )
}
