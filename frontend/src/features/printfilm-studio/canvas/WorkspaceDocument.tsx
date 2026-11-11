import { useState } from 'react'
import { FileText, Image, Film, Mic, Pencil, Scan, Check } from 'lucide-react'
import { MessageContent } from '../agent/MessageContent'
import { nodeMediaKind, type StudioNodeRecord } from './nodeOperations'
import { writingContext } from './writingContext'
import { InlineVideoPlayer } from './InlineVideoPlayer'

export function WorkspaceDocument({ nodes, writable, onText, onLocate }: { nodes: StudioNodeRecord[]; writable: boolean; onText: (id: string, text: string) => void; onLocate: (id: string) => void }) {
  const [editing, setEditing] = useState<string | null>(null)
  const visible = nodes.filter((node) => node.type !== 'group')
  return <section className="pf-workspace-document" aria-label="画布文档"><div className="pf-document-content"><header><FileText size={24} /><div><h1>画布文档</h1><p>以文档方式阅读画布内容 · {visible.length} 个节点</p></div></header>
    {visible.length === 0 && <p className="pf-document-empty">画布还没有内容，添加节点后会同步显示在这里。</p>}
    {visible.map((node) => { const kind = nodeMediaKind(node), media = String(node.data.mediaUrl || node.data.url || node.data.cover || ''), text = String(node.data.text || node.data.prompt || ''), Icon = kind === 'image' ? Image : kind === 'video' ? Film : kind === 'audio' ? Mic : FileText; return <article key={node.id} className={`pf-document-node is-${kind}`}><header><Icon size={16} /><b>{String(node.data.label || node.data.name || '节点')}</b>{kind === 'text' && writable && <button aria-label={editing === node.id ? '完成文本编辑' : '编辑文本'} onClick={() => setEditing(editing === node.id ? null : node.id)}>{editing === node.id ? <Check size={15} /> : <Pencil size={15} />}</button>}<button aria-label="在画布中定位" title="在画布中定位" onClick={() => onLocate(node.id)}><Scan size={15} /></button></header>
      {kind === 'text' ? editing === node.id ? <textarea autoFocus aria-label="文档节点正文" value={text} onChange={(event) => onText(node.id, event.target.value)} /> : <MessageContent references={writingContext(node,nodes,[]).references} text={text || '此节点暂无文本'} /> : media ? kind === 'video' ? <InlineVideoPlayer key={media} url={media} title={String(node.data.label || '视频')} writable={false} onSize={() => undefined} onCapture={() => undefined} /> : kind === 'audio' ? <audio src={media} controls /> : <img src={media} alt={String(node.data.label || '图片')} loading="lazy" /> : <div className="pf-document-pending"><Icon size={28} />{node.data.status === 'running' || node.data.status === 'queued' ? '正在生成' : '暂无媒体'}</div>}
      {kind !== 'text' && text && <p>{text}</p>}
    </article>})}
  </div></section>
}
