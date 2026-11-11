import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useReactFlow } from '@xyflow/react'
import { Hand, MousePointer2, Plus, Search } from 'lucide-react'
import { STUDIO_ADDABLE_TYPES, STUDIO_NODE_LABELS, type StudioAddableType } from './flowAdapter'

type StudioChromeProps = {
  title: string
  statusText: string
  lockError: string
  writable: boolean
  loading: boolean
  tool: 'move' | 'hand'
  agentOpen: boolean
  onTool: (tool: 'move' | 'hand') => void
  onAdd: (type: StudioAddableType) => void
  onRetryLock: () => void
  onTakeOver: () => void
  onToggleAgent: () => void
}

/** 画布上的浮层：返回、状态、添加工具、缩放，配色沿用现有浅色体系。 */
export function StudioChrome({ title, statusText, lockError, writable, loading, tool, agentOpen, onTool, onAdd, onRetryLock, onTakeOver, onToggleAgent }: StudioChromeProps) {
  /*
   * addOpen 添加节点菜单
   * searchOpen 节点搜索
   * query 搜索关键字
   * searchError 未找到节点
   */
  const [addOpen, setAddOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [searchError, setSearchError] = useState('')
  const { setCenter, getNodes, getViewport } = useReactFlow()

  /** 按标题或正文定位节点。 */
  function searchNodes(event: FormEvent) {
    event.preventDefault()
    const keyword = query.trim()
    if (!keyword) return
    const hit = getNodes().find((node) => {
      const data = node.data as { label?: string; text?: string }
      return node.id.includes(keyword) || String(data.label || '').includes(keyword) || String(data.text || '').includes(keyword)
    })
    if (!hit) {
      setSearchError('没有匹配的节点')
      return
    }
    setSearchError('')
    void setCenter(hit.position.x + 120, hit.position.y + 80, { zoom: Math.max(getViewport().zoom, 1), duration: 200 })
    setSearchOpen(false)
  }

  return (
    <>
      <div className="pf-studio-menu">
        <Link to="/canvas" aria-label="返回画布列表">返回</Link>
        <div>
          <strong>{title || 'Printfilm Studio'}</strong>
          <span>{statusText}</span>
        </div>
      </div>
      <div className="pf-studio-switch" role="tablist" aria-label="工作区">
        <button type="button" aria-pressed="true">画布</button>
        <button type="button" disabled title="文档面板尚未接入">文档</button>
      </div>
      {lockError ? (
        <p className="pf-studio-lock" role="alert">
          {lockError}
          <button type="button" onClick={onRetryLock}>重试</button>
          <button type="button" onClick={onTakeOver}>接管</button>
        </p>
      ) : null}
      <div className="pf-studio-tools" role="toolbar" aria-label="画布工具">
        <div className="pf-studio-add">
          <button type="button" className="is-plus" aria-label="添加节点" aria-expanded={addOpen} disabled={!writable || loading} onClick={() => setAddOpen((open) => !open)}>
            <Plus size={16} />
          </button>
          {addOpen ? (
            <div className="pf-studio-add-menu" role="menu">
              {STUDIO_ADDABLE_TYPES.map((type) => (
                <button key={type} type="button" role="menuitem" onClick={() => { onAdd(type); setAddOpen(false) }}>{STUDIO_NODE_LABELS[type]}</button>
              ))}
            </div>
          ) : null}
        </div>
        <button type="button" aria-pressed={tool === 'move'} aria-label="移动工具" onClick={() => onTool('move')}><MousePointer2 size={16} /></button>
        <button type="button" aria-pressed={tool === 'hand'} aria-label="抓手工具" onClick={() => onTool('hand')}><Hand size={16} /></button>
        <button type="button" aria-pressed={searchOpen} aria-label="搜索节点" disabled={loading} onClick={() => setSearchOpen((open) => !open)}><Search size={16} /></button>
        {!agentOpen ? <button type="button" className="pf-studio-agent-launcher" aria-label="打开助手" onClick={onToggleAgent} /> : null}
      </div>
      {searchOpen ? (
        <form className="pf-studio-search" onSubmit={searchNodes}>
          <input value={query} placeholder="搜索节点标题或正文" onChange={(event) => setQuery(event.target.value)} />
          {searchError ? <span>{searchError}</span> : null}
        </form>
      ) : null}
    </>
  )
}
