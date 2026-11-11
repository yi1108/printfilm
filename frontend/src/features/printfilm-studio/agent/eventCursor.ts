/** The run identity and monotonic cursor make replay safe for UI side effects. */
export function createEventCursor(runId?: string) {
  let id = runId || ''
  let sequence = 0
  let done = false
  return {
    get runId() { return id },
    get sequence() { return sequence },
    get done() { return done },
    accept(event: Record<string, unknown>) {
      if (event.type === 'heartbeat') return false
      const nextId = String(event.run_id || '')
      const nextSequence = Number(event.sequence)
      if (nextId && id && nextId !== id) return false
      if (nextId && Number.isSafeInteger(nextSequence) && nextSequence > 0) {
        if (nextSequence <= sequence) return false
        if (nextSequence !== sequence + 1) throw new Error('Agent 事件不连续，正在恢复缺失内容')
        id = nextId; sequence = nextSequence
      }
      if (event.type === 'done') done = true
      return true
    },
  }
}
