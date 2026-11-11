import { useState } from 'react'
import { FileText, Search, X } from 'lucide-react'

export function CanvasSearch({ nodes, onSelect, onClose }: { nodes: { id: string; data: Record<string, unknown> }[]; onSelect: (id: string) => void; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const matches = nodes.filter((node) => `${node.data.label || ''} ${node.data.name || ''} ${node.data.text || ''} ${node.data.prompt || ''}`.toLowerCase().includes(query.trim().toLowerCase()))
  return <section className="pf-canvas-search" role="dialog" aria-label="搜索画布节点" onKeyDown={(event) => { if (event.key === 'Escape') onClose() }}><header><Search size={16} /><input autoFocus placeholder="搜索名称、文本或提示词" aria-label="搜索画布" value={query} onChange={(event) => setQuery(event.target.value)} /><button aria-label="关闭搜索" onClick={onClose}><X size={16} /></button></header><div>{matches.map((node) => <button key={node.id} onClick={() => { onSelect(node.id); onClose() }}><FileText size={15} /><span>{String(node.data.label || node.data.name || '未命名节点')}<small>{String(node.data.text || node.data.prompt || '').slice(0, 65)}</small></span></button>)}{matches.length === 0 && <p>未找到匹配节点</p>}</div></section>
}
