import { createJsonRequester, API_BASE } from '../../api/client'
import { scopedRequestInit } from '../teams/workspaceScope'
import { readNodeDefaults } from './workspacePreferences'
import { createEventCursor } from './agent/eventCursor'
import { parseNdjson } from './canvas/canvasCodec'
import type { AgentOptions, AgentSession, CanvasResponse, ProjectAsset, MediaOperation, FrameAnalysisReport } from './types'
import type { Recipe } from './canvas/recipeGraph'
import { reportStudioUnauthorized, STUDIO_SESSION_EXPIRED } from './workspaceAccess'

const jsonRequest = createJsonRequester()
function notifyExpired(cause: unknown, token: string | null) {
  reportStudioUnauthorized(cause, token, () => localStorage.getItem('token'), () => window.dispatchEvent(new Event(STUDIO_SESSION_EXPIRED)))
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('token')
  try { return await jsonRequest<T>(path, init) }
  catch (cause) { notifyExpired(cause, token); throw cause }
}

/** 从失败响应里取出可展示的中文原因。 */
function errorDetail(payload: unknown): string {
  if (!payload || typeof payload !== 'object') return 'Agent 请求失败'
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const message = String((detail as { message?: unknown }).message || '')
    if (message.trim()) return message
  }
  return 'Agent 请求失败'
}

export const printfilmStudioApi = {
  quoteWorkflow: (projectId: number, targetIds: string[], settings: import('./agent/batchGeneration').BatchSettings, version: number, headers?: HeadersInit, textOnly = false) => request<import('./agent/batchGeneration').BatchQuote>(`/api/printfilm-studio/projects/${projectId}/workflow/quote`, { method: 'POST', headers, body: JSON.stringify({ target_ids: targetIds, settings, expected_version: version, text_only: textOnly }) }),
  startWorkflow: (projectId: number, runId: string, headers?: HeadersInit) => request<{ id: string; status: string }>(`/api/printfilm-studio/projects/${projectId}/workflow/${runId}/start`, { method: 'POST', headers }),
  workflowStatus: (projectId: number) => request<CanvasResponse & { run: { id: string; status: string; completed: number; count: number; error?: string } | null }>(`/api/printfilm-studio/projects/${projectId}/workflow`),
  repairStory: (projectId: number, scriptNodeId: string, expectedVersion: number, headers?: HeadersInit) => request<CanvasResponse>(`/api/printfilm-studio/projects/${projectId}/canvas/story/repair`, { method: 'POST', headers, body: JSON.stringify({ script_node_id: scriptNodeId, expected_version: expectedVersion }) }),
  readMedia: async (projectId: number, assetId: number, signal?: AbortSignal, url?: string): Promise<Blob> => {
    const token = localStorage.getItem('token'), path = `/api/printfilm-studio/projects/${projectId}/media/${assetId ? `assets/${assetId}` : 'source'}`
    const response = await fetch(`${API_BASE}${path}`, scopedRequestInit(path, { signal, method: assetId ? 'GET' : 'POST', body: assetId ? undefined : JSON.stringify({ url }), headers: { Authorization: `Bearer ${token || ''}`, ...(!assetId ? { 'Content-Type': 'application/json' } : {}) } }))
    if (!response.ok) { const error = Object.assign(new Error(errorDetail(await response.json().catch(() => ({})))), { status: response.status }); notifyExpired(error, token); throw error }
    return response.blob()
  },
  estimateAudio: (projectId: number) => request<{ estimate_fen: number; estimate_yuan: number }>(`/api/printfilm-studio/projects/${projectId}/audio/estimate`),
  estimateImage: (projectId: number, params: { model_id: string; resolution: string; ratio: string; count: number }) => request<{ estimate_fen: number; estimate_yuan: number }>(`/api/printfilm-studio/projects/${projectId}/image/estimate`, { method: 'POST', body: JSON.stringify(params) }),
  cancelGeneration: (projectId: number, taskId: string, headers?: HeadersInit) => request<{ ok: boolean; message: string }>(`/api/printfilm-studio/projects/${projectId}/generations/${encodeURIComponent(taskId)}/cancel`, { method: 'POST', headers }),
  analyzeMedia: (projectId: number, file: File, options: { detector: string; threshold: number; minimum: number; frames: boolean; clips: boolean; audio: boolean }, headers?: HeadersInit, signal?: AbortSignal) => {
    const body = new FormData(); body.append('file', file)
    for (const [key, value] of Object.entries(options)) body.append(key, String(value))
    return request<{ report: FrameAnalysisReport; assets: ProjectAsset[] }>(`/api/printfilm-studio/projects/${projectId}/media/analyze`, { method: 'POST', headers, signal, body })
  },
  messageAction: (sessionId: string, messageId: string, action: 'branch' | 'edit_branch' | 'truncate', expected_sequence: number, expected_last_message_id: string) => request<AgentSession>(`/api/printfilm-studio/agent/sessions/${sessionId}/messages/${messageId}/actions`, { method: 'POST', body: JSON.stringify({ action, expected_sequence, expected_last_message_id }) }),
  agentConfig: () => request<{ models: { id: string; label: string }[]; tools: string[]; default_model?: string }>('/api/printfilm-studio/agent/config'),
  updateSession: (id: string, changes: { title?: string; model_id?: string | null }) => request<AgentSession>(`/api/printfilm-studio/agent/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  editMedia: (projectId: number, file: File, options: { operation: MediaOperation; start?: number; end?: number; speed?: number }, headers?: HeadersInit, signal?: AbortSignal) => {
    const body = new FormData(); body.append('file', file)
    for (const [key, value] of Object.entries(options)) if (value !== undefined) body.append(key, String(value))
    return request<{ assets: ProjectAsset[] }>(`/api/printfilm-studio/projects/${projectId}/media/edit`, { method: 'POST', headers, signal, body })
  },
  composeMedia: (projectId: number, urls: string[], headers?: HeadersInit, signal?: AbortSignal) => request<{ assets: ProjectAsset[] }>(`/api/printfilm-studio/projects/${projectId}/media/compose`, { method: 'POST', headers, signal, body: JSON.stringify({ urls }) }),
  listRecipes: (projectId: number) => request<{ recipes: Recipe[] }>(`/api/printfilm-studio/projects/${projectId}/recipes`),
  createRecipe: (projectId: number, name: string, document: unknown) => request<Recipe>(`/api/printfilm-studio/projects/${projectId}/recipes`, { method: 'POST', body: JSON.stringify({ name, document }) }),
  deleteRecipe: (id: string) => request<{ ok: boolean }>(`/api/printfilm-studio/recipes/${id}`, { method: 'DELETE' }),
  /** 读取或初始化当前项目的工作室画布。 */
  getCanvas: (projectId: number, signal?: AbortSignal) => request<CanvasResponse>(`/api/printfilm-studio/projects/${projectId}/canvas`, { signal }),
  /** 获取项目已有资产，供画布资产库和节点创建使用。 */
  getAssets: (projectId: number) => request<{ assets: ProjectAsset[] }>(`/api/printfilm-studio/projects/${projectId}/canvas/assets`),
  importAsset: (projectId: number, assetId: number, headers?: HeadersInit) => request<ProjectAsset>(`/api/printfilm-studio/projects/${projectId}/canvas/assets/${assetId}/import`, { method: 'POST', headers }),
  uploadAsset: (projectId: number, file: File, headers?: HeadersInit, signal?: AbortSignal) => {
    const body = new FormData(); body.append('file', file)
    return request<ProjectAsset>(`/api/printfilm-studio/projects/${projectId}/canvas/assets/upload`, { method: 'POST', headers, body, signal })
  },
  /** 按版本号保存画布；团队项目需附带编辑锁请求头。 */
  saveCanvas: (projectId: number, document: unknown, expectedVersion: number, headers?: HeadersInit) => request<CanvasResponse>(`/api/printfilm-studio/projects/${projectId}/canvas`, { method: 'PUT', headers, body: JSON.stringify({ document, expected_version: expectedVersion }) }),
  resetCanvas: (projectId: number, headers?: HeadersInit) => request<CanvasResponse>(`/api/printfilm-studio/projects/${projectId}/canvas/reset`, { method: 'POST', headers }),
  /** 列出当前用户在该项目下的助手会话。 */
  listSessions: (projectId: number) => request<{ sessions: AgentSession[] }>(`/api/printfilm-studio/projects/${projectId}/agent/sessions`),
  /** 新建一条助手会话。 */
  createSession: (projectId: number) => request<AgentSession>(`/api/printfilm-studio/projects/${projectId}/agent/sessions`, { method: 'POST', body: JSON.stringify({}) }),
  /** 读取会话及已保存消息。 */
  getSession: (sessionId: string) => request<AgentSession>(`/api/printfilm-studio/agent/sessions/${sessionId}`),
  /** 请求服务端停止当前流式回复。 */
  stopSession: (sessionId: string) => request<AgentSession>(`/api/printfilm-studio/agent/sessions/${sessionId}/stop`, { method: 'POST' }),
  /** 删除一条助手会话。 */
  deleteSession: (sessionId: string) => request<{ ok: boolean }>(`/api/printfilm-studio/agent/sessions/${sessionId}`, { method: 'DELETE' }),
  stream: (sessionId: string, prompt: string, onEvent: (event: Record<string, unknown>) => void, signal?: AbortSignal, headers?: HeadersInit, options?: AgentOptions) => streamEvents(sessionId, onEvent, signal, headers, prompt, undefined, options),
  resume: (sessionId: string, runId: string, onEvent: (event: Record<string, unknown>) => void, signal?: AbortSignal) => streamEvents(sessionId, onEvent, signal, undefined, undefined, runId),
}

async function streamEvents(sessionId: string, onEvent: (event: Record<string, unknown>) => void, signal?: AbortSignal, headers?: HeadersInit, prompt?: string, runId?: string, options?: AgentOptions) {
  const cursor = createEventCursor(runId)
  const requestId = crypto.randomUUID()
  let failures = 0
  while (!cursor.done) {
    signal?.throwIfAborted()
    const replay = cursor.runId
    const path = replay ? `/api/printfilm-studio/agent/sessions/${sessionId}/runs/${replay}/events?after=${cursor.sequence}` : `/api/printfilm-studio/agent/sessions/${sessionId}/stream`
    const before = cursor.sequence
    const token = localStorage.getItem('token')
    try {
      const init = scopedRequestInit(path, {
        method: replay ? 'GET' : 'POST',
        headers: { Authorization: `Bearer ${token || ''}`, 'Content-Type': 'application/json', ...headers },
        body: replay ? undefined : JSON.stringify({ prompt, request_id: requestId, ...options, node_defaults: readNodeDefaults() }), signal,
      })
      const response = await fetch(`${API_BASE}${path}`, init)
      if (!response.ok) throw Object.assign(new Error(errorDetail(await response.json().catch(() => ({})))), { status: response.status })
      const reader = response.body?.getReader()
      if (!reader) throw new Error('Agent 没有返回事件流')
      const decoder = new TextDecoder()
      let buffer = ''
      const dispatch = (text: string) => {
        for (const event of parseNdjson(text)) {
          if (cursor.accept(event)) onEvent(event)
          if (event.code === 'access_revoked') throw Object.assign(new Error(String(event.message)), { status: 403 })
        }
      }
      try {
        while (true) {
          const chunk = await reader.read()
          if (chunk.done) break
          buffer += decoder.decode(chunk.value, { stream: true })
          const lines = buffer.split(/\r?\n/)
          buffer = lines.pop() || ''
          dispatch(lines.join('\n'))
          if (cursor.done) break
        }
        if (!cursor.done) dispatch(buffer + decoder.decode())
      } finally { await reader.cancel().catch(() => undefined); reader.releaseLock() }
      if (!cursor.done) throw new Error('Agent 连接中断')
    } catch (error) {
      notifyExpired(error, token)
      signal?.throwIfAborted()
      const status = (error as { status?: number }).status
      if (status && status < 500) throw error
      if (cursor.sequence > before) failures = 0
      if (++failures > 3) throw new Error('连接暂时无法恢复。刷新页面可继续读取当前执行，不会重复创建任务')
      onEvent({ type: 'reconnecting', content: '连接中断，正在恢复已完成步骤…' })
      await new Promise<void>((resolve, reject) => {
        const abort = () => { clearTimeout(timer); reject(signal?.reason) }
        const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve() }, failures * 600)
        signal?.addEventListener('abort', abort, { once: true })
      })
    }
  }
}
