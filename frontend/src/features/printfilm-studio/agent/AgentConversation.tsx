import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, Check, ChevronRight, Copy, GitBranch, Pencil, Sparkles, Trash2, Wrench } from 'lucide-react'
import { MessageContent } from './MessageContent'
import { AgentReferences } from './AgentReferences'
import { AgentProgress } from './AgentProgress'
import { ProposalCard, type ProposalControls } from './ProposalCard'
import type { AgentProposal } from './proposals'
import { conversationRows, type AgentEvent } from './conversation'

export type MessageAction = 'branch' | 'edit_branch' | 'truncate'
export function AgentConversation({ events, answer, running, sessionId, labels, onPrompt, onAction, guide, proposals }: {
  events: AgentEvent[]; answer: string; running: boolean; sessionId: string | null; labels: Record<string, string>
  onPrompt: (value: string) => void; onAction: (event: AgentEvent, action: MessageAction) => Promise<void>
  guide?: ReactNode
  proposals?: ProposalControls
}) {
  const log = useRef<HTMLDivElement | null>(null)
  const atBottom = useRef(true)
  const [unread, setUnread] = useState(false)
  const [copied, setCopied] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollBottom = () => { if (log.current) log.current.scrollTop = log.current.scrollHeight; atBottom.current = true; setUnread(false) }
  useEffect(() => { atBottom.current = true; setUnread(false) }, [sessionId])
  useEffect(() => { if (atBottom.current) scrollBottom(); else setUnread(true) }, [events, answer])
  const rows = conversationRows(events, running)
  const act = async (event: AgentEvent, action: MessageAction) => {
    if (action === 'truncate' && !window.confirm('删除此消息及后续对话？已生成的素材和画布修改会保留。')) return
    setBusy(true); setError('')
    try { await onAction(event, action) } catch (reason) { setError(reason instanceof Error ? reason.message : '对话操作失败') } finally { setBusy(false) }
  }
  return <div className="pf-agent-thread">
    {guide}
    <div className="pf-agent-scroll pf-agent-conversation" ref={log} role="log" aria-live="polite" onScroll={() => { const element = log.current; if (element) { atBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48; if (atBottom.current) setUnread(false) } }}>
      {events.length === 0 && <div className="pf-agent-welcome"><Sparkles size={28} /><h3>今天想创作什么？</h3><p>从一个想法开始，也可以 @ 引用画布上的内容。</p>{[
        ['梳理当前画布', '读取节点与连线，整理故事结构'], ['规划分镜', '根据当前故事规划三个镜头节点'], ['处理视频', '查看画布中可用于剪辑的视频素材'],
      ].map(([title, description]) => <button key={title} onClick={() => onPrompt(description)}><span><b>{title}</b><small>{description}</small></span><ChevronRight size={15} /></button>)}</div>}
      {rows.map((event, index) => event.type === 'proposal' && proposals ? <ProposalCard key={(event.data as AgentProposal).id} proposal={event.data as AgentProposal} controls={proposals} /> : event.type.startsWith('tool_') ? <details className={`pf-agent-tool ${event.state === 'failed' ? 'is-error' : ''}`} key={index}>
        <summary><ChevronRight className="pf-disclosure" size={14} /><Wrench size={14} /><span title={event.text}>{labels[event.text] || event.text}</span><em>{event.state === 'running' ? '执行中' : event.state === 'failed' ? '失败' : event.state === 'interrupted' ? '已中断' : '已完成'}</em></summary>
        {event.input !== undefined && <><small>输入</small><pre>{JSON.stringify(event.input, null, 2)}</pre></>}
        {event.summary && <p>{event.summary}</p>}{event.data !== undefined && <><small>结果</small><pre>{JSON.stringify(event.data, null, 2)}</pre></>}
      </details> : event.type === 'thinking' ? <details className="pf-agent-tool" key={index}><summary><ChevronRight className="pf-disclosure" size={14} /><Sparkles size={14} />处理进度</summary><p>{event.text}</p></details> : <div className={`pf-agent-bubble is-${event.type}`} key={index}>
        {event.references && <AgentReferences references={event.references} />}
        {event.text && <MessageContent text={event.text} />}
        {['user', 'assistant'].includes(event.type) && <div className="pf-message-actions">
          <button aria-label="复制消息" title="复制消息" onClick={() => void navigator.clipboard.writeText(event.text).then(() => setCopied(index)).catch(() => setError('无法复制，请检查剪贴板权限'))}>{copied === index ? <Check size={14} /> : <Copy size={14} />}</button>
          {event.id && <><button title="从这里创建新会话" aria-label="从此消息分支" disabled={running || busy} onClick={() => void act(event, 'branch')}><GitBranch size={14} /></button>
            {event.type === 'user' && <button title="在新分支编辑这条消息，保留原会话" aria-label="编辑并分支" disabled={running || busy} onClick={() => void act(event, 'edit_branch')}><Pencil size={14} /></button>}
            <button title="删除此处及后续对话" aria-label="删除此处及后续对话" disabled={running || busy} onClick={() => void act(event, 'truncate')}><Trash2 size={14} /></button></>}
        </div>}
      </div>)}
      {answer && <div className="pf-agent-bubble is-assistant is-streaming"><MessageContent text={answer} /></div>}
      {error && <p role="alert" className="pf-agent-error">{error}</p>}
    </div>
    {running && <AgentProgress events={events} labels={labels} />}
    {unread && <button className="pf-agent-jump" onClick={scrollBottom}><ArrowDown size={14} />回到最新消息</button>}
  </div>
}
