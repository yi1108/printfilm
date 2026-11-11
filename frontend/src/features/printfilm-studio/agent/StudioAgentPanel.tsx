import { useEffect, useRef, useState } from 'react'
import { printfilmStudioApi } from '../api'
import type { AgentSession } from '../types'

type ChatLine = { id: string; role: 'user' | 'assistant' | 'error' | 'tool'; text: string; name?: string; open?: boolean }
const SUGGESTIONS = [
  ['整理分镜', '根据项目内容整理一条可拍摄的分镜，并在画布上创建对应文本节点。'],
  ['补三个画面', '在画布上添加三个画面节点，分别写开场、发展和结尾。'],
  ['连成故事', '把现有节点按故事顺序连起来，并补上缺失的过渡。'],
]

/** 把会话消息收成可展示的文本。 */
function messageText(content: unknown): string {
  if (typeof content === 'string') return content
  if (content && typeof content === 'object' && 'text' in content) return String((content as { text?: unknown }).text || '')
  return content == null ? '' : JSON.stringify(content)
}

type StudioAgentPanelProps = {
  projectId: number
  docked: boolean
  onCanvasUpdated: () => void
  onDock: () => void
  onClose: () => void
}

/** 项目内的创作助手：可切换会话，工具调用可展开，并流式显示回复。 */
export function StudioAgentPanel({ projectId, docked, onCanvasUpdated, onDock, onClose }: StudioAgentPanelProps) {
  /*
   * sessions 当前项目的会话
   * sessionId 正在查看的会话
   * lines 对话记录
   * prompt 输入草稿
   * streaming 是否正在接收回复
   * error 会话加载或发送失败
   */
  const [sessions, setSessions] = useState<AgentSession[]>([])
  const [sessionId, setSessionId] = useState('')
  const [lines, setLines] = useState<ChatLine[]>([])
  const [prompt, setPrompt] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  /** 读取指定会话的历史消息。 */
  async function openSession(id: string) {
    const full = await printfilmStudioApi.getSession(id)
    setSessionId(full.id)
    setLines((full.messages || []).map((message) => ({
      id: message.id,
      role: message.role === 'assistant' ? 'assistant' : 'user',
      text: messageText(message.content),
    })))
  }

  useEffect(() => {
    let active = true
    setSessions([])
    setSessionId('')
    setLines([])
    setError('')
    void (async () => {
      try {
        const listed = await printfilmStudioApi.listSessions(projectId)
        const existing = listed.sessions[0] ?? await printfilmStudioApi.createSession(projectId)
        const full = await printfilmStudioApi.getSession(existing.id)
        if (!active) return
        setSessions(listed.sessions.length ? listed.sessions : [full])
        setSessionId(full.id)
        setLines((full.messages || []).map((message) => ({
          id: message.id,
          role: message.role === 'assistant' ? 'assistant' : 'user',
          text: messageText(message.content),
        })))
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : '助手会话加载失败')
      }
    })()
    return () => { active = false; abortRef.current?.abort() }
  }, [projectId])

  /** 另开一条空白会话。 */
  async function startNew() {
    const created = await printfilmStudioApi.createSession(projectId)
    setSessions((current) => [created, ...current])
    setSessionId(created.id)
    setLines([])
    setError('')
  }

  /** 删除当前会话；没有剩余会话时再新建一条。 */
  async function removeCurrent() {
    if (!sessionId || streaming) return
    const removing = sessionId
    await printfilmStudioApi.deleteSession(removing)
    const rest = sessions.filter((session) => session.id !== removing)
    if (!rest.length) {
      const created = await printfilmStudioApi.createSession(projectId)
      setSessions([created])
      setSessionId(created.id)
      setLines([])
      setError('')
      return
    }
    setSessions(rest)
    await openSession(rest[0].id)
  }

  /** 发送当前输入，并把增量回复追加到最后一条助手消息。 */
  async function send(draft = prompt) {
    const text = draft.trim()
    if (!text || !sessionId || streaming) return
    const controller = new AbortController()
    abortRef.current = controller
    const assistantId = `local-${crypto.randomUUID()}`
    setPrompt('')
    setError('')
    setStreaming(true)
    setLines((current) => [...current, { id: `user-${assistantId}`, role: 'user', text }, { id: assistantId, role: 'assistant', text: '' }])
    try {
      await printfilmStudioApi.stream(sessionId, text, (event) => {
        if (event.type === 'message_delta') {
          const delta = String(event.content || '')
          setLines((current) => current.map((line) => line.id === assistantId ? { ...line, text: line.text + delta } : line))
        } else if (event.type === 'tool') {
          setLines((current) => [...current, { id: `tool-${crypto.randomUUID()}`, role: 'tool', name: String(event.name || '工具'), text: String(event.summary || (event.ok ? '已完成' : '未完成')), open: false }])
        } else if (event.type === 'canvas_updated') {
          onCanvasUpdated()
        } else if (event.type === 'error') {
          const message = String(event.message || '助手回复失败')
          setLines((current) => current.map((line) => line.id === assistantId ? { ...line, role: 'error', text: message } : line))
        }
      }, controller.signal)
    } catch (err) {
      if (controller.signal.aborted) return
      setError(err instanceof Error ? err.message : '助手回复失败')
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setStreaming(false)
    }
  }

  /** 同时中断本地读取和服务端生成。 */
  function stop() {
    abortRef.current?.abort()
    if (sessionId) void printfilmStudioApi.stopSession(sessionId).catch(() => undefined)
    setStreaming(false)
  }

  /** 复制一条消息。 */
  async function copyLine(text: string) {
    try { await navigator.clipboard.writeText(text) } catch { setError('复制失败') }
  }

  return (
    <aside className={`pf-studio-agent${docked ? ' is-docked' : ''}`} aria-label="创作助手">
      <header>
        <select aria-label="切换会话" value={sessionId} disabled={!sessions.length || streaming} onChange={(event) => { void openSession(event.target.value).catch((err) => setError(err instanceof Error ? err.message : '会话打开失败')) }}>
          {sessions.map((session) => <option key={session.id} value={session.id}>{session.title || '新对话'}</option>)}
        </select>
        <button type="button" disabled={streaming} onClick={() => { void startNew().catch((err) => setError(err instanceof Error ? err.message : '无法新建会话')) }}>新建</button>
        <button type="button" disabled={!sessionId || streaming} onClick={() => { void removeCurrent().catch((err) => setError(err instanceof Error ? err.message : '无法删除会话')) }}>删除</button>
        <button type="button" aria-label={docked ? '改为悬浮' : '停靠到右侧'} onClick={onDock}>{docked ? '悬浮' : '停靠'}</button>
        <button type="button" aria-label="关闭助手" onClick={onClose}>关闭</button>
      </header>
      <div className="pf-studio-agent-log" aria-live="polite">
        {lines.length === 0 ? (
          <section className="pf-studio-welcome">
            <p>从一个想法开始</p>
            <strong>聊聊故事、画面或镜头，落到画布上。</strong>
            {SUGGESTIONS.map(([label, value]) => (
              <button key={label} type="button" disabled={!sessionId || streaming} onClick={() => setPrompt(value)}>
                <strong>{label}</strong>
                <span>{value}</span>
              </button>
            ))}
          </section>
        ) : null}
        {lines.map((line) => line.role === 'tool' ? (
          <button key={line.id} type="button" className={`pf-studio-tool${line.open ? ' is-open' : ''}`} onClick={() => setLines((current) => current.map((item) => item.id === line.id ? { ...item, open: !item.open } : item))}>
            <span>{line.name}</span><em>{line.text}</em>
            {line.open ? <small>{line.text}</small> : null}
          </button>
        ) : (
          <article key={line.id} className={`pf-studio-line is-${line.role}`}>
            <p>{line.text || (streaming && line.id === lines[lines.length - 1]?.id ? '正在思考…' : '')}</p>
            {line.text ? <button type="button" onClick={() => { void copyLine(line.text) }}>复制</button> : null}
          </article>
        ))}
      </div>
      {error ? <p className="pf-studio-agent-error" role="alert">{error}</p> : null}
      <form className="pf-studio-composer" onSubmit={(event) => { event.preventDefault(); void send() }}>
        <textarea value={prompt} placeholder="输入消息，Enter 发送" onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} />
        <div>
          {streaming ? <button type="button" onClick={stop}>停止</button> : null}
          <button type="submit" className="is-send" disabled={!sessionId || streaming || !prompt.trim()} aria-label="发送">发送</button>
        </div>
      </form>
    </aside>
  )
}
