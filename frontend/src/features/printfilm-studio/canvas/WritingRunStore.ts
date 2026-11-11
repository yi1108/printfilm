export type WritingRun = { controller: AbortController; sessionId?: string }
export type WritingRunState = { busy: boolean; result: string; error: string; startedAt: number }
const EMPTY: WritingRunState = Object.freeze({ busy: false, result: '', error: '', startedAt: 0 })

/** Owned by the workspace, not by a selected node's transient composer. */
export class WritingRunStore {
  private states = new Map<string, WritingRunState>()
  private active = new Map<string, WritingRun>()
  private listeners = new Map<string, Set<() => void>>()
  private stopSession: (sessionId: string) => Promise<unknown>

  constructor(stopSession: (sessionId: string) => Promise<unknown>) { this.stopSession = stopSession }

  snapshot(key: string): WritingRunState { return this.states.get(key) || EMPTY }

  subscribe(key: string, listener: () => void) {
    const listeners = this.listeners.get(key) || new Set<() => void>()
    listeners.add(listener)
    this.listeners.set(key, listeners)
    return () => { listeners.delete(listener); if (!listeners.size) this.listeners.delete(key) }
  }

  update(key: string, patch: Partial<WritingRunState>) {
    this.states.set(key, { ...this.snapshot(key), ...patch })
    this.listeners.get(key)?.forEach(listener => listener())
  }

  begin(key: string): WritingRun | null {
    if (this.active.has(key)) return null
    const run = { controller: new AbortController() }
    this.active.set(key, run)
    this.update(key, { busy: true, result: '', error: '', startedAt: Date.now() })
    return run
  }

  finish(key: string, run: WritingRun) {
    if (this.active.get(key) !== run) return false
    this.active.delete(key)
    this.update(key, { busy: false })
    return true
  }

  stop(key: string) {
    const run = this.active.get(key)
    if (!run || run.controller.signal.aborted) return
    run.controller.abort()
    if (run.sessionId) void this.stopSession(run.sessionId).catch(() => undefined)
  }

  /** Workspace navigation ends local runs; closing a composer never calls this. */
  dispose() { for (const key of this.active.keys()) this.stop(key) }
}
