import { throwApiError } from '../lib/apiError'

function defaultApiBase() {
  if (typeof window !== 'undefined' && window.location?.hostname) {
    const { protocol, hostname } = window.location
    return `${protocol}//${hostname}:8000`
  }
  return 'http://127.0.0.1:8000'
}

const _viteApiBase = import.meta.env.VITE_API_BASE
const API_BASE =
  _viteApiBase === undefined || _viteApiBase === null ? defaultApiBase() : String(_viteApiBase)

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('token')
  return token
    ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    : { 'Content-Type': 'application/json' }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers || {}) },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throwApiError(res.status, err.detail, `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export type TaskEventOut = {
  id: number
  event_type: string
  status?: string | null
  phase?: string | null
  message?: string | null
  created_at?: string | null
}

export type TaskStepOut = {
  id: number
  step_key: string
  status: string
  attempt?: number
  started_at?: string | null
  finished_at?: string | null
}

export type TaskRunOut = {
  id: number
  domain: string
  task_type: string
  status: string
  progress_percent?: number
  current_step_key?: string | null
  current_step_status?: string | null
  error_code?: string | null
  error_message?: string | null
  provider_task_id?: string | null
  episode_id?: number | null
  fragment_id?: number | null
  drama_project_id?: number | null
  batch_key?: string | null
  created_at?: string | null
  updated_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  steps?: TaskStepOut[]
  events?: TaskEventOut[]
}

export type TaskListOut = {
  items: TaskRunOut[]
  total: number
  page: number
  page_size: number
}

export const tasksApi = {
  // 单任务详情（含 steps / events）
  get: (taskId: number) => request<TaskRunOut>(`/api/tasks/${taskId}`),

  // 按目标筛选最近任务（如 fragment）
  list: (params: {
    page?: number
    page_size?: number
    domain?: string
    task_type?: string
    status?: string
    target_type?: string
    target_id?: number
    drama_project_id?: number
  }) => {
    const q = new URLSearchParams()
    if (params.page) q.set('page', String(params.page))
    if (params.page_size) q.set('page_size', String(params.page_size))
    if (params.domain) q.set('domain', params.domain)
    if (params.task_type) q.set('task_type', params.task_type)
    if (params.status) q.set('status', params.status)
    if (params.target_type) q.set('target_type', params.target_type)
    if (params.target_id) q.set('target_id', String(params.target_id))
    if (params.drama_project_id) q.set('drama_project_id', String(params.drama_project_id))
    const qs = q.toString()
    return request<TaskListOut>(`/api/tasks${qs ? `?${qs}` : ''}`)
  },
}
