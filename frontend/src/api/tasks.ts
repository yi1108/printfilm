import { throwApiError } from '../lib/apiError'
import { createJsonRequester } from './client'

/** 任务 API 沿用 HTTP 状态回退文案，共用统一传输层。 */
const request = createJsonRequester((response, detail) =>
  throwApiError(response.status, detail, `HTTP ${response.status}`),
)

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
  execution_mode?: 'direct' | 'queued'
  queue_type?: 'text' | 'image' | 'video'
  provider_name?: string | null
  provider_status?: string | null
  status: string
  progress_percent?: number
  current_step_key?: string | null
  current_step_status?: string | null
  error_code?: string | null
  error_message?: string | null
  payload?: Record<string, unknown> | null
  result_payload?: Record<string, unknown> | null
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
    queue_type?: 'text' | 'image' | 'video'
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
    if (params.queue_type) q.set('queue_type', params.queue_type)
    if (params.status) q.set('status', params.status)
    if (params.target_type) q.set('target_type', params.target_type)
    if (params.target_id) q.set('target_id', String(params.target_id))
    if (params.drama_project_id) q.set('drama_project_id', String(params.drama_project_id))
    const qs = q.toString()
    return request<TaskListOut>(`/api/tasks${qs ? `?${qs}` : ''}`)
  },
}
