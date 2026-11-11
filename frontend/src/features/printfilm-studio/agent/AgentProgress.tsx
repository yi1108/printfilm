import { useEffect, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { conversationRows, type AgentEvent } from './conversation'

export function AgentProgress({ events, labels }: { events: AgentEvent[]; labels: Record<string, string> }) {
  const [started] = useState(() => Date.now())
  const [seconds, setSeconds] = useState(0)
  useEffect(() => { const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000); return () => window.clearInterval(timer) }, [started])
  const current = events.slice(events.findLastIndex((event) => event.type === 'user') + 1)
  const pending = conversationRows(current, true).findLast((event) => event.state === 'running')
  const phase = current.findLast(event => event.type === 'model_progress')?.text
  return <div className="pf-agent-progress">
    <LoaderCircle size={16} className="pf-agent-progress-spinner" />
    <div role="status"><b>生成中{pending ? ` · ${labels[pending.text] || '正在处理画布'}` : '…'}</b><small>{pending ? '正在读取或处理画布资料。' : phase || (seconds >= 30 ? '正在等待模型完整回复，可随时停止。' : '正在组织内容，请稍候。')}</small></div>
    <time aria-label={`已等待 ${seconds} 秒`}>{seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`}</time>
  </div>
}
