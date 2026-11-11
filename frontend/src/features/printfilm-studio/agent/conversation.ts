import type { AgentSession } from '../types'
import type { AgentReference } from './references'

export type AgentEvent = { type: string; text: string; references?: AgentReference[]; data?: unknown; ok?: boolean; id?: string; sequence?: number; callId?: string; runId?: string; summary?: string }
export type ConversationRow = AgentEvent & { input?: unknown; state?: 'running' | 'completed' | 'failed' | 'interrupted'; streaming?: boolean }

export function eventFromWire(event: Record<string, unknown>): AgentEvent {
  return { type: String(event.type), text: String(event.tool || event.content || event.summary || event.message || event.task_id || ''), data: event.data, ok: typeof event.ok === 'boolean' ? event.ok : undefined, callId: event.call_id == null ? undefined : String(event.call_id), runId: typeof event.run_id === 'string' ? event.run_id : undefined, summary: typeof event.summary === 'string' ? event.summary : undefined }
}

export function sessionEvents(session: AgentSession): AgentEvent[] {
  return (session.messages || []).flatMap((message) => {
    const events = message.metadata?.events || []
    return [...events.map(eventFromWire), { id: message.id, sequence: message.sequence, type: message.role, references: message.metadata?.references, text: typeof message.content === 'string' ? message.content : JSON.stringify(message.content) }]
  })
}

/** A tool invocation has one row, even after reconnect/replay or when repeated. */
export function conversationRows(events: AgentEvent[], running: boolean): ConversationRow[] {
  const rows: ConversationRow[] = []
  let pending: number[] = []
  for (const event of events) {
    if (event.type === 'model_progress') continue
    if (event.type === 'user') pending = []
    if (event.type === 'tool_start') {
      pending.push(rows.length)
      rows.push({ ...event, input: event.data, data: undefined, state: 'running' })
    } else if (event.type === 'tool_result') {
      const match = pending.findLast((index) => rows[index].text === event.text && (event.runId === undefined || rows[index].runId === event.runId) && (event.callId === undefined || rows[index].callId === event.callId))
      if (match !== undefined) {
        rows[match] = { ...rows[match], ...event, input: rows[match].input, state: event.ok === false ? 'failed' : 'completed' }
        pending = pending.filter((index) => index !== match)
      } else rows.push({ ...event, state: event.ok === false ? 'failed' : 'completed' })
    } else rows.push({ ...event })
  }
  return rows.map((row) => row.state === 'running' && !running ? { ...row, state: 'interrupted' } : row)
}

/** Keep each turn's actionable cards after its prose, including live output.
 * Reorder presentation only: event history and proposal identities stay intact. */
export function conversationDisplayRows(events: AgentEvent[], running: boolean, answer = ''): ConversationRow[] {
  const displayed: ConversationRow[] = []
  let cards: ConversationRow[] = []
  for (const row of conversationRows(events, running)) {
    if (row.type === 'user') {
      displayed.push(...cards)
      cards = []
    }
    if (row.type === 'proposal') cards.push(row)
    else displayed.push(row)
  }
  if (answer) displayed.push({type: 'assistant', text: answer, streaming: true})
  return [...displayed, ...cards]
}
